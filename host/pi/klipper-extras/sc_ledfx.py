import math
import logging
import re

def _clamp01(x):
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)

def _rgba(r, g, b, w=0.0):
    return (_clamp01(r), _clamp01(g), _clamp01(b), _clamp01(w))

class ScLedFx:
    """
    Per-lane LED state and overrides without endstop polling.

    Base per-lane logic:
      - GSW open                         -> solid orange (EMPTY)
      - at_gears == lane                 -> breathe white (IN USE)
      - need_lth == 1 and hub busy!=lane -> breathe yellow (WAITING FOR HUB)
      - need_lth == 1                    -> breathe green (NEEDS LTH / hub available)
      - need_lth == 0 and GSW true       -> solid green (READY)

    Overrides (per lane):
      SCLED_SET LANE=4 MODE=REMOVE_BLUE   -> breathe blue (while macro runs)
      SCLED_SET LANE=4 MODE=REMOVE_ORANGE -> blink orange until GSW opens (then auto-clear to orange)
      SCLED_CLEAR LANE=4                  -> clear override
    """

    OV_REMOVE_BLUE   = "REMOVE_BLUE"
    OV_REMOVE_ORANGE = "REMOVE_ORANGE"
    OV_ERROR         = "ERROR"
    OV_LTHRUN        = "LTHRUN"

    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")
        self.reactor = None
        self.shutdown = False
        sec = config.get_name().split()
        inst = sec[1] if len(sec) > 1 else ""
        self.instance = inst
        m = re.search(r"(\d+)$", inst)
        self.cmd_suffix = m.group(1) if m else ""
        self.tag = "SC" + (self.cmd_suffix or "")

        self.gsw_prefix = config.get("gsw_prefix", "").strip()
        self.var_suffix = config.get("var_suffix", self.cmd_suffix).strip()

        def _cmd(name: str) -> str:
            return f"{name}{self.cmd_suffix}"
        self._cmd = _cmd


        chain_spec = config.get("chain", "neopixel:status_led").strip()
        self.chain_name = chain_spec.replace(":", " ")

        self.first_index = config.getint("first_index", 1, minval=1)
        self.lane_count  = config.getint("lane_count", 4, minval=1)

        active = config.get("active_lanes", "").replace(",", " ").split()
        self.active_lanes = set(int(x) for x in active if x.isdigit()) if active else set(range(1, self.lane_count+1))

        self.enabled = config.getboolean("enabled", True)
        fps = config.getfloat("frame_rate", 20.0, minval=1.0, maxval=200.0)
        self.period = 1.0 / fps

        self.breathe_s = config.getfloat("breathe_s", 2.0, minval=0.2, maxval=10.0)
        self.breathe_fast_s = config.getfloat("breathe_fast_s", 0.6, minval=0.1, maxval=10.0)

        self.blink_orange_hz = config.getfloat("blink_orange_hz", 2.0, minval=0.2, maxval=20.0)
        self.blink_error_hz  = config.getfloat("blink_error_hz", 6.0, minval=0.5, maxval=30.0)

        self.c_orange = _rgba(0.80, 0.25, 0.00)
        self.c_yellow = _rgba(1.00, 1.00, 0.00)
        self.c_green  = _rgba(0.00, 0.90, 0.00)
        self.c_white  = _rgba(0.85, 0.85, 0.85)
        self.c_blue   = _rgba(0.00, 0.00, 0.85)
        self.c_red    = _rgba(0.90, 0.00, 0.00)

        try:
            self.chain = self.printer.load_object(config, self.chain_name)
        except Exception as e:
            raise config.error("[sc_ledfx] can't load chain '%s': %s" % (self.chain_name, str(e)))
        if not hasattr(self.chain, "led_helper"):
            raise config.error("[sc_ledfx] chain has no led_helper: %s" % self.chain_name)

        helper = self.chain.led_helper
        self.led_count = getattr(helper, "led_count", 0) or len(getattr(helper, "led_state", []))

        needed = (self.first_index - 1) + self.lane_count
        if self.led_count < needed:
            raise config.error("[sc_ledfx] needs %d LEDs starting at %d, but chain has %d"
                               % (needed, self.first_index, self.led_count))

        self.savevars = None
        self.gsw = {}

        self.ov_mode = {}
        self.ov_until = {}

        self._last = [None] * self.led_count

        self.gcode.register_command(self._cmd("SCLED_STATUS"), self.cmd_status)
        self.gcode.register_command(self._cmd("SCLED_ENABLE"), self.cmd_enable)
        self.gcode.register_command(self._cmd("SCLED_DISABLE"), self.cmd_disable)
        self.gcode.register_command(self._cmd("SCLED_SET"), self.cmd_set)
        self.gcode.register_command(self._cmd("SCLED_CLEAR"), self.cmd_clear)

        self.printer.register_event_handler("klippy:ready", self._handle_ready)
        self.printer.register_event_handler("klippy:shutdown", self._handle_shutdown)

    def _handle_ready(self):
        self.reactor = self.printer.get_reactor()
        self.savevars = self.printer.lookup_object("save_variables", None)
        for lane in range(1, self.lane_count + 1):
            fsname = f"{self.gsw_prefix}l{lane}_gsw"
            self.gsw[lane] = self.printer.lookup_object(f"filament_switch_sensor {fsname}", None)
        self.reactor.register_timer(self._tick, self.reactor.NOW)
        logging.info("sc_ledfx ready: chain=%s active=%s", self.chain_name, sorted(self.active_lanes))

    def _handle_shutdown(self):
        self.shutdown = True

    def cmd_enable(self, gcmd):
        self.enabled = True
        gcmd.respond_info("SCLED: enabled=1")

    def cmd_disable(self, gcmd):
        self.enabled = False
        gcmd.respond_info("SCLED: enabled=0")

    def cmd_set(self, gcmd):
        try:
            lane = int((gcmd.get("LANE", "") or "0"))
            mode = (gcmd.get("MODE", "") or "").strip().upper()
        except Exception:
            gcmd.respond_info("SCLED_SET ignored: bad args")
            return
        if lane < 1 or lane > self.lane_count:
            gcmd.respond_info("SCLED_SET ignored: invalid LANE")
            return
        if mode not in (self.OV_REMOVE_BLUE, self.OV_REMOVE_ORANGE, self.OV_ERROR, self.OV_LTHRUN):
            gcmd.respond_info("SCLED_SET ignored: invalid MODE")
            return
        timeout = 0.0
        try:
            timeout = float(gcmd.get("TIMEOUT", 0.0) or 0.0)
        except Exception:
            timeout = 0.0
        self.ov_mode[lane] = mode
        self.ov_until[lane] = None
        if timeout > 0.0 and self.reactor is not None:
            self.ov_until[lane] = self.reactor.monotonic() + timeout
        gcmd.respond_info(f"SCLED: lane {lane} override {mode}")

    def cmd_clear(self, gcmd):
        try:
            lane_s = (gcmd.get("LANE", "") or "").strip()
        except Exception:
            lane_s = ""
        if lane_s:
            try:
                lane = int(lane_s)
            except Exception:
                return
            self.ov_mode.pop(lane, None)
            self.ov_until.pop(lane, None)
        else:
            self.ov_mode.clear()
            self.ov_until.clear()
        gcmd.respond_info("SCLED: override cleared")

    def cmd_status(self, gcmd):
        et = self.reactor.monotonic() if self.reactor else 0.0
        vars_ = self._vars(et)
        hub = int(vars_.get(self._hub_key(), 0) or 0)
        atg = int(vars_.get(self._atg_key(), 0) or 0)
        parts = [f"hub={hub} at_gears={atg} active={sorted(self.active_lanes)}"]
        for lane in sorted(self.active_lanes):
            g = 1 if self._gsw_state(lane, et) else 0
            n = int(vars_.get(self._need_key(lane), 0) or 0)
            ov = self.ov_mode.get(lane, "AUTO")
            parts.append(f"L{lane}:gsw={g} need={n} ov={ov}")
        gcmd.respond_info("SCLED: " + " ".join(parts))


    def _hub_key(self) -> str:
        s = self.var_suffix
        return f"hub_owner{s}" if s else "hub_owner"

    def _atg_key(self) -> str:
        s = self.var_suffix
        return f"at_gears{s}" if s else "at_gears"

    def _need_key(self, lane: int) -> str:
        s = self.var_suffix
        return f"need_lth{lane}{s}" if s else f"need_lth{lane}"

    def _vars(self, eventtime):
        if not self.savevars:
            return {}
        try:
            st = self.savevars.get_status(eventtime) or {}
            return st.get("variables", {}) or {}
        except Exception:
            return {}

    def _gsw_state(self, lane, eventtime):
        fs = self.gsw.get(lane)
        if not fs:
            return False
        try:
            st = fs.get_status(eventtime) or {}
            return bool(st.get("filament_detected", False))
        except Exception:
            return False

    def _breathe(self, base, t, period_s, floor=0.20):
        k = floor + (1.0 - floor) * 0.5 * (1.0 + math.sin(2.0*math.pi*(t/period_s)))
        return _rgba(base[0]*k, base[1]*k, base[2]*k, base[3]*k)

    def _blink(self, base, t, hz, dim=0.0):
        on = (int(t * hz) & 1) == 0
        k = 1.0 if on else dim
        return _rgba(base[0]*k, base[1]*k, base[2]*k, base[3]*k)

    def _idx0(self, lane):
        return (self.first_index - 1) + (lane - 1)

    def _transmit(self):
        self.chain.led_helper.need_transmit = True
        if hasattr(self.chain.led_helper, "_check_transmit"):
            self.chain.led_helper._check_transmit()
        else:
            self.chain.led_helper.check_transmit(None)

    def _tick(self, eventtime):
        if self.shutdown:
            return eventtime + 1.0
        if not self.enabled:
            return eventtime + 0.5

        try:
            t = eventtime
            vars_ = self._vars(eventtime)
            hub = int(vars_.get(self._hub_key(), 0) or 0)
            atg = int(vars_.get(self._atg_key(), 0) or 0)

            now = self.reactor.monotonic() if self.reactor else 0.0
            for lane, until in list(self.ov_until.items()):
                if until is not None and now >= until:
                    self.ov_mode.pop(lane, None)
                    self.ov_until.pop(lane, None)

            changed = False

            for lane in range(1, self.lane_count + 1):
                if lane not in self.active_lanes:
                    continue

                gsw = self._gsw_state(lane, eventtime)
                need = int(vars_.get(self._need_key(lane), 0) or 0)

                ov = self.ov_mode.get(lane)

                if ov in (self.OV_REMOVE_BLUE, self.OV_REMOVE_ORANGE) and not gsw:
                    self.ov_mode.pop(lane, None)
                    self.ov_until.pop(lane, None)
                    ov = None

                if ov == self.OV_REMOVE_BLUE:
                    color = self._breathe(self.c_blue, t, self.breathe_s)
                elif ov == self.OV_REMOVE_ORANGE:
                    color = self._blink(self.c_orange, t, self.blink_orange_hz, dim=0.0)
                elif ov == self.OV_ERROR:
                    color = self._blink(self.c_red, t, self.blink_error_hz, dim=0.0)
                elif ov == self.OV_LTHRUN:
                    color = self._breathe(self.c_green, t, self.breathe_fast_s, floor=0.10)
                else:
                    if not gsw:
                        color = self.c_orange
                    elif atg == lane:
                        color = self._breathe(self.c_white, t, self.breathe_s)
                    elif need != 0 and hub != 0 and hub != lane:
                        color = self._breathe(self.c_yellow, t, self.breathe_s)
                    elif need != 0:
                        color = self._breathe(self.c_green, t, self.breathe_s)
                    else:
                        color = self.c_green

                idx0 = self._idx0(lane)
                if self._last[idx0] != color:
                    self.chain.led_helper.led_state[idx0] = color
                    self._last[idx0] = color
                    changed = True

            if changed:
                self._transmit()

        except Exception:
            logging.exception("sc_ledfx tick exception; disabling")
            self.enabled = False

        return eventtime + self.period

def load_config_prefix(config):
    return ScLedFx(config)
