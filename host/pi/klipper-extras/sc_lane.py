
import logging
import re


class SCLane:
    def __init__(self, config):
        self.config = config
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")
        self.reactor = self.printer.get_reactor()

        sec = config.get_name().split()
        inst = sec[1] if len(sec) > 1 else ""
        self.instance = inst
        m2 = re.search(r"(\d+)$", inst)
        self.cmd_suffix = m2.group(1) if m2 else ""
        self.tag = "SC" + (self.cmd_suffix or "")

        default_prefix = "SC"
        if inst:
            m = re.search(r"(\d+)$", inst)
            default_prefix = "SC" + m.group(1) if m else ("SC_" + inst.upper())
        self.cmd_prefix = config.get("cmd_prefix", default_prefix).strip()
        def _cmd(name: str) -> str:
            return f"{name}{self.cmd_suffix}"
        self._cmd = _cmd
        self.hsw_pin = config.get("hsw_pin", "^gpio36").strip()
        self.bfcompsw_pin = config.get("bfcompsw_pin", "^gpio37").strip()

        self._lanes = {}
        self._lanes_present = []
        self._es_map = {}
        self._gsw = {}

        l1_stepper = config.get("stepper", "bt_lane1").strip()
        l1_gsw = config.get("gsw", "l1_gsw").strip()
        l1_rsw_pin = config.get("rsw_pin", "^gpio29").strip()

        def default_rsw_pin(lane: int) -> str:
            return f"^gpio{27 + 2*lane}"

        for lane in (1, 2, 3, 4):
            if lane == 1:
                stepper = l1_stepper
                gsw_name = l1_gsw
                rsw_pin = l1_rsw_pin
            else:
                stepper = config.get(f"lane{lane}_stepper", f"bt_lane{lane}").strip()
                gsw_name = config.get(f"lane{lane}_gsw", f"l{lane}_gsw").strip()
                rsw_pin = config.get(f"lane{lane}_rsw_pin", default_rsw_pin(lane)).strip()

            self._lanes[lane] = {"stepper": stepper, "gsw": gsw_name, "rsw_pin": rsw_pin}
            self._gsw[lane] = None

        self._setup_endstops_config_time()

        self.printer.register_event_handler("klippy:ready", self._on_ready)

        self.gcode.register_command(self._cmd("SCPING"), self.cmd_ping, desc="SideCar: verify sc_lane extra is loaded")

        self.gcode.register_command(self._cmd("SC_HUB_FREE"), self.cmd_hub_free, desc="SideCar: error if HSW is triggered (hub occupied) unless FORCE=1")

        for lane in self._lanes_present:
            self.gcode.register_command(
                self._cmd(f"SCSTATUS{lane}"),
                self._make_cmd_status(lane),
                desc=f"SideCar: lane{lane} status",
            )
            self.gcode.register_command(
                self._cmd(f"SCFWD{lane}"),
                self._make_cmd_jog(lane, forward=True),
                desc=f"SideCar: lane{lane} jog forward +MM @ SPEED",
            )
            self.gcode.register_command(
                self._cmd(f"SCREV{lane}"),
                self._make_cmd_jog(lane, forward=False),
                desc=f"SideCar: lane{lane} jog reverse -MM @ SPEED",
            )
            self.gcode.register_command(
                self._cmd(f"SCDIS{lane}"),
                self._make_cmd_dis(lane),
                desc=f"SideCar: lane{lane} disable stepper",
            )

        self.gcode.register_command(self._cmd("SCLHOME"), self.cmd_home,
            desc="SideCar: smooth move until selected endstop (RSW/HSW/BFCOMPSW) LANE="
        )
        self.gcode.register_command(self._cmd("SCLTH"), self.cmd_lth,
            desc="SideCar: LTH (fast hit HSW, slow poke x2, retract 30mm) LANE="
        )
        self.gcode.register_command(self._cmd("SCLUNLOAD"), self.cmd_unload,
            desc="SideCar: unload to hub-clear (open HSW if needed, then extra retract) LANE="
        )
        self.gcode.register_command(self._cmd("SCLREMOVE"), self.cmd_remove,
            desc="SideCar: remove spool (open RSW if needed, then extra retract) LANE="
        )
        self.gcode.register_command(self._cmd("SCLPRELOAD"), self.cmd_preload,
            desc="SideCar: preload (feed until RSW closes) LANE="
        )


    def _on_ready(self):
        for lane in self._lanes_present:
            gsw_name = self._lanes[lane]["gsw"]
            try:
                self._gsw[lane] = self.printer.lookup_object(f"filament_switch_sensor {gsw_name}")
            except Exception:
                self._gsw[lane] = None
                logging.info("SC: lane%d GSW sensor '%s' not found (gating will require FORCE=1)", lane, gsw_name)

    def _now(self):
        return self.reactor.monotonic()


    def _get_lane(self, gcmd, default=1) -> int:
        lane = int(gcmd.get_int("LANE", default))
        if lane not in self._lanes_present:
            raise self.printer.command_error(f"LANE must be one of {self._lanes_present}")
        return lane

    def _stepper_name(self, lane: int) -> str:
        return self._lanes[lane]["stepper"]

    def _manual_stepper(self, lane: int):
        return self.printer.lookup_object(f"manual_stepper {self._stepper_name(lane)}")

    def _gsw_state(self, lane: int) -> bool:
        obj = self._gsw.get(lane)
        if obj is None:
            return False
        st = obj.get_status(self._now())
        return bool(st.get("filament_detected", False))

    def _enable(self, lane: int, on: bool):
        self.gcode.run_script_from_command(
            f"MANUAL_STEPPER STEPPER={self._stepper_name(lane)} ENABLE={'1' if on else '0'}"
        )

    def _set_pos0(self, lane: int):
        self.gcode.run_script_from_command(
            f"MANUAL_STEPPER STEPPER={self._stepper_name(lane)} SET_POSITION=0"
        )

    def _move_rel(self, lane: int, mm: float, speed: float):
        self._set_pos0(lane)
        self.gcode.run_script_from_command(
            f"MANUAL_STEPPER STEPPER={self._stepper_name(lane)} MOVE={mm:.4f} SPEED={float(speed):.3f}"
        )

    def _stop_flags_from_int(self, stop: int):
        triggered = stop > 0
        check_triggered = abs(stop) == 1
        return triggered, check_triggered

    def _setup_endstops_config_time(self):
        ppins = self.printer.lookup_object("pins")
        qes = self.printer.lookup_object("query_endstops")

        self._lanes_present = []
        for lane in (1, 2, 3, 4):
            stepper = self._lanes[lane]["stepper"]
            try:
                self.printer.lookup_object(f"manual_stepper {stepper}")
            except Exception as e:
                if lane == 1:
                    raise self.config.error(
                        f"[sc_lane] could not find manual_stepper {stepper}. "
                        f"Put [sc_lane] AFTER the [manual_stepper {stepper}] section. ({e})"
                    )
                logging.info("SC: sc_lane skipping lane%d (manual_stepper %s not found)", lane, stepper)
                continue
            self._lanes_present.append(lane)

        if not self._lanes_present:
            raise self.config.error("[sc_lane] no lanes present (no manual_stepper objects found)")

        mcu_hsw = ppins.setup_pin("endstop", self.hsw_pin)
        mcu_bf = ppins.setup_pin("endstop", self.bfcompsw_pin)

        lbls = getattr(self, "cmd_suffix", "")


        for lane in self._lanes_present:
            ms = self._manual_stepper(lane)
            for s in ms.steppers:
                mcu_hsw.add_stepper(s)
                mcu_bf.add_stepper(s)

        qes.register_endstop(mcu_hsw, "HSW" + lbls)
        qes.register_endstop(mcu_bf, "BFCOMPSW" + lbls)

        for lane in self._lanes_present:
            ms = self._manual_stepper(lane)
            rsw_pin = self._lanes[lane]["rsw_pin"]

            mcu_rsw = ppins.setup_pin("endstop", rsw_pin)
            for s in ms.steppers:
                mcu_rsw.add_stepper(s)

            base = "RSW" if lane == 1 else f"L{lane}RSW"
            label = base + lbls
            qes.register_endstop(mcu_rsw, label)

            self._es_map[lane] = {
                "RSW": (mcu_rsw, label),
                "HSW": (mcu_hsw, "HSW" + lbls),
                "BFCOMPSW": (mcu_bf, "BFCOMPSW" + lbls),
            }

        logging.info(
            self._cmd("SC: sc_lane registered endstops at config time: lanes=%s RSW_pins=%s HSW=%s BFCOMPSW=%s"),
            self._lanes_present,
            {lane: self._lanes[lane]['rsw_pin'] for lane in self._lanes_present},
            self.hsw_pin,
            self.bfcompsw_pin,
        )

    def _home_rel(self, lane: int, endstop: str, move: float, speed: float, accel: float, stop: int, label: str):
        endstop = endstop.strip().upper()
        if endstop not in ("RSW", "HSW", "BFCOMPSW"):
            raise self.printer.command_error("ENDSTOP must be RSW, HSW, or BFCOMPSW")

        ms = self._manual_stepper(lane)
        ms.homing_accel = float(accel)

        mcu_es, es_name = self._es_map[lane][endstop]
        triggered, check_triggered = self._stop_flags_from_int(int(stop))

        self.gcode.respond_info(f"{self.tag}: {label} LANE={lane} ENDSTOP={endstop} MOVE={move} SPEED={speed} ACCEL={accel} STOP={stop}"
        )

        self._set_pos0(lane)

        phoming = self.printer.lookup_object("homing")
        pos = [float(move), 0.0, 0.0, 0.0]
        phoming.manual_home(ms, [(mcu_es, es_name)], pos, float(speed),
                            triggered, check_triggered)


    def _make_cmd_status(self, lane: int):
        def _cmd(gcmd):
            g = int(self._gsw_state(lane))
            self.gcode.respond_info(f"{self.tag}: lane{lane} GSW={g} | endstops={list(self._es_map[lane].keys())} (use QUERY_ENDSTOPS)"
            )
        return _cmd

    def _make_cmd_dis(self, lane: int):
        def _cmd(gcmd):
            self._enable(lane, False)
            self.gcode.respond_info(f"{self.tag}: lane{lane} disabled")
        return _cmd

    def _make_cmd_jog(self, lane: int, forward: bool):
        def _cmd(gcmd):
            mm = gcmd.get_float("MM", 10.0)
            sp = gcmd.get_float("SPEED", 5.0)
            self._enable(lane, True)
            try:
                self._move_rel(lane, abs(mm) if forward else -abs(mm), sp)
            finally:
                self._enable(lane, False)
        return _cmd


    def cmd_ping(self, gcmd):
        self.gcode.respond_info(f"{self.tag}: sc_lane.py loaded (SCPING ok)")


    def cmd_hub_free(self, gcmd):
        lane = int(gcmd.get_int("LANE", 1))
        force = int(gcmd.get_int("FORCE", 0))

        esmap = getattr(self, "_es_map", getattr(self, "_lane_es_map", None))
        if esmap is None or lane not in esmap:
            raise gcmd.error(f"SC_HUB_FREE: invalid lane {lane}")

        mcu_hsw, _lbl = esmap[lane]["HSW"]
        toolhead = self.printer.lookup_object("toolhead")
        pt = toolhead.get_last_move_time()
        busy = bool(mcu_hsw.query_endstop(pt))

        if busy and not force:
            raise gcmd.error(f"Hub busy (HSW triggered). Unload hub filament first, or FORCE=1 (lane{lane})")
        if busy and force:
            self.gcode.respond_info(f"{self.tag}: hub busy but FORCE=1 override (lane{lane})")
        else:
            self.gcode.respond_info(f"{self.tag}: hub free (lane{lane})")

    def cmd_home(self, gcmd):
        lane = self._get_lane(gcmd, default=1)
        endstop = gcmd.get("ENDSTOP", "HSW")
        move = gcmd.get_float("MOVE")
        speed = gcmd.get_float("SPEED", 10.0)
        stop = int(gcmd.get_int("STOP", 1))

        ms = self._manual_stepper(lane)
        accel = gcmd.get_float("ACCEL", ms.homing_accel, minval=0.0)

        self._enable(lane, True)
        try:
            self._home_rel(lane, endstop, move, speed, accel, stop, "SCLHOME")
            self.gcode.respond_info(f"{self.tag}: SCLHOME OK (lane{lane})")
        finally:
            self._enable(lane, False)

    def cmd_lth(self, gcmd):
        lane = self._get_lane(gcmd, default=1)

        force = int(gcmd.get_int("FORCE", 0))
        if not self._gsw_state(lane) and force == 0:
            self.gcode.respond_info(f"{self.tag}: SCLTH blocked (lane{lane} GSW open/missing)  (use FORCE=1 to override)")
            return
        if force == 0:
            mcu_rsw, _label = self._es_map[lane]["RSW"]
            toolhead = self.printer.lookup_object("toolhead")
            pt = toolhead.get_last_move_time()
            if not mcu_rsw.query_endstop(pt):
                self.gcode.respond_info(f"{self.tag}: SCLTH blocked (lane{lane} RSW open - run preload/auto-grab first, or FORCE=1)"
                )
                return

        ms = self._manual_stepper(lane)
        accel = gcmd.get_float("ACCEL", ms.homing_accel, minval=0.0)

        fast = gcmd.get_float("FAST", 20.0)
        seek = gcmd.get_float("SEEK", 600.0)

        poke_speed = gcmd.get_float("POKESPEED", 5.0)
        poke_mm = gcmd.get_float("POKEMM", 10.0)
        back_max = gcmd.get_float("BACK", 15.0)

        pokes = int(gcmd.get_int("POKES", 2))
        retract = gcmd.get_float("RETRACT", 30.0)

        self.gcode.respond_info(f"{self.tag}: SCLTH start lane{lane} (fast->HSW, poke x{pokes}, retract {retract}mm)"
        )

        self._enable(lane, True)
        try:
            self._home_rel(lane, "HSW", seek, fast, accel, 1, "SCLTH FAST_HIT")

            for i in range(max(1, pokes)):
                self._home_rel(lane, "HSW", -back_max, poke_speed, accel, -1, f"SCLTH OPEN {i+1}/{pokes}")
                self._home_rel(lane, "HSW", poke_mm, poke_speed, accel, 1, f"SCLTH POKE {i+1}/{pokes}")

            self._move_rel(lane, -retract, poke_speed)

            self.gcode.respond_info(f"{self.tag}: SCLTH OK (lane{lane})")
        finally:
            self._enable(lane, False)

    def cmd_unload(self, gcmd):
        lane = self._get_lane(gcmd, default=1)

        ms = self._manual_stepper(lane)
        accel = gcmd.get_float("ACCEL", ms.homing_accel, minval=0.0)

        speed = gcmd.get_float("SPEED", 10.0)
        openmove = gcmd.get_float("OPENMOVE", 2000.0)
        extra = gcmd.get_float("EXTRA", 30.0)

        retry = gcmd.get_int("RETRY", 1, minval=0, maxval=3)
        retry_speed = gcmd.get_float("RETRY_SPEED", max(1.0, float(speed) * 0.60), minval=0.1)
        retry_accel = gcmd.get_float("RETRY_ACCEL", max(1.0, float(accel) * 0.50), minval=0.0)
        retry_openmove = gcmd.get_float("RETRY_OPENMOVE", float(openmove), minval=0.1)
        retry_extra = gcmd.get_float("RETRY_EXTRA", float(extra), minval=0.0)

        if openmove <= 0:
            raise gcmd.error("OPENMOVE must be > 0")
        if extra < 0:
            raise gcmd.error("EXTRA must be >= 0")

        self.gcode.respond_info(f"{self.tag}: SCLUNLOAD start lane{lane} (open HSW if needed, then -{extra}mm extra)"
        )

        self._enable(lane, True)
        try:
            try:
                self._home_rel(lane, "HSW", -openmove, speed, accel, -1, "SCLUNLOAD OPEN")
                if extra > 0:
                    self._move_rel(lane, -extra, speed)
                self.gcode.respond_info(f"{self.tag}: SCLUNLOAD OK (lane{lane})")
            except Exception as first_err:
                if retry <= 0:
                    raise
                self.gcode.respond_info(
                    f"{self.tag}: SCLUNLOAD first attempt failed lane{lane}; retrying slower "
                    f"(speed={retry_speed:.3f} accel={retry_accel:.3f})"
                )
                self._home_rel(lane, "HSW", -retry_openmove, retry_speed, retry_accel, -1, "SCLUNLOAD RETRY OPEN")
                if retry_extra > 0:
                    self._move_rel(lane, -retry_extra, retry_speed)
                self.gcode.respond_info(f"{self.tag}: SCLUNLOAD RETRY OK (lane{lane})")
        finally:
            self._enable(lane, False)

    def cmd_remove(self, gcmd):
        lane = self._get_lane(gcmd, default=1)

        ms = self._manual_stepper(lane)
        accel = gcmd.get_float("ACCEL", ms.homing_accel, minval=0.0)

        speed = gcmd.get_float("SPEED", 10.0)
        openmove = gcmd.get_float("OPENMOVE", 4000.0)
        extra = gcmd.get_float("EXTRA", 50.0)

        if openmove <= 0:
            raise gcmd.error("OPENMOVE must be > 0")
        if extra < 0:
            raise gcmd.error("EXTRA must be >= 0")

        self.gcode.respond_info(f"{self.tag}: SCLREMOVE start lane{lane} (open RSW if needed, then -{extra}mm extra)"
        )

        self._enable(lane, True)
        try:
            self._home_rel(lane, "RSW", -openmove, speed, accel, -2, "SCLREMOVE OPEN")
            mcu_rsw, _lbl = self._es_map[lane]["RSW"]
            toolhead = self.printer.lookup_object("toolhead")
            pt = toolhead.get_last_move_time()
            if mcu_rsw.query_endstop(pt):
                raise gcmd.error(
                    f"SCLREMOVE failed (lane{lane}): RSW still triggered after OPENMOVE={openmove}. "
                    "Increase OPENMOVE or check filament path/switch."
                )

            if extra > 0:
                self._move_rel(lane, -extra, speed)
            self.gcode.respond_info(f"{self.tag}: SCLREMOVE OK (lane{lane})")
        finally:
            self._enable(lane, False)

    def cmd_preload(self, gcmd):
        lane = self._get_lane(gcmd, default=1)

        if not self._gsw_state(lane) and int(gcmd.get_int("FORCE", 0)) == 0:
            self.gcode.respond_info(f"{self.tag}: SCLPRELOAD blocked (lane{lane} GSW open/missing)  (use FORCE=1 to override)")
            return

        ms = self._manual_stepper(lane)
        accel = gcmd.get_float("ACCEL", ms.homing_accel, minval=0.0)

        speed = gcmd.get_float("SPEED", 10.0)
        move = gcmd.get_float("MOVE", 200.0)

        self.gcode.respond_info(f"{self.tag}: SCLPRELOAD start lane{lane} (feed until RSW closes)")

        self._enable(lane, True)
        try:
            self._home_rel(lane, "RSW", move, speed, accel, 1, "SCLPRELOAD")
            self.gcode.respond_info(f"{self.tag}: SCLPRELOAD OK (lane{lane})")
        finally:
            self._enable(lane, False)




def load_config_prefix(config):
    return SCLane(config)

def load_config(config):
    return SCLane(config)
