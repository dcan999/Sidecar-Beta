#!/usr/bin/env python3
import json, os, socket, threading, time, urllib.request, urllib.parse
import re
import websocket

from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

PURGE_TEMP_C = int(os.getenv("PURGE_TEMP_C", "220"))
PURGE_FAST_MM = float(os.getenv("PURGE_FAST_MM", "45"))
PURGE_FAST_V = float(os.getenv("PURGE_FAST_V", "10.0"))
PURGE_SLOW_V = float(os.getenv("PURGE_SLOW_V", "4.0"))
PURGE_FAST_A = float(os.getenv("PURGE_FAST_A", "0.0"))
PARK_TEMP_UI_C    = int(os.getenv("PARK_TEMP_UI_C", "0"))
PARK_TEMP_PRINT_C = int(os.getenv("PARK_TEMP_PRINT_C", "140"))
U1_HTTP = os.getenv("U1_HTTP", "http://10.42.0.10:7125").rstrip("/")
U1_WS   = os.getenv("U1_WS",   "ws://10.42.0.10:7125/websocket").rstrip("/")
BT_HTTP = os.getenv("BT_HTTP", "http://127.0.0.1:7125").rstrip("/")
SC_HEADS_CFG = os.getenv("SC_HEADS_CFG", "/home/sidecar/sidecar/state/sc_heads.json")
SC_API_HOST  = os.getenv("SC_API_HOST", "0.0.0.0")
SC_API_PORT  = int(os.getenv("SC_API_PORT", "8090"))


SERVO_CFG = os.getenv("SERVO_CFG", "/home/sidecar/sidecar/state/servo_mapping.json")
SERVO_PORTS = os.getenv("SERVO_PORTS", "6,13,19,26")
SERVO_PERIOD_NS = int(os.getenv("SERVO_PERIOD_NS", "20000000"))
SERVO_CENTER_US = int(os.getenv("SERVO_CENTER_US", "1500"))
SERVO_BOOT_US = int(os.getenv("SERVO_BOOT_US", "1500"))
SERVO_IDENT_SAFE_LO_US = int(os.getenv("SERVO_IDENT_SAFE_LO_US", "1200"))
SERVO_IDENT_SAFE_HI_US = int(os.getenv("SERVO_IDENT_SAFE_HI_US", "1800"))
SERVO_TOOLHEAD_DEFAULTS = {
    "1": {"closed_us": 1800, "open_us": 1225, "min_us": 1225, "max_us": 1800},
    "2": {"closed_us": 1100, "open_us": 1800, "min_us": 1100, "max_us": 1800},
    "3": {"closed_us": 1150, "open_us": 1860, "min_us": 1150, "max_us": 1860},
    "4": {"closed_us": 1175, "open_us": 1875, "min_us": 1175, "max_us": 1875},
}
SERVO_IDENT_DEFAULTS = {"lo_us": SERVO_IDENT_SAFE_LO_US, "hi_us": SERVO_IDENT_SAFE_HI_US, "period_ms": 400}

_servo_cfg_lock = threading.RLock()

_ident_lock = threading.Lock()
_ident_stop = threading.Event()
_ident_thread = None
_ident_port = None

_pwm_cache_lock = threading.Lock()
_pwm0_cache = {}

def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")

def servo_ports():
    parts = [p.strip() for p in str(SERVO_PORTS).split(",") if p.strip()]
    try:
        gpios = [int(p) for p in parts]
    except Exception:
        gpios = []
    if len(gpios) != 4:
        gpios = [6, 13, 19, 26]
    return {i + 1: gpios[i] for i in range(4)}

def _servo_cfg_default():
    ports = servo_ports()
    return {
        "version": 1,
        "boot_us": int(SERVO_BOOT_US),
        "identify": dict(SERVO_IDENT_DEFAULTS),
        "toolheads": dict(SERVO_TOOLHEAD_DEFAULTS),
        "ports": {str(k): {"gpio": int(v)} for k, v in ports.items()},
        "toolhead_to_port": {},
        "updated_at": _now_iso(),
    }

def servo_cfg_load():
    with _servo_cfg_lock:
        try:
            if not os.path.exists(SERVO_CFG):
                cfg = _servo_cfg_default()
                servo_cfg_save(cfg)
                return cfg
            with open(SERVO_CFG, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            dirty = False
            if not isinstance(cfg, dict):
                cfg = _servo_cfg_default()
                dirty = True
            if "ports" not in cfg:
                cfg["ports"] = _servo_cfg_default()["ports"]
                dirty = True
            if "toolhead_to_port" not in cfg:
                cfg["toolhead_to_port"] = {}
                dirty = True
            if "boot_us" not in cfg:
                cfg["boot_us"] = int(SERVO_BOOT_US)
                dirty = True
            if "identify" not in cfg:
                cfg["identify"] = dict(SERVO_IDENT_DEFAULTS)
                dirty = True
            if "toolheads" not in cfg:
                cfg["toolheads"] = dict(SERVO_TOOLHEAD_DEFAULTS)
                dirty = True
            if dirty:
                try:
                    servo_cfg_save(cfg)
                except Exception:
                    pass
            return cfg
        except Exception:
            cfg = _servo_cfg_default()
            try:
                servo_cfg_save(cfg)
            except Exception:
                pass
            return cfg

def servo_cfg_save(cfg):
    with _servo_cfg_lock:
        os.makedirs(os.path.dirname(SERVO_CFG), exist_ok=True)
        cfg = dict(cfg)
        cfg["updated_at"] = _now_iso()
        tmp = SERVO_CFG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, SERVO_CFG)

def servo_cfg_set_mapping(toolhead: int, port: int):
    toolhead = int(toolhead)
    port = int(port)
    if toolhead not in (1, 2, 3, 4):
        raise ValueError("bad_toolhead")
    if port not in (1, 2, 3, 4):
        raise ValueError("bad_port")
    cfg = servo_cfg_load()
    m = cfg.get("toolhead_to_port") or {}
    for th, p in list(m.items()):
        try:
            if int(p) == port and int(th) != toolhead:
                m.pop(th, None)
        except Exception:
            pass
    m[str(toolhead)] = port
    cfg["toolhead_to_port"] = m
    servo_cfg_save(cfg)
    return cfg

def servo_cfg_reset():
    cfg = servo_cfg_load()
    cfg["toolhead_to_port"] = {}
    servo_cfg_save(cfg)
    return cfg

LANE_META_CFG = os.getenv("LANE_META_CFG", "/home/sidecar/sidecar/state/lane_meta.json")
_lane_meta_lock = threading.RLock()

def _lane_meta_default_lane():
    return {
        "color": "",
        "material": "",
    }

def _lane_meta_default():
    return {
        "version": 1,
        "toolheads": {
            "1": {"lanes": {"1": _lane_meta_default_lane(), "2": _lane_meta_default_lane(), "3": _lane_meta_default_lane(), "4": _lane_meta_default_lane()}},
            "2": {"lanes": {"1": _lane_meta_default_lane(), "2": _lane_meta_default_lane(), "3": _lane_meta_default_lane(), "4": _lane_meta_default_lane()}},
            "3": {"lanes": {"1": _lane_meta_default_lane(), "2": _lane_meta_default_lane(), "3": _lane_meta_default_lane(), "4": _lane_meta_default_lane()}},
            "4": {"lanes": {"1": _lane_meta_default_lane(), "2": _lane_meta_default_lane(), "3": _lane_meta_default_lane(), "4": _lane_meta_default_lane()}},
        },
        "updated_at": _now_iso(),
    }

def _lane_meta_norm(cfg):
    dirty = False

    if not isinstance(cfg, dict):
        cfg = {}
        dirty = True

    if cfg.get("version") != 1:
        cfg["version"] = 1
        dirty = True

    if "updated_at" not in cfg:
        cfg["updated_at"] = _now_iso()
        dirty = True

    toolheads = cfg.get("toolheads")
    if not isinstance(toolheads, dict):
        toolheads = {}
        cfg["toolheads"] = toolheads
        dirty = True

    for th in ("1", "2", "3", "4"):
        th_obj = toolheads.get(th)
        if not isinstance(th_obj, dict):
            th_obj = {}
            toolheads[th] = th_obj
            dirty = True

        lanes = th_obj.get("lanes")
        if not isinstance(lanes, dict):
            lanes = {}
            th_obj["lanes"] = lanes
            dirty = True

        for lane in ("1", "2", "3", "4"):
            cur = lanes.get(lane)
            merged = _lane_meta_default_lane()
            if isinstance(cur, dict):
                if "color" in cur and cur["color"] is not None:
                    merged["color"] = str(cur["color"])
                if "material" in cur and cur["material"] is not None:
                    merged["material"] = str(cur["material"])
            if cur != merged:
                lanes[lane] = merged
                dirty = True

    return cfg, dirty

def lane_meta_load():
    with _lane_meta_lock:
        try:
            if not os.path.exists(LANE_META_CFG):
                cfg = _lane_meta_default()
                lane_meta_save(cfg)
                return cfg

            with open(LANE_META_CFG, "r", encoding="utf-8") as f:
                cfg = json.load(f)

            cfg, dirty = _lane_meta_norm(cfg)
            if dirty:
                try:
                    lane_meta_save(cfg)
                except Exception:
                    pass
            return cfg
        except Exception:
            cfg = _lane_meta_default()
            try:
                lane_meta_save(cfg)
            except Exception:
                pass
            return cfg

def lane_meta_save(cfg):
    with _lane_meta_lock:
        os.makedirs(os.path.dirname(LANE_META_CFG), exist_ok=True)
        cfg, _ = _lane_meta_norm(dict(cfg))
        cfg["updated_at"] = _now_iso()
        tmp = LANE_META_CFG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, LANE_META_CFG)

def lane_meta_get(toolhead=None, lane=None):
    cfg = lane_meta_load()
    if toolhead is None:
        return cfg
    toolhead = int(toolhead)
    if toolhead not in (1, 2, 3, 4):
        raise ValueError("bad_toolhead")
    th = cfg["toolheads"][str(toolhead)]
    if lane is None:
        return th
    lane = int(lane)
    if lane not in (1, 2, 3, 4):
        raise ValueError("bad_lane")
    return th["lanes"][str(lane)]

def lane_meta_set(toolhead, lane, body):
    toolhead = int(toolhead)
    lane = int(lane)
    if toolhead not in (1, 2, 3, 4):
        raise ValueError("bad_toolhead")
    if lane not in (1, 2, 3, 4):
        raise ValueError("bad_lane")

    cfg = lane_meta_load()
    dst = cfg["toolheads"][str(toolhead)]["lanes"][str(lane)]

    if "color" in body:
        dst["color"] = "" if body.get("color") is None else str(body.get("color"))
    if "material" in body:
        dst["material"] = "" if body.get("material") is None else str(body.get("material"))

    lane_meta_save(cfg)
    return cfg, dst


def _servo_us_clamp(us):
    return max(500, min(2500, int(us)))

def servo_cfg_set_toolhead_settings(toolhead: int, closed_us=None, open_us=None):
    toolhead = int(toolhead)
    if toolhead not in (1, 2, 3, 4):
        raise ValueError("bad_toolhead")

    cfg = servo_cfg_load()
    toolheads = cfg.get("toolheads") or {}
    cur = dict(SERVO_TOOLHEAD_DEFAULTS.get(str(toolhead)) or {})
    cur.update(toolheads.get(str(toolhead)) or {})

    if closed_us is not None:
        cur["closed_us"] = _servo_us_clamp(closed_us)
    if open_us is not None:
        cur["open_us"] = _servo_us_clamp(open_us)

    if "closed_us" not in cur or "open_us" not in cur:
        raise ValueError("missing_open_close_us")

    cur["closed_us"] = _servo_us_clamp(cur["closed_us"])
    cur["open_us"] = _servo_us_clamp(cur["open_us"])
    cur["min_us"] = min(int(cur["closed_us"]), int(cur["open_us"]))
    cur["max_us"] = max(int(cur["closed_us"]), int(cur["open_us"]))

    toolheads[str(toolhead)] = cur
    cfg["toolheads"] = toolheads
    servo_cfg_save(cfg)
    return cfg, cur

def servo_toolhead_move_preview(toolhead: int, action: str, us):
    toolhead = int(toolhead)
    action = str(action or "").strip().lower()
    if toolhead not in (1, 2, 3, 4):
        raise ValueError("bad_toolhead")
    if action not in ("open", "close"):
        raise ValueError("bad_action")

    original_cfg = servo_cfg_load()
    preview_cfg = json.loads(json.dumps(original_cfg))
    toolheads = preview_cfg.get("toolheads") or {}
    cur = dict(SERVO_TOOLHEAD_DEFAULTS.get(str(toolhead)) or {})
    cur.update(toolheads.get(str(toolhead)) or {})

    if action == "open":
        cur["open_us"] = _servo_us_clamp(us)
    else:
        cur["closed_us"] = _servo_us_clamp(us)

    cur["min_us"] = min(int(cur["closed_us"]), int(cur["open_us"]))
    cur["max_us"] = max(int(cur["closed_us"]), int(cur["open_us"]))
    toolheads[str(toolhead)] = cur
    preview_cfg["toolheads"] = toolheads

    try:
        servo_cfg_save(preview_cfg)
        st = servo_toolhead_move(toolhead, action)
    finally:
        try:
            servo_cfg_save(original_cfg)
        except Exception:
            pass
    return st

def _pwmchip_for_gpio(gpio: int) -> str:
    base = "/sys/class/pwm"
    for name in sorted(os.listdir(base)):
        if not name.startswith("pwmchip"):
            continue
        dev = os.path.realpath(os.path.join(base, name, "device"))
        node = os.path.basename(dev)
        m = re.search(r"pwm_pio@([0-9a-fA-F]+)$", node)
        if m and int(m.group(1), 16) == int(gpio):
            return os.path.join(base, name)
    raise FileNotFoundError(f"no pwmchip for gpio={gpio}")

def _ensure_pwm0_dir(gpio: int) -> str:
    with _pwm_cache_lock:
        if gpio in _pwm0_cache and os.path.isdir(_pwm0_cache[gpio]):
            return _pwm0_cache[gpio]

    chip = _pwmchip_for_gpio(gpio)
    pwm0 = os.path.join(chip, "pwm0")
    if not os.path.isdir(pwm0):
        with open(os.path.join(chip, "export"), "w") as f:
            f.write("0")
    pwm0 = os.path.join(chip, "pwm0")

    with _pwm_cache_lock:
        _pwm0_cache[gpio] = pwm0
    return pwm0

def _w(path: str, val):
    with open(path, "w") as f:
        f.write(str(val))

def _servo_init_gpio(gpio: int):
    pwm0 = _ensure_pwm0_dir(gpio)
    enable = os.path.join(pwm0, "enable")
    period = os.path.join(pwm0, "period")
    duty = os.path.join(pwm0, "duty_cycle")
    try:
        _w(enable, 0)
    except Exception:
        pass
    _w(period, SERVO_PERIOD_NS)
    _w(duty, int(SERVO_BOOT_US) * 1000)
    _w(enable, 1)

def _servo_set_us_gpio(gpio: int, us: int):
    us = int(us)
    if us < 500: us = 500
    if us > 2500: us = 2500
    pwm0 = _ensure_pwm0_dir(gpio)
    duty = os.path.join(pwm0, "duty_cycle")
    _w(duty, us * 1000)

def servo_identify_stop():
    global _ident_thread, _ident_port
    with _ident_lock:
        _ident_stop.set()
        t = _ident_thread
        port = _ident_port
        _ident_thread = None
        _ident_port = None
    if t:
        try:
            t.join(timeout=1.0)
        except Exception:
            pass
    if port in (1,2,3,4):
        try:
            gpio = int(servo_ports()[int(port)])
            _servo_init_gpio(gpio)
        except Exception:
            pass
    _ident_stop.clear()

def servo_identify_start(port: int, lo_us: int = 1200, hi_us: int = 1800, period_ms: int = 500):
    global _ident_thread, _ident_port
    port = int(port)
    if port not in (1,2,3,4):
        raise ValueError("bad_port")
    gpio = int(servo_ports()[port])

    servo_identify_stop()

    _servo_init_gpio(gpio)

    lo_us = int(lo_us); hi_us = int(hi_us)
    lo_us = max(int(SERVO_IDENT_SAFE_LO_US), min(int(SERVO_IDENT_SAFE_HI_US), lo_us))
    hi_us = max(int(SERVO_IDENT_SAFE_LO_US), min(int(SERVO_IDENT_SAFE_HI_US), hi_us))
    if hi_us < lo_us:
        lo_us, hi_us = hi_us, lo_us
    if hi_us == lo_us:
        if hi_us + 200 <= int(SERVO_IDENT_SAFE_HI_US):
            hi_us = hi_us + 200
        elif lo_us - 200 >= int(SERVO_IDENT_SAFE_LO_US):
            lo_us = lo_us - 200
    period_ms = int(period_ms)
    if period_ms < 100: period_ms = 100

    def _loop():
        a = lo_us
        b = hi_us
        while not _ident_stop.is_set():
            try:
                _servo_set_us_gpio(gpio, a)
                if _ident_stop.wait(period_ms / 1000.0):
                    break
                _servo_set_us_gpio(gpio, b)
                if _ident_stop.wait(period_ms / 1000.0):
                    break
            except Exception:
                if _ident_stop.wait(0.25):
                    break
        try:
            _servo_set_us_gpio(gpio, SERVO_BOOT_US)
        except Exception:
            pass

    with _ident_lock:
        _ident_stop.clear()
        _ident_port = port
        _ident_thread = threading.Thread(target=_loop, daemon=True)
        _ident_thread.start()

    return {"port": port, "gpio": gpio, "lo_us": lo_us, "hi_us": hi_us, "period_ms": period_ms}

def servo_toolhead_move(toolhead: int, action: str):
    cfg = servo_cfg_load()
    toolhead = int(toolhead)
    action = str(action or "").strip().lower()

    m = cfg.get("toolhead_to_port") or {}
    port = m.get(str(toolhead))
    if port is None:
        raise ValueError("toolhead_not_mapped")
    port = int(port)

    ports_cfg = cfg.get("ports") or {}
    gpio = None
    try:
        gpio = int((ports_cfg.get(str(port)) or {}).get("gpio"))
    except Exception:
        gpio = None
    if gpio is None:
        gpio = int(servo_ports().get(port))

    th = (cfg.get("toolheads") or {}).get(str(toolhead)) or {}

    if action == "open":
        us = int(th.get("closed_us", cfg.get("boot_us", SERVO_BOOT_US)))
    elif action == "close":
        us = int(th.get("open_us", cfg.get("boot_us", SERVO_BOOT_US)))
    elif action == "boot":
        us = int(cfg.get("boot_us", SERVO_BOOT_US))
    else:
        raise ValueError("bad_action")

    try:
        lo = th.get("min_us", None)
        hi = th.get("max_us", None)
        if lo is not None and hi is not None:
            lo = int(lo); hi = int(hi)
            if hi < lo: lo, hi = hi, lo
            if us < lo: us = lo
            if us > hi: us = hi
    except Exception:
        pass

    _servo_init_gpio(gpio)
    _servo_set_us_gpio(gpio, us)
    return {"toolhead": toolhead, "port": port, "gpio": gpio, "us": us, "action": action}


SC_LC_CFG = os.getenv("SC_LC_CFG", "/home/sidecar/sidecar/state/sc_loadcell.json")

_lc_lock = threading.RLock()
_lc_cache_lock = threading.Lock()
_lc_cache = {"t": {}, "raw": {}}

def lc_unit_norm(unit, default=1) -> int:
    try:
        u = int(unit)
    except Exception:
        u = int(default)
    if u < 1 or u > 4:
        raise ValueError("bad_unit")
    return u

def lc_name(unit: int, lane: int) -> str:
    unit = lc_unit_norm(unit)
    lane = int(lane)
    if lane not in (1, 2, 3, 4):
        raise ValueError("bad_lane")
    if unit == 1:
        return f"l{lane}_scale"
    return f"aux{unit}_l{lane}_scale"

def lc_cfg_unit_default():
    return {
        "lanes": {
            "1": {"tare_mode": "none", "tare_raw_g": 0.0, "empty_spool_g": 0.0, "scale_k": 1.0},
            "2": {"tare_mode": "none", "tare_raw_g": 0.0, "empty_spool_g": 0.0, "scale_k": 1.0},
            "3": {"tare_mode": "none", "tare_raw_g": 0.0, "empty_spool_g": 0.0, "scale_k": 1.0},
            "4": {"tare_mode": "none", "tare_raw_g": 0.0, "empty_spool_g": 0.0, "scale_k": 1.0},
        },
        "cal_session": {},
        "updated_at": _now_iso(),
    }

def lc_cfg_default():
    units = {str(u): lc_cfg_unit_default() for u in (1, 2, 3, 4)}
    return {
        "version": 2,
        "units": units,
        "updated_at": _now_iso(),
    }

def lc_cfg_load():
    with _lc_lock:
        try:
            if not os.path.exists(SC_LC_CFG):
                cfg = lc_cfg_default()
                lc_cfg_save(cfg)
                return cfg

            with open(SC_LC_CFG, "r", encoding="utf-8") as f:
                cfg = json.load(f)

            dirty = False
            if not isinstance(cfg, dict):
                cfg = lc_cfg_default()
                dirty = True

            if "units" not in cfg or not isinstance(cfg.get("units"), dict):
                if "lanes" in cfg and isinstance(cfg.get("lanes"), dict):
                    old = cfg
                    cfg = lc_cfg_default()
                    cfg["units"]["1"]["lanes"] = old.get("lanes") or {}
                    cfg["units"]["1"]["cal_session"] = old.get("cal_session") or {}
                    if isinstance(old.get("updated_at"), str):
                        cfg["units"]["1"]["updated_at"] = old["updated_at"]
                        cfg["updated_at"] = old["updated_at"]
                    dirty = True
                else:
                    cfg["units"] = lc_cfg_default()["units"]
                    dirty = True

            if int(cfg.get("version") or 0) < 2:
                cfg["version"] = 2
                dirty = True

            units = cfg.setdefault("units", {})
            dflt_unit = lc_cfg_unit_default()
            dflt_lanes = dflt_unit["lanes"]

            for unit in (1, 2, 3, 4):
                uk = str(unit)
                if uk not in units or not isinstance(units.get(uk), dict):
                    units[uk] = lc_cfg_unit_default()
                    dirty = True
                uc = units[uk]
                if "lanes" not in uc or not isinstance(uc.get("lanes"), dict):
                    uc["lanes"] = {k: dict(v) for k, v in dflt_lanes.items()}
                    dirty = True

                for lane in ("1", "2", "3", "4"):
                    if lane not in uc["lanes"] or not isinstance(uc["lanes"][lane], dict):
                        uc["lanes"][lane] = dict(dflt_lanes[lane])
                        dirty = True
                    for k, v in dflt_lanes[lane].items():
                        if k not in uc["lanes"][lane]:
                            uc["lanes"][lane][k] = v
                            dirty = True

                if "cal_session" not in uc or not isinstance(uc.get("cal_session"), dict):
                    uc["cal_session"] = {}
                    dirty = True

            if dirty:
                try:
                    lc_cfg_save(cfg)
                except Exception:
                    pass
            return cfg
        except Exception:
            cfg = lc_cfg_default()
            try:
                lc_cfg_save(cfg)
            except Exception:
                pass
            return cfg

def lc_cfg_save(cfg):
    with _lc_lock:
        os.makedirs(os.path.dirname(SC_LC_CFG), exist_ok=True)
        cfg = dict(cfg)
        cfg["updated_at"] = _now_iso()
        tmp = SC_LC_CFG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, SC_LC_CFG)

def lc_query_raw(unit: int, timeout: float = 1.5):
    unit = lc_unit_norm(unit)
    now = time.time()
    with _lc_cache_lock:
        t0 = float((_lc_cache.get("t") or {}).get(str(unit), 0.0) or 0.0)
        raw_cached = (_lc_cache.get("raw") or {}).get(str(unit))
        if raw_cached and (now - t0) < 0.25:
            return dict(raw_cached)

    q = "&".join(
        urllib.parse.quote(f"load_cell {lc_name(unit, lane)}", safe="")
        for lane in (1, 2, 3, 4)
    )
    url = f"{BT_HTTP}/printer/objects/query?{q}"
    j = get_json(url, timeout=timeout)
    st = (j.get("result") or {}).get("status") or {}

    raw = {}
    for lane in (1, 2, 3, 4):
        obj = st.get(f"load_cell {lc_name(unit, lane)}") or {}
        v = obj.get("force_g", None)
        raw[str(lane)] = None if v is None else float(v)

    with _lc_cache_lock:
        _lc_cache.setdefault("t", {})[str(unit)] = now
        _lc_cache.setdefault("raw", {})[str(unit)] = raw
    return raw

def lc_lane_state(cfg_lane: dict, raw_g):
    try:
        k = float(cfg_lane.get("scale_k", 1.0) or 1.0)
    except Exception:
        k = 1.0
    try:
        tare_raw = float(cfg_lane.get("tare_raw_g", 0.0) or 0.0)
    except Exception:
        tare_raw = 0.0
    try:
        empty = float(cfg_lane.get("empty_spool_g", 0.0) or 0.0)
    except Exception:
        empty = 0.0

    mode = str(cfg_lane.get("tare_mode") or "none").strip().lower()

    net = None
    if raw_g is not None:
        if mode == "measure_empty":
            net = (raw_g - tare_raw) * k
        elif mode == "manual_empty":
            net = (raw_g - tare_raw) * k - empty
        else:
            net = raw_g * k
        if net < 0:
            net = 0.0

    return {
        "raw_g": raw_g,
        "net_g": net,
        "tare_raw_g": tare_raw,
        "empty_spool_g": empty,
        "scale_k": k,
    }

def lc_state_snapshot(unit: int = 1):
    unit = lc_unit_norm(unit)
    cfg = lc_cfg_load()
    uc = ((cfg.get("units") or {}).get(str(unit)) or {})
    raw = lc_query_raw(unit, timeout=1.5)
    lanes = {}
    for lane in (1, 2, 3, 4):
        cl = (uc.get("lanes") or {}).get(str(lane)) or {}
        lanes[str(lane)] = lc_lane_state(cl, raw.get(str(lane)))
    return lanes

def lc_set_lane(cfg_unit: dict, lane: int, **kwargs):
    lanes = cfg_unit.setdefault("lanes", {})
    d = lanes.setdefault(str(lane), {})
    d.update(kwargs)
    lanes[str(lane)] = d

def lc_pick_loaded_lane(raw_by_lane: dict):
    best_lane = None
    best_abs = 0.0
    for k, v in (raw_by_lane or {}).items():
        if v is None:
            continue
        try:
            a = abs(float(v))
        except Exception:
            continue
        if a > best_abs:
            best_abs = a
            best_lane = int(k)
    if best_lane is None or best_abs < 50.0:
        return None
    return best_lane

def lc_tare(unit: int, lane: int, mode: str, empty_spool_g=None):
    unit = lc_unit_norm(unit)
    lane = int(lane)
    if lane not in (1, 2, 3, 4):
        raise ValueError("bad_lane")
    mode = str(mode or "").strip().lower()

    cfg = lc_cfg_load()
    uc = ((cfg.get("units") or {}).get(str(unit)) or {})
    raw = lc_query_raw(unit, timeout=2.0)
    v = raw.get(str(lane))
    if v is None:
        raise ValueError("no_raw")

    if mode == "measure_empty":
        lc_set_lane(uc, lane, tare_mode="measure_empty", tare_raw_g=float(v), empty_spool_g=float(v))
    elif mode == "manual_empty":
        if empty_spool_g is None:
            raise ValueError("missing_empty_spool_g")
        eg = float(empty_spool_g)
        if eg <= 0:
            raise ValueError("bad_empty_spool_g")
        lc_set_lane(uc, lane, tare_mode="manual_empty", tare_raw_g=float(v), empty_spool_g=float(eg))
    else:
        raise ValueError("bad_mode")

    cfg.setdefault("units", {})[str(unit)] = uc
    lc_cfg_save(cfg)
    return lc_state_snapshot(unit)

def lc_clear_tare(unit: int, lane: int):
    unit = lc_unit_norm(unit)
    lane = int(lane)
    if lane not in (1, 2, 3, 4):
        raise ValueError("bad_lane")
    cfg = lc_cfg_load()
    uc = ((cfg.get("units") or {}).get(str(unit)) or {})
    lc_set_lane(uc, lane, tare_mode="none", tare_raw_g=0.0, empty_spool_g=0.0)
    cfg.setdefault("units", {})[str(unit)] = uc
    lc_cfg_save(cfg)
    return lc_state_snapshot(unit)

def lc_calibrate(unit: int, step: str, known_g):
    unit = lc_unit_norm(unit)
    step = str(step or "").strip().lower()
    kg = float(known_g)
    if kg <= 0:
        raise ValueError("bad_known_g")

    cfg = lc_cfg_load()
    uc = ((cfg.get("units") or {}).get(str(unit)) or {})
    raw = lc_query_raw(unit, timeout=2.5)
    lane = lc_pick_loaded_lane(raw)
    if lane is None:
        raise ValueError("no_loaded_lane")

    sess = uc.get("cal_session") or {}

    if step == "full":
        uc["cal_session"] = {"lane": lane, "full": {"raw_g": raw[str(lane)], "known_g": kg}}
        cfg.setdefault("units", {})[str(unit)] = uc
        lc_cfg_save(cfg)
        return lane, lc_state_snapshot(unit)

    if step == "empty":
        if not sess or "full" not in sess:
            raise ValueError("need_full_first")
        if int(sess.get("lane", lane)) != lane:
            raise ValueError("lane_changed")

        full = sess["full"]
        fr = float(full["raw_g"])
        fk = float(full["known_g"])
        er = float(raw[str(lane)])
        ek = kg

        denom = (fr - er)
        if abs(denom) < 1e-6:
            raise ValueError("denom_zero")

        k = (fk - ek) / denom
        if not (0.05 < k < 10.0):
            raise ValueError("bad_scale_k")

        lc_set_lane(uc, lane, scale_k=float(k))
        lc_set_lane(uc, lane, empty_spool_g=float(ek))

        uc["cal_session"] = {}
        cfg.setdefault("units", {})[str(unit)] = uc
        lc_cfg_save(cfg)
        return lane, lc_state_snapshot(unit)

    raise ValueError("bad_step")

def lc_cal_reset(unit: int = 1):
    unit = lc_unit_norm(unit)
    cfg = lc_cfg_load()
    uc = ((cfg.get("units") or {}).get(str(unit)) or {})
    uc["cal_session"] = {}
    cfg.setdefault("units", {})[str(unit)] = uc
    lc_cfg_save(cfg)
    return lc_state_snapshot(unit)



_sc_cfg_lock = threading.Lock()

def sc_cfg_load():
    with _sc_cfg_lock:
        with open(SC_HEADS_CFG, "r", encoding="utf-8") as f:
            return json.load(f)

def sc_cfg_save(cfg):
    with _sc_cfg_lock:
        tmp = SC_HEADS_CFG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, SC_HEADS_CFG)

def sc_cfg_head(cfg, head: int):
    return (cfg.get("heads") or {}).get(str(head))

def sc_cfg_validate(head: int, lane: int, for_unload: bool = False):
    cfg = sc_cfg_load()
    h = sc_cfg_head(cfg, head)
    if not h or not h.get("managed", False):
        return False, "head_not_managed", cfg
    allowed = h.get("allowed_lanes") or []
    if lane not in allowed:
        return False, "lane_not_allowed", cfg
    if for_unload and h.get("active_lane") is not None and int(h.get("active_lane")) != lane:
        return False, "lane_not_active", cfg
    return True, "", cfg

def sc_cfg_set_active(head: int, lane: int):
    cfg = sc_cfg_load()
    h = sc_cfg_head(cfg, head)
    if not h:
        return
    h["active_lane"] = int(lane)
    cfg["heads"][str(head)] = h
    sc_cfg_save(cfg)

def sc_cfg_clear_active(head: int, lane: int):
    cfg = sc_cfg_load()
    h = sc_cfg_head(cfg, head)
    if not h:
        return
    if h.get("active_lane") is None or int(h.get("active_lane")) == int(lane):
        h["active_lane"] = None
        cfg["heads"][str(head)] = h
        sc_cfg_save(cfg)

def _api_json(handler, max_bytes=65536):
    ln = int(handler.headers.get("Content-Length") or "0")
    if ln > max_bytes:
        raise ValueError("body too large")
    raw = handler.rfile.read(ln) if ln else b"{}"
    return json.loads(raw.decode("utf-8", errors="replace") or "{}")

def _api_send(handler, code: int, obj: dict):
    body = json.dumps(obj).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)

class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def u1_temp_state(head: int):
    extr = "extruder" if head == 0 else f"extruder{head}"
    j = get_json(f"{U1_HTTP}/printer/objects/query?print_stats&{extr}")
    st = j["result"]["status"]
    ps = st.get("print_stats") or {}
    ex = st.get(extr) or {}
    return (ps.get("state") or ""), float(ex.get("temperature", 0.0) or 0.0), float(ex.get("target", 0.0) or 0.0)

def u1_set_temp_nonblock(head: int, temp: float):
    t = int(temp)
    u1_gcode(f"M104 T{head} A0 S{t}")

def _swap_temp_assert(head: int, lane: int, temp: float, tag: str):
    try:
        state, cur, tgt = u1_temp_state(head)
    except Exception:
        state, cur, tgt = '?', -1.0, -1.0
    t = int(temp)
    try:
        u1_gcode(f"M104 T{int(head)} A0 S{t}")
    except Exception as e:
        print('gate: WARN swap_temp_assert_failed', {'head': head, 'lane': lane, 'tool': int(head), 'tag': tag, 'set': t, 'err': str(e)})
        return
    try:
        print(f"gate: SWAP_TEMP_ASSERT_PHYSICAL t={time.time():.3f} tag={tag} head={head} lane={lane} tool={int(head)} set={t} state={state} cur={cur:.1f} tgt={tgt:.1f}")
    except Exception:
        pass


def u1_ensure_hot(head: int, temp: float, tol: float = 5.0, timeout_s: float = 300.0, poll_s: float = 1.0):
    t0 = time.time()
    did_set = False
    set_at = 0.0

    while True:
        state, cur, tgt = u1_temp_state(head)

        if state in ("printing", "paused"):
            return False, "busy_printing"

        if (not did_set) and (tgt < (temp - 0.5)):
            u1_set_temp_nonblock(head, temp)
            did_set = True
            set_at = time.time()
            if cur >= (temp - tol):
                return True, ""

        if cur >= (temp - tol):
            return True, ""

        if did_set and (time.time() - set_at) > max(3.0, float(poll_s) * 2.0):
            if tgt < (temp - 0.5):
                return False, "heat_target_changed"

        if time.time() - t0 > timeout_s:
            return False, "heat_timeout"

        time.sleep(poll_s)


class _ApiHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/v1/heads":
            _api_send(self, 200, {"ok": True, "cfg": sc_cfg_load()})
            return
        if self.path.split("?", 1)[0] == "/api/v1/state":
            try:
                unit = 1
                try:
                    q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                    unit = int((q.get("unit") or ["1"])[0] or 1)
                except Exception:
                    unit = 1
                if unit < 1 or unit > 4:
                    unit = 1
                snap = api_state_snapshot(unit)
                _api_send(self, 200, {"ok": True, "unit": unit, **snap})
            except Exception as e:
                _api_send(self, 500, {"ok": False, "error": "state_failed", "detail": str(e)})
            return
        p = self.path.split("?", 1)[0]
        if p == "/api/v1/servo/mapping":
            cfg = servo_cfg_load()
            mapping = {"toolhead_to_port": (cfg.get("toolhead_to_port") or {})}
            _api_send(self, 200, {"ok": True, "mapping": mapping, "cfg": cfg})
            return
        if p == "/api/v1/servo/adjust":
            try:
                qs = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "", keep_blank_values=True)
                toolhead = int((qs.get("toolhead", ["0"])[0]) or "0")
                if toolhead not in (1, 2, 3, 4):
                    raise ValueError("bad_toolhead")
                cfg = servo_cfg_load()
                tool = dict(SERVO_TOOLHEAD_DEFAULTS.get(str(toolhead)) or {})
                tool.update((cfg.get("toolheads") or {}).get(str(toolhead)) or {})
                port = int((cfg.get("toolhead_to_port") or {}).get(str(toolhead), 0) or 0)
                _api_send(self, 200, {
                    "ok": True,
                    "toolhead": toolhead,
                    "port": port,
                    "settings": {
                        "closed_us": int(tool.get("closed_us")),
                        "open_us": int(tool.get("open_us")),
                        "min_us": int(tool.get("min_us", min(int(tool.get("closed_us")), int(tool.get("open_us"))))),
                        "max_us": int(tool.get("max_us", max(int(tool.get("closed_us")), int(tool.get("open_us"))))),
                    },
                })
            except Exception as e:
                _api_send(self, 409, {"ok": False, "error": "servo_adjust_get_failed", "detail": str(e)})
            return
        if p == "/api/v1/servo/ports":
            _api_send(self, 200, {"ok": True, "ports": servo_ports()})
            return
        if p == "/api/v1/loadcell/state":
            try:
                qs = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "", keep_blank_values=True)
                unit = int((qs.get("unit", ["1"])[0]) or "1")
                lanes = lc_state_snapshot(unit)
                _api_send(self, 200, {"ok": True, "unit": unit, "lanes": lanes})
            except Exception as e:
                _api_send(self, 500, {"ok": False, "error": "loadcell_state_failed", "detail": str(e)})
            return

        if p == "/api/v1/lane-meta":
            try:
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                toolhead = q.get("toolhead", [None])[0]
                lane = q.get("lane", [None])[0]

                if toolhead is None:
                    unit = q.get("unit", [None])[0]
                    if unit is not None:
                        toolhead = unit

                if toolhead is None:
                    head = q.get("head", [None])[0]
                    if head is not None:
                        toolhead = int(head) + 1

                if toolhead is None:
                    cfg = lane_meta_get()
                    _api_send(self, 200, {"ok": True, "cfg": cfg})
                    return

                toolhead = int(toolhead)
                if lane is None:
                    cfg = lane_meta_get(toolhead=toolhead)
                    _api_send(self, 200, {"ok": True, "toolhead": toolhead, "cfg": cfg})
                    return

                lane = int(lane)
                meta = lane_meta_get(toolhead=toolhead, lane=lane)
                _api_send(self, 200, {"ok": True, "toolhead": toolhead, "lane": lane, "meta": meta})
            except Exception as e:
                _api_send(self, 409, {"ok": False, "error": "lane_meta_get_failed", "detail": str(e)})
            return

        _api_send(self, 404, {"ok": False, "error": "not_found"})

    def do_POST(self):
        try:
            p = self.path.split("?", 1)[0]
            if p == "/api/v1/servo/identify/start":
                body = _api_json(self)
                port = int(body.get("port"))
                lo_us = int(body.get("lo_us", 1200))
                hi_us = int(body.get("hi_us", 1800))
                period_ms = int(body.get("period_ms", 500))
                try:
                    st = servo_identify_start(port, lo_us=lo_us, hi_us=hi_us, period_ms=period_ms)
                    _api_send(self, 200, {"ok": True, **st})
                except Exception as e:
                    _api_send(self, 409, {"ok": False, "error": "identify_start_failed", "detail": str(e)})
                return

            if p == "/api/v1/servo/identify/stop":
                try:
                    servo_identify_stop()
                except Exception:
                    pass
                _api_send(self, 200, {"ok": True})
                return

            if p == "/api/v1/servo/mapping":
                body = _api_json(self)
                try:
                    toolhead = int(body.get("toolhead"))
                    port = int(body.get("port"))
                    try:
                        servo_identify_stop()
                    except Exception:
                        pass
                    cfg = servo_cfg_set_mapping(toolhead, port)
                    _api_send(self, 200, {"ok": True, "cfg": cfg})
                except Exception as e:
                    _api_send(self, 409, {"ok": False, "error": "mapping_failed", "detail": str(e)})
                return

            if p == "/api/v1/servo/adjust/preview":
                body = _api_json(self)
                try:
                    toolhead = int(body.get("toolhead"))
                    action = str(body.get("action") or "").strip().lower()
                    us = int(body.get("us"))
                    try:
                        servo_identify_stop()
                    except Exception:
                        pass
                    cfg = servo_cfg_load()
                    port = int((cfg.get("toolhead_to_port") or {}).get(str(toolhead), 0) or 0)
                    if port not in (1, 2, 3, 4):
                        _api_send(self, 409, {"ok": False, "error": "toolhead_unmapped", "toolhead": toolhead})
                        return
                    st = servo_toolhead_move_preview(toolhead, action, us)
                    _api_send(self, 200, {"ok": True, "toolhead": toolhead, "port": port, "action": action, "us": int(us), **st})
                except Exception as e:
                    _api_send(self, 409, {"ok": False, "error": "servo_adjust_preview_failed", "detail": str(e)})
                return

            if p == "/api/v1/servo/adjust/save":
                body = _api_json(self)
                try:
                    toolhead = int(body.get("toolhead"))
                    closed_us = body.get("closed_us", None)
                    open_us = body.get("open_us", None)
                    cfg, cur = servo_cfg_set_toolhead_settings(toolhead, closed_us=closed_us, open_us=open_us)
                    port = int((cfg.get("toolhead_to_port") or {}).get(str(toolhead), 0) or 0)
                    _api_send(self, 200, {"ok": True, "toolhead": toolhead, "port": port, "settings": cur, "cfg": cfg})
                except Exception as e:
                    _api_send(self, 409, {"ok": False, "error": "servo_adjust_save_failed", "detail": str(e)})
                return

            if p == "/api/v1/servo/toolhead/move":
                body = _api_json(self)
                try:
                    toolhead = int(body.get("toolhead"))
                    action = str(body.get("action") or "").strip().lower()
                    try:
                        servo_identify_stop()
                    except Exception:
                        pass
                    st = servo_toolhead_move(toolhead, action)
                    _api_send(self, 200, {"ok": True, **st})
                except Exception as e:
                    _api_send(self, 409, {"ok": False, "error": "toolhead_move_failed", "detail": str(e)})
                return

            if p == "/api/v1/servo/mapping/reset":
                try:
                    try:
                        servo_identify_stop()
                    except Exception:
                        pass
                    cfg = servo_cfg_reset()
                    _api_send(self, 200, {"ok": True, "cfg": cfg})
                except Exception as e:
                    _api_send(self, 500, {"ok": False, "error": "reset_failed", "detail": str(e)})
                return

            if p == "/api/v1/loadcell/tare":
                body = _api_json(self)
                try:
                    unit = int(body.get("unit", 1))
                    lane = int(body.get("lane", 0))
                    mode = str(body.get("mode") or "")
                    empty = body.get("empty_spool_g", None)
                    lanes = lc_tare(unit, lane, mode, empty_spool_g=empty)
                    _api_send(self, 200, {"ok": True, "unit": unit, "lane": lane, "lanes": lanes})
                except Exception as e:
                    _api_send(self, 409, {"ok": False, "error": "tare_failed", "detail": str(e)})
                return

            if p == "/api/v1/loadcell/tare/reset":
                body = _api_json(self)
                try:
                    unit = int(body.get("unit", 1))
                    lane = int(body.get("lane", 0))
                    lanes = lc_clear_tare(unit, lane)
                    _api_send(self, 200, {"ok": True, "unit": unit, "lane": lane, "lanes": lanes})
                except Exception as e:
                    _api_send(self, 409, {"ok": False, "error": "tare_reset_failed", "detail": str(e)})
                return

            if p == "/api/v1/loadcell/calibrate":
                body = _api_json(self)
                try:
                    unit = int(body.get("unit", 1))
                    step = str(body.get("step") or "")
                    known_g = float(body.get("known_g", 0))
                    lane, lanes = lc_calibrate(unit, step, known_g)
                    _api_send(self, 200, {"ok": True, "unit": unit, "lane": lane, "lanes": lanes})
                except Exception as e:
                    _api_send(self, 409, {"ok": False, "error": "calibrate_failed", "detail": str(e)})
                return

            if p == "/api/v1/loadcell/calibrate/reset":
                try:
                    body = _api_json(self)
                    unit = int(body.get("unit", 1))
                    lanes = lc_cal_reset(unit)
                    _api_send(self, 200, {"ok": True, "unit": unit, "lanes": lanes})
                except Exception as e:
                    _api_send(self, 500, {"ok": False, "error": "calibrate_reset_failed", "detail": str(e)})
                return


            if p == "/api/v1/lane-meta":
                body = _api_json(self)
                try:
                    toolhead = body.get("toolhead", None)
                    lane = body.get("lane", None)

                    if toolhead is None:
                        unit = body.get("unit", None)
                        if unit is not None:
                            toolhead = unit

                    if toolhead is None:
                        head = body.get("head", None)
                        if head is not None:
                            toolhead = int(head) + 1

                    if toolhead is None:
                        _api_send(self, 400, {"ok": False, "error": "missing_toolhead"})
                        return
                    if lane is None:
                        _api_send(self, 400, {"ok": False, "error": "missing_lane"})
                        return

                    toolhead = int(toolhead)
                    lane = int(lane)
                    cfg, meta = lane_meta_set(toolhead, lane, body)
                    _api_send(self, 200, {"ok": True, "toolhead": toolhead, "lane": lane, "meta": meta, "cfg": cfg})
                except Exception as e:
                    _api_send(self, 409, {"ok": False, "error": "lane_meta_set_failed", "detail": str(e)})
                return

            if self.path == "/api/v1/heads":
                cfg = sc_cfg_load()
                body = _api_json(self)
                if "heads" in body:
                    cfg["heads"] = body["heads"]
                if "defaults" in body:
                    cfg["defaults"] = body["defaults"]
                sc_cfg_save(cfg)
                _api_send(self, 200, {"ok": True, "cfg": cfg})
                return

            if self.path in ("/api/v1/load", "/api/v1/unload", "/api/v1/remove"):
                body = _api_json(self)
                head = int(body.get("head"))
                lane = body.get("lane")
                if lane is None:
                    h = sc_cfg_head(sc_cfg_load(), head)
                    lane = None if not h else h.get("active_lane")
                if lane is None:
                    _api_send(self, 400, {"ok": False, "error": "missing_lane"})
                    return
                lane = int(lane)

                with _busy_lock:
                    if _busy:
                        _api_send(self, 409, {"ok": False, "error": "gate_busy"})
                        return


                if self.path == "/api/v1/load":
                    ok, why, cfg = sc_cfg_validate(head, lane, for_unload=False)
                    if not ok:
                        _api_send(self, 409, {"ok": False, "error": why, "head": head, "lane": lane})
                        return
                    d = cfg.get("defaults") or {}
                    try:
                        if not bt_hub_clear_precondition(head):
                            _api_send(self, 409, {"ok": False, "error": "hub_busy", "head": head, "lane": lane})
                            return
                    except Exception as e:
                        _api_send(self, 500, {"ok": False, "error": "hub_check_failed", "detail": str(e)})
                        return

                    if int(body.get('dry_run', 0) or 0):
                        _api_send(self, 200, {'ok': True, 'dry_run': True, 'head': head, 'lane': lane})
                        return

                    temp = float(body.get('temp', d.get('temp_load', 220)))
                    okh, whyh = u1_ensure_hot(head, temp,
                                             tol=float(d.get('temp_tol', 5)),
                                             timeout_s=float(d.get('temp_timeout_s', 300)),
                                             poll_s=float(d.get('temp_poll_s', 1.0)))
                    if not okh:
                        _api_send(self, 409, {'ok': False, 'error': whyh, 'head': head})
                        return
                    if int(body.get('heat_only', 0) or 0):
                        _api_send(self, 200, {'ok': True, 'heat_only': True, 'head': head, 'lane': lane})
                        return

                    go = float(body.get("go_dist", d.get("go_dist", 80)))
                    v  = float(body.get("v", d.get("v", 2.0)))
                    a  = float(body.get("a", d.get("a", 0.0)))
                    u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=LOAD head={head} lane={lane} go_dist={go:g} v={v:g} a={a:g} src=ui"')
                    _api_send(self, 200, {"ok": True, "sent": "EV=LOAD", "head": head, "lane": lane})
                    return

                if self.path == "/api/v1/unload":
                    ok, why, cfg = sc_cfg_validate(head, lane, for_unload=True)
                    if not ok:
                        _api_send(self, 409, {"ok": False, "error": why, "head": head, "lane": lane})
                        return
                    d = cfg.get('defaults') or {}
                    h = sc_cfg_head(cfg, head)
                    active = None if not h else h.get("active_lane")
                    try:
                        active_i = int(active) if active is not None else None
                    except Exception:
                        active_i = None
                    if active_i != lane:
                        _api_send(self, 409, {"ok": False, "error": "nothing_to_unload", "head": head, "lane": lane, "active_lane": active})
                        return
                    try:
                        unit = head + 1
                        v = bt_vars()
                        owner = int(v.get(bt_key("hub_owner", unit), 0) or 0)
                    except Exception:
                        owner = 0
                    if owner != lane:
                        _api_send(self, 409, {"ok": False, "error": "unload_owner_mismatch", "head": head, "lane": lane, "hub_owner": owner})
                        return

                    temp = float(body.get('temp', d.get('temp_unload', 220)))
                    okh, whyh = u1_ensure_hot(head, temp,
                                             tol=float(d.get('temp_tol', 5)),
                                             timeout_s=float(d.get('temp_timeout_s', 300)),
                                             poll_s=float(d.get('temp_poll_s', 1.0)))
                    if not okh:
                        _api_send(self, 409, {'ok': False, 'error': whyh, 'head': head})
                        return
                    u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=UNLOAD head={head} lane={lane} src=ui"')
                    _api_send(self, 200, {"ok": True, "sent": "EV=UNLOAD", "head": head, "lane": lane})
                    return

                if self.path == "/api/v1/remove":
                    macro = body.get("macro") or f"REMOVEL{lane}"
                    bt_gcode(macro)
                    _api_send(self, 200, {"ok": True, "sent": macro, "lane": lane})
                    return

            _api_send(self, 404, {"ok": False, "error": "not_found"})
        except Exception as e:
            _api_send(self, 500, {"ok": False, "error": "exception", "detail": str(e)})

def start_api_server():
    try:
        srv = _ThreadedHTTPServer((SC_API_HOST, SC_API_PORT), _ApiHandler)
        print(f"gate: api listening on http://{SC_API_HOST}:{SC_API_PORT} (cfg={SC_HEADS_CFG})")
        srv.serve_forever()
    except Exception as e:
        print("gate: api server failed", e)


POLL_SEC        = float(os.getenv("POLL_SEC", "0.2"))
STALL_TIMEOUT   = float(os.getenv("STALL_TIMEOUT", "60"))
BT_TIMEOUT      = float(os.getenv("BT_TIMEOUT", "5"))
COMP_OPEN_TO    = float(os.getenv("COMP_OPEN_TIMEOUT", "0.1"))

GO_V = float(os.getenv("GO_V", "2.0"))
GO_A = float(os.getenv("GO_A", "0.0"))

AUTO_LTGL = int(os.getenv("AUTO_LTGL", "0"))

def get_json(url: str, timeout: float = 6.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))

def post_json(url: str, payload: dict, timeout: float = 6.0) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))

def u1_gcode(script: str, timeout: float = 6.0) -> None:
    post_json(f"{U1_HTTP}/printer/gcode/script", {"script": script}, timeout=timeout)

def bt_gcode(script: str) -> None:
    post_json(f"{BT_HTTP}/printer/gcode/script", {"script": script}, timeout=BT_TIMEOUT)

def bt_vars() -> dict:
    j = get_json(f"{BT_HTTP}/printer/objects/query?save_variables", timeout=BT_TIMEOUT)
    st = j["result"]["status"]
    return (st.get("save_variables") or {}).get("variables") or {}

def bt_key(base: str, unit: int) -> str:
    u = int(unit)
    return base if u <= 1 else f"{base}{u}"

def bt_at_gears(unit: int = 1) -> int:
    v = bt_vars()
    return int(v.get(bt_key("at_gears", unit), 0) or 0)

def bt_set_at_gears(unit: int, val: int):
    bt_gcode(f"SAVE_VARIABLE VARIABLE={bt_key('at_gears', unit)} VALUE={int(val)}")

def bt_ltgl_cmd(unit: int, lane: int) -> str:
    u = int(unit)
    l = int(lane)
    return f"LTGL{l}" if u <= 1 else f"LTGL{l}{u}"

def bt_endstops_and_vars():
    j = get_json(f"{BT_HTTP}/printer/objects/query?query_endstops&save_variables", timeout=BT_TIMEOUT)
    st = (j.get("result") or {}).get("status") or {}
    last = (st.get("query_endstops") or {}).get("last_query") or {}
    vars_ = (st.get("save_variables") or {}).get("variables") or {}

    if ("HSW" not in last) or ("RSW" not in last):
        try:
            bt_gcode("QUERY_ENDSTOPS")
            time.sleep(0.05)
            j = get_json(f"{BT_HTTP}/printer/objects/query?query_endstops&save_variables", timeout=BT_TIMEOUT)
            st = (j.get("result") or {}).get("status") or {}
            last = (st.get("query_endstops") or {}).get("last_query") or {}
            vars_ = (st.get("save_variables") or {}).get("variables") or {}
        except Exception:
            pass

    return last, vars_

def api_state_snapshot(unit: int = 1):
    try:
        unit = int(unit or 1)
    except Exception:
        unit = 1
    if unit < 1 or unit > 4:
        unit = 1

    j = get_json(f"{BT_HTTP}/printer/objects/query?query_endstops&save_variables", timeout=BT_TIMEOUT)
    st = (j.get("result") or {}).get("status") or {}
    last = (st.get("query_endstops") or {}).get("last_query") or {}
    vars_ = (st.get("save_variables") or {}).get("variables") or {}

    def _k(base: str) -> str:
        return f"{base}{unit}" if unit != 1 else base

    if (_k("HSW") not in last) or (_k("RSW") not in last):
        now = time.time()
        last_prime = globals().get("_api_state_last_prime", 0.0)
        if now - last_prime > 2.0:
            globals()["_api_state_last_prime"] = now
            try:
                bt_gcode("QUERY_ENDSTOPS")
            except Exception:
                pass
            time.sleep(0.05)
            j = get_json(f"{BT_HTTP}/printer/objects/query?query_endstops&save_variables", timeout=BT_TIMEOUT)
            st = (j.get("result") or {}).get("status") or {}
            last = (st.get("query_endstops") or {}).get("last_query") or {}
            vars_ = (st.get("save_variables") or {}).get("variables") or {}

    def _to01(v) -> int:
        if v is None:
            return 0
        if isinstance(v, bool):
            return 1 if v else 0
        if isinstance(v, (int, float)):
            return 1 if v else 0
        s = str(v).strip().upper()
        return 1 if s in ("TRIGGERED", "1", "TRUE", "CLOSED") else 0

    okey = "hub_owner" if unit == 1 else f"hub_owner{unit}"
    owner = int(vars_.get(okey, 0) or 0)
    agkey = "at_gears" if unit == 1 else f"at_gears{unit}"
    at_gears = int(vars_.get(agkey, 0) or 0)

    need = {}
    for lane in (1, 2, 3, 4):
        vk = f"need_lth{lane}" if unit == 1 else f"need_lth{lane}{unit}"
        need[f"need_lth{lane}"] = int(vars_.get(vk, 0) or 0)

    keys = ("HSW", "RSW", "L2RSW", "L3RSW", "L4RSW", "BFCOMPSW")
    endstops = {k: _to01(last.get(_k(k), 0)) for k in keys}

    gsw = {}
    try:
        if unit == 1:
            names = [(1, "l1_gsw"), (2, "l2_gsw"), (3, "l3_gsw"), (4, "l4_gsw")]
        else:
            names = [(1, f"aux{unit}_l1_gsw"), (2, f"aux{unit}_l2_gsw"), (3, f"aux{unit}_l3_gsw"), (4, f"aux{unit}_l4_gsw")]
        qs = "&".join(urllib.parse.quote(f"filament_switch_sensor {n}", safe="") for _, n in names)
        j2 = get_json(f"{BT_HTTP}/printer/objects/query?{qs}", timeout=BT_TIMEOUT)
        st2 = (j2.get("result") or {}).get("status") or {}
        for lane, name in names:
            obj = st2.get(f"filament_switch_sensor {name}") or {}
            gsw[str(lane)] = _to01(obj.get("filament_detected", 0))
    except Exception:
        gsw = {}

    return {"hub_owner": owner, "at_gears": at_gears, "need_lth": need, "endstops": endstops, "gsw": gsw}
def bt_hub_clear_precondition(head: int) -> bool:
    try:
        bt_gcode("QUERY_ENDSTOPS")
    except Exception:
        pass

    last, vars_ = bt_endstops_and_vars()
    suf = "" if int(head) == 0 else str(int(head) + 1)
    hsw = int(last.get(f"HSW{suf}", 1) or 0)
    ag  = int(vars_.get(f"at_gears{suf}", 0) or 0)
    return (hsw == 0) and (ag == 0)

def bt_comp_state(unit: int = 1) -> int:
    try:
        bt_gcode("QUERY_ENDSTOPS")
    except Exception:
        pass

    u = int(unit or 1)
    snap = api_state_snapshot(u)
    es = (snap.get("endstops") or {})
    return int(es.get("BFCOMPSW", 0) or 0)

def bt_tension_state(unit: int = 1) -> int:
    u = int(unit or 1)
    name = "bftenssw" if u == 1 else f"aux{u}_bftenssw"
    j = get_json(f"{BT_HTTP}/printer/objects/query?filament_switch_sensor%20{name}", timeout=BT_TIMEOUT)
    st = j["result"]["status"]
    fs = st.get(f"filament_switch_sensor {name}") or {}
    return 1 if int(fs.get("filament_detected", 0) or 0) else 0

def bt_lane_retract_burst(lane: int, mm: float, speed: float, accel: float, unit: int = 1):
    sign = float(os.getenv("DRAIN_SIGN", "-1"))
    d = sign * abs(mm)

    u = int(unit or 1)
    stepper = f"bt_lane{lane}" if u == 1 else f"aux{u}_bt_lane{lane}"

    bt_gcode(
        f"MANUAL_STEPPER STEPPER={stepper} ENABLE=1\n"
        f"MANUAL_STEPPER STEPPER={stepper} SET_POSITION=0\n"
        f"MANUAL_STEPPER STEPPER={stepper} MOVE={d:g} SPEED={speed:g} ACCEL={accel:g}"
    )

def u1_active_extruder_and_state():
    j = get_json(f"{U1_HTTP}/printer/objects/query?toolhead&print_stats")
    st = j["result"]["status"]
    th = st.get("toolhead") or {}
    ps = st.get("print_stats") or {}
    return (th.get("extruder") or ""), (ps.get("state") or "")

def parse_ev(line: str):
    i = line.find("EV=")
    if i < 0:
        return None
    payload = line[i:].strip()
    toks = payload.split()
    d = {}
    for t in toks:
        if "=" in t:
            k, v = t.split("=", 1)
            d[k.strip()] = v.strip()
    return d or None

def local_ip_for(dst_ip: str, dst_port: int) -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((dst_ip, dst_port))
        return s.getsockname()[0]
    finally:
        s.close()

CLIENT_URL = f"http://{local_ip_for('10.42.0.10', 7125)}"

_busy_lock = threading.Lock()
_busy = False


_pending_lock = threading.Lock()
_pending = []

def _enqueue_ev(ev: dict) -> None:
    with _pending_lock:
        _pending.append(ev)

def _pop_ev():
    with _pending_lock:
        return _pending.pop(0) if _pending else None

def _kick_next():
    global _busy
    with _busy_lock:
        if _busy:
            return
    ev = _pop_ev()
    if not ev:
        return
    with _busy_lock:
        _busy = True
    if ev.get("EV") == "LOAD":
        threading.Thread(target=_handle_load_safe, args=(ev,), daemon=True).start()
    elif ev.get("EV") == "UNLOAD":
        threading.Thread(target=_handle_unload_safe, args=(ev,), daemon=True).start()
    else:
        with _busy_lock:
            _busy = False

def _handle_load_safe(ev: dict):
    global _busy
    try:
        handle_load(ev)
    except Exception as e:
        print("gate: EXC handle_load", str(e))
        try:
            u1_gcode(f'ReSPOND PREFIX="SC" MSG="EV=FAULT reason=gate_exc_load err={str(e).replace(" ","_")[:80]} src=sidecar"')
        except Exception:
            pass
    finally:
        with _busy_lock:
            _busy = False
        _kick_next()


def _bfu_inhibit_var(head: int) -> str:
    h = int(head)
    if h == 0:
        return "bfu_inhibit"
    return f"bfu_inhibit{h+1}"


def _set_bfu_inhibit(head: int, value: int) -> None:
    var = _bfu_inhibit_var(head)
    bt_gcode(f'SAVE_VARIABLE VARIABLE={var} VALUE={int(value)}')


def _bfu_start_for_head(head: int) -> None:
    unit = int(head) + 1
    bt_gcode(f"BFU_START{unit}")


def _bfu_stop_for_head(head: int) -> None:
    unit = int(head) + 1
    bt_gcode(f"BFU_STOP{unit}")

def _close_puck_safe(head: int) -> None:
    try:
        if int(os.getenv('PUCK_ENABLE', '1') or 0):
            servo_toolhead_move(int(head) + 1, 'close')
    except Exception as e:
        print('gate: WARN puck_close_failed', {'head': head, 'err': str(e)})

def _park_failed_unload_temp(head: int, lane: int) -> None:
    try:
        h = int(head)
        l = int(lane)
        if h < 0 or h > 3 or l < 1 or l > 4:
            return
        u1_gcode(f"M104 T{h} A0 S{PARK_TEMP_PRINT_C}")
    except Exception as e:
        print('gate: WARN unload_park_temp_failed', {'head': head, 'lane': lane, 'err': str(e)})

def u1_bg_status_retry(extr: str, attempts: int = 4, timeout: float = 2.0, delay: float = 0.75):
    tries = max(1, int(attempts))
    for attempt in range(1, tries + 1):
        st = u1_bg_status(extr, timeout=timeout)
        if st is not None:
            return st
        if attempt < tries:
            try:
                print('gate: WARN SC_BG_BUSY preflight retry', {'extr': extr, 'attempt': attempt, 'attempts': tries})
            except Exception:
                pass
            time.sleep(delay)
    return None

def _handle_unload_safe(ev: dict):
    global _busy
    unload_ok = False
    try:
        handle_unload(ev)
        unload_ok = bool(ev.get('_unload_success'))
    except Exception as e:
        print("gate: EXC handle_unload", str(e))
        try:
            u1_gcode(f'ReSPOND PREFIX="SC" MSG="EV=FAULT reason=gate_exc_unload err={str(e).replace(" ","_")[:80]} src=sidecar"')
        except Exception:
            pass
    finally:
        if ev.get('_unload_inhibit_set') and not ev.get('_unload_success'):
            try:
                h = int(ev.get('head','-1'))
                _set_bfu_inhibit(h, 0)
            except Exception:
                pass
            try:
                _close_puck_safe(int(ev.get('head','-1')))
            except Exception:
                pass
        with _busy_lock:
            _busy = False

        if unload_ok:
            _kick_next()
            return

        dropped = []
        if ev.get('src') != 'ui':
            try:
                with _pending_lock:
                    dropped = list(_pending)
                    _pending.clear()
            except Exception:
                dropped = []
            try:
                h = ev.get("head", "?")
                l = ev.get("lane", "?")
                u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=QUEUE_ABORT reason=unload_failed dropped={len(dropped)} head={h} lane={l} src=sidecar"')
            except Exception:
                pass
            try:
                _active_extr, st = u1_active_extruder_and_state()
                if st in ("printing", "paused"):
                    u1_gcode("PAUSE")
            except Exception:
                pass

_bg_lock = threading.Lock()
_bg_cond = threading.Condition(_bg_lock)
_bg_last = None
_bg_query_lock = threading.Lock()
_bg_capable = None

def extruder_name_for_head(head: int) -> str:
    return "extruder" if head == 0 else f"extruder{head}"
def u1_bg_status(extr: str, timeout: float = 2.0):
    global _bg_last, _bg_capable
    if _bg_capable is False:
        return None
    with _bg_query_lock:
        with _bg_cond:
            _bg_last = None
        try:
            u1_gcode(f"SC_BG_BUSY EXTRUDER={extr}")
        except Exception as e:
            try:
                print('gate: WARN SC_BG_BUSY poll failed', {'extr': extr, 'err': str(e)})
            except Exception:
                pass
            return None
        t_end = time.time() + timeout
        with _bg_cond:
            while _bg_last is None and time.time() < t_end:
                _bg_cond.wait(timeout=0.5)
            return _bg_last

def u1_wait_bg_idle(extr: str, timeout: float = 120.0, poll: float = 0.25):
    t0 = time.time()
    while True:
        if _bg_capable is False:
            return False
        st = u1_bg_status(extr, timeout=2.0)
        if st is not None:
            busy, rem = st
            if busy == 0:
                return True
        if time.time() - t0 > timeout:
            return False
        time.sleep(poll)


def _clear_failed_load_state(head: int, lane: int, clear_bt_loaded: bool = True):
    unit = int(head) + 1
    try:
        sc_cfg_clear_active(head, lane)
    except Exception:
        pass
    try:
        _set_bfu_inhibit(head, 0)
    except Exception:
        pass
    if clear_bt_loaded:
        try:
            bt_gcode(
                f"SAVE_VARIABLE VARIABLE={bt_key('at_gears', unit)} VALUE=0\n"
                f"SAVE_VARIABLE VARIABLE={bt_key('hub_owner', unit)} VALUE=0"
            )
        except Exception as e:
            print('gate: WARN load_recover_clear_bt_failed', {'head': head, 'lane': lane, 'unit': unit, 'err': str(e)})


def _recover_failed_load_to_hsw(head: int, lane: int, reason: str, close_puck: bool = True) -> bool:
    unit = int(head) + 1
    rspeed = float(os.getenv("UNLOAD_RSPEED", "150.0"))
    raccel = float(os.getenv("UNLOAD_RACCEL", "400.0"))
    rsplr_run = float(os.getenv('UNLOAD_RSPLR_RUN', '0.50'))
    rsplr_dir = int(os.getenv('UNLOAD_RSPLR_DIR', '0'))
    rsplr_cmd = bt_key('RSPLR_RUN', unit)
    rsplr_stop_cmd = bt_key('RSPLR_STOP', unit)
    cmd = f"{bt_key('SCLUNLOAD', unit)} LANE={int(lane)} SPEED={rspeed:g}"
    if float(raccel) > 0.0:
        cmd += f" ACCEL={raccel:g}"
    cmd += " RETRY=1"
    ok = True
    print('gate: LOAD_RECOVER start', {'head': head, 'lane': lane, 'unit': unit, 'reason': reason, 'cmd': cmd})
    try:
        try:
            bt_gcode(f"{rsplr_cmd} LANE={int(lane)} RUN={rsplr_run:g} DIR={rsplr_dir}")
        except Exception as e:
            print('gate: WARN load_recover_rsplr_start_failed', {'head': head, 'lane': lane, 'unit': unit, 'err': str(e)})
        try:
            bt_gcode(cmd)
        finally:
            try:
                bt_gcode(f"{rsplr_stop_cmd} LANE={int(lane)}")
            except Exception:
                pass
    except Exception as e:
        ok = False
        print('gate: WARN load_recover_sclunload_failed', {'head': head, 'lane': lane, 'unit': unit, 'err': str(e)})
    if ok:
        _clear_failed_load_state(head, lane, clear_bt_loaded=True)
    else:
        _clear_failed_load_state(head, lane, clear_bt_loaded=False)
    if close_puck:
        try:
            servo_toolhead_move(head + 1, 'close')
        except Exception as e:
            print('gate: WARN load_recover_puck_close_failed', {'head': head, 'lane': lane, 'err': str(e)})
    return ok


def handle_load(ev: dict):
    global _busy
    try:
        head = int(ev.get("head", "-1"))
        lane = int(ev.get("lane", "0"))
        go_dist = float(ev.get("go_dist", "0"))
        v = float(ev.get("v", str(GO_V)))
        a = float(ev.get("a", str(GO_A)))
        load_retry = int(ev.get("_load_retry", "0") or 0)
    except Exception as e:
        print("gate: bad EV payload", ev, e)
        with _busy_lock: _busy = False
        return

    if lane not in (1,2,3,4) or go_dist == 0:
        print("gate: ignore LOAD (lane/go_dist missing)", ev)
        with _busy_lock: _busy = False
        return

    ok, why, _cfg = sc_cfg_validate(head, lane, for_unload=False)

    if not ok:

        u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=FAULT reason={why} head={head} lane={lane} src=sidecar"')

        print('gate: FAULT', why, {'head': head, 'lane': lane})

        with _busy_lock: _busy = False

        return

    target_extr = extruder_name_for_head(head)
    max_load_retry = int(os.getenv('LOAD_RETRY_COUNT', '1') or 0)

    def _maybe_retry_load(reason: str, detail=None) -> bool:
        info = {'head': head, 'lane': lane, 'attempt': load_retry, 'reason': reason}
        if detail is not None:
            info['detail'] = detail
        if load_retry < max_load_retry:
            try:
                u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=LOAD_RETRY head={head} lane={lane} try={load_retry + 1} reason={reason} src=sidecar"')
            except Exception:
                pass
            print('gate: LOAD retry scheduled', info)
            rec_ok = _recover_failed_load_to_hsw(head, lane, reason, close_puck=True)
            if not rec_ok:
                return False
            retry_ev = dict(ev)
            retry_ev['_load_retry'] = str(load_retry + 1)
            handle_load(retry_ev)
            return True
        print('gate: LOAD retry exhausted', info)
        _recover_failed_load_to_hsw(head, lane, reason, close_puck=True)
        return False

    try:
        if int(os.getenv('PUCK_ENABLE', '1') or 0):
            tokmap = globals().setdefault('_puck_tok', {})
            tok = int(tokmap.get(head, 0) or 0) + 1
            tokmap[head] = tok
            servo_toolhead_move(head + 1, 'open')
    except Exception as e:
        print('gate: WARN puck_open_failed', {'head': head, 'err': str(e)})
    active_extr, state = u1_active_extruder_and_state()
    if state in ("printing","paused") and active_extr == target_extr:
        u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=FAULT reason=active_extruder head={head} src=sidecar"')
        print("gate: FAULT active extruder", {"active": active_extr, "target": target_extr})
        with _busy_lock: _busy = False
        return

    try:
        if ev.get('src') != 'ui':
            _swap_temp_assert(head, lane, PURGE_TEMP_C, 'load_begin')
    except Exception as e:
        print('gate: WARN load_swap_temp_assert_failed', {'head': head, 'lane': lane, 'err': str(e)})

    if u1_bg_status(target_extr, timeout=2.0) is None:
        u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=FAULT reason=bg_unavailable head={head} lane={lane} src=sidecar"')
        print("gate: FAULT bg_unavailable (no SC_BG_BUSY response)")
        try:
            sc_cfg_clear_active(head, lane)
        except Exception:
            pass
        with _busy_lock:
            _busy = False
        return

    print(f"gate: LOAD head={head} lane={lane} go_dist={go_dist:g} v={v:g} a={a:g}")

    if not bt_hub_clear_precondition(head):
        u1_gcode('RESPOND PREFIX="SC" MSG="EV=FAULT reason=hub_busy src=sidecar"')
        print("gate: FAULT hub_busy (HSW/owner not clear)")
        with _busy_lock: _busy = False
        return


    if AUTO_LTGL:
        print("gate: hub clear precondition OK. starting LTGL then waiting for at_gears cycle 0 -> lane", lane)
        try:
            bt_set_at_gears(head + 1, 0)
            bt_gcode(bt_ltgl_cmd(head + 1, lane))
            print("gate: LTGL queued", lane)
        except Exception as e:
            u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=FAULT reason=ltgl_fail lane={lane} src=sidecar"')
            print("gate: FAULT ltgl_fail", {"lane": lane, "err": str(e)})
            try:
                if ev.get('src') == 'ui':
                    u1_gcode(f"M104 T{head} A0 S0")
            except Exception:
                pass
            with _busy_lock: _busy = False
            return
    else:
        print("gate: hub clear precondition OK. AUTO_LTGL=0 -> waiting for operator LTGL then at_gears cycle 0 -> lane", lane)
    t0 = time.time()
    while True:
        ag = bt_at_gears(head + 1)
        if ag == lane:
            break
        if time.time() - t0 > STALL_TIMEOUT:
            did_retry = _maybe_retry_load('stall_timeout_waitlane', {'at_gears': ag, 'lane': lane})
            if did_retry:
                return
            u1_gcode('RESPOND PREFIX="SC" MSG="EV=FAULT reason=stall_timeout_waitlane src=sidecar"')
            print("gate: FAULT stall_timeout_waitlane", {"at_gears": ag, "lane": lane, "attempt": load_retry})
            try:
                if ev.get('src') == 'ui':
                    u1_gcode(f"M104 T{head} A0 S0")
            except Exception:
                pass
            with _busy_lock: _busy = False
            return
        time.sleep(POLL_SEC)

    print("gate: at_gears latched. arming buffer + starting U1 pull")

    try:
        deadline = time.time() + 0.10
        while time.time() < deadline:
            if bt_comp_state(head + 1) == 1:
                break
            time.sleep(POLL_SEC)
        else:
            did_retry = _maybe_retry_load('no_comp_proof', {'head': head, 'lane': lane})
            if did_retry:
                return
            u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=FAULT reason=no_comp_proof head={head} lane={lane} src=sidecar"')
            print('gate: FAULT no_comp_proof (BFCOMPSW stayed open)', {'attempt': load_retry})
            try:
                if ev.get('src') == 'ui':
                    u1_gcode(f"M104 T{head} A0 S0")
            except Exception:
                pass
            with _busy_lock: _busy = False
            return
    except Exception as e:
        print('gate: WARN comp_proof_check_failed', str(e))



    sc_cfg_set_active(head, lane)

    try:

        _bfu_start_for_head(head)
        _set_bfu_inhibit(head, 0)

        print(f"gate: BFU_START{head + 1} armed")

    except Exception as e:

        u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=FAULT reason=bfstart_fail lane={lane} src=sidecar"')

        print("gate: FAULT bfstart_fail", {"lane": lane, "err": str(e)})
        try:
            sc_cfg_clear_active(head, lane)
        except Exception:
            pass

        with _busy_lock: _busy = False

        return


    comp0 = bt_comp_state(head + 1)
    print("gate: BFCOMPSW start =", comp0)

    try:
        u1_gcode(f"M104 T{head} A0 S{PURGE_TEMP_C}")
    except Exception:
        pass

    def _build_load_segments(total_dist: float, slow_v: float, slow_a: float):
        total = abs(total_dist)
        if total <= 0.0:
            return []
        fast_mm = max(0.0, float(PURGE_FAST_MM or 0.0))
        fast_v = float(PURGE_FAST_V or 0.0)
        configured_slow_v = float(PURGE_SLOW_V or 0.0)
        slow_v_eff = configured_slow_v if configured_slow_v > 0.0 else (slow_v if slow_v and slow_v > 0 else 0.0)
        fast_a = float(PURGE_FAST_A if PURGE_FAST_A and PURGE_FAST_A > 0.0 else slow_a)
        if fast_mm <= 0.0 or fast_v <= 0.0 or total <= fast_mm + 1e-6 or fast_v <= slow_v_eff:
            return [(total_dist, slow_v_eff or slow_v, slow_a, 2001)]
        sign = 1.0 if total_dist >= 0.0 else -1.0
        fast_dist = sign * min(total, fast_mm)
        slow_dist = total_dist - fast_dist
        segs = []
        if abs(fast_dist) > 1e-6:
            segs.append((fast_dist, fast_v, fast_a, 2001))
        if abs(slow_dist) > 1e-6:
            segs.append((slow_dist, slow_v_eff or slow_v, slow_a, 2002))
        return segs

    segments = _build_load_segments(go_dist, v, a)
    if not segments:
        print('gate: FAULT bad_load_segments', {'head': head, 'lane': lane, 'go_dist': go_dist})
        with _busy_lock:
            _busy = False
        return

    total_bg_s = sum(abs(dist) / (vel if vel and vel > 0 else 0.01) for dist, vel, _accel, _line in segments) + 1.0
    load_heat_timeout = float(os.getenv('LOAD_BG_HEAT_TIMEOUT', '20.0'))
    load_heat_min_c = float(os.getenv('LOAD_BG_MIN_TEMP_C', str(max(0.0, PURGE_TEMP_C - 10.0))))
    load_cmd_timeout = max(10.0, load_heat_timeout + 20.0)

    fast_dist, fast_vv, fast_a, fast_line = segments[0]
    if len(segments) > 1:
        slow_dist, slow_vv, slow_aa, slow_line = segments[1]
    else:
        slow_dist, slow_vv, slow_aa, slow_line = 0.0, 0.0, 0.0, 0

    u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=LOAD_BEGIN head={head} lane={lane} dist={go_dist:g} src=sidecar"')
    u1_gcode(
        f'SET_STEPPER_ENABLE STEPPER={target_extr} ENABLE=1\n'
        f'SC_BG_LOAD EXTRUDER={target_extr} TEMP={PURGE_TEMP_C:g} MIN_TEMP={load_heat_min_c:g} '
        f'HEAT_TIMEOUT={load_heat_timeout:g} '
        f'FAST_DIST={fast_dist:g} FAST_V={fast_vv:g} FAST_A={fast_a:g} FAST_LINE={fast_line} '
        f'SLOW_DIST={slow_dist:g} SLOW_V={slow_vv:g} SLOW_A={slow_aa:g} SLOW_LINE={slow_line}',
        timeout=load_cmd_timeout,
    )
    print(
        f"gate: U1 SC_BG_LOAD queued segs={len(segments)} head={head} lane={lane} "
        f"fast={fast_dist:g}@{fast_vv:g} slow={slow_dist:g}@{slow_vv:g}"
    )
    u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=LOAD_GO_SENT head={head} lane={lane} src=sidecar"')

    load_cleanup_timeout = max(240.0, total_bg_s + 120.0)
    load_tok = globals().get('_puck_tok', {}).get(head, 0)

    if comp0 == 1:
        deadline = time.time() + COMP_OPEN_TO
        while time.time() < deadline:
            c = bt_comp_state(head + 1)
            if c == 0:
                print("gate: PULL_EARLY_OK (BFCOMPSW opened)")
                break
            time.sleep(POLL_SEC)
        else:
            print("gate: WARN BFCOMPSW did not open within timeout (pull may still be happening)")

    seq_ok = u1_wait_bg_idle(target_extr, timeout=load_cleanup_timeout, poll=POLL_SEC)
    if not seq_ok:
        try:
            u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=FAULT reason=bg_timeout_load head={head} lane={lane} src=sidecar"')
        except Exception:
            pass
        print('gate: FAULT bg_timeout_load', {'head': head, 'lane': lane})

    try:
        print(f"gate: PUCK_AFTER_LOAD waiting_seq_done head={head} extr={target_extr}")
        if not seq_ok:
            print(f"gate: PUCK_AFTER_LOAD abort head={head} (bg profile not ok)")
        else:
            try:
                if (ev.get('src') or '') == 'ui':
                    park = PARK_TEMP_UI_C
                    u1_gcode(f"M104 T{head} A0 S{park}")
                else:
                    _ae, _st = u1_active_extruder_and_state()
                    park = PARK_TEMP_PRINT_C if _st in ('printing','paused') else PARK_TEMP_UI_C
                    u1_gcode(f"M104 T{head} A0 S{park}")
            except Exception:
                pass

            try:
                if int(os.getenv('PUCK_ENABLE', '1') or 0):
                    tok = load_tok
                    print(f"gate: PUCK_AFTER_LOAD start head={head} tok={tok}")
                    if globals().get('_puck_tok', {}).get(head, tok) != tok:
                        print(f"gate: PUCK_AFTER_LOAD canceled(head={head}) before delay")
                    else:
                        delay = float(os.getenv('PUCK_POST_PURGE_DELAY', '3.0'))
                        print(f"gate: PUCK_AFTER_LOAD delay={delay} head={head}")
                        time.sleep(delay)
                        if globals().get('_puck_tok', {}).get(head, tok) != tok:
                            print(f"gate: PUCK_AFTER_LOAD canceled(head={head}) after delay")
                        else:
                            n = int(os.getenv('PUCK_TOGGLE_COUNT_LOAD', os.getenv('PUCK_TOGGLE_COUNT', '10')))
                            d = float(os.getenv('PUCK_TOGGLE_DWELL', '0.25'))
                            print(f"gate: PUCK_AFTER_LOAD toggling n={n} dwell={d} head={head}")
                            for _ in range(n):
                                if globals().get('_puck_tok', {}).get(head, tok) != tok:
                                    print(f"gate: PUCK_AFTER_LOAD canceled(head={head}) mid-toggle")
                                    break
                                servo_toolhead_move(head + 1, 'close'); time.sleep(d)
                                servo_toolhead_move(head + 1, 'open');  time.sleep(d)
                            servo_toolhead_move(head + 1, 'close')
                            print(f"gate: PUCK_AFTER_LOAD done head={head} (closed)")
            except Exception as e:
                print('gate: WARN puck_after_load_failed', {'head': head, 'err': str(e)})
                print(__import__('traceback').format_exc())
            finally:
                try:
                    if globals().get('_puck_tok', {}).get(head) == load_tok:
                        servo_toolhead_move(head + 1, 'close')
                except Exception:
                    pass

            try:
                if ev.get('src') == 'ui':
                    u1_gcode(f"M104 T{head} A0 S0")
            except Exception:
                pass

            try:
                u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=LOAD_DONE head={head} lane={lane} src=sidecar"')
            except Exception:
                pass

    except Exception as e:
        print('gate: WARN load_cleanup_sync_failed', {'head': head, 'lane': lane, 'err': str(e)})

    with _busy_lock:
        _busy = False

def handle_unload(ev: dict):
    global _busy
    try:
        head = int(ev.get("head", "-1"))
        lane = int(ev.get("lane", "0"))
    except Exception as e:
        print("gate: bad EV payload (UNLOAD)", ev, e)
        with _busy_lock: _busy = False
        return

    if lane not in (1,2,3,4):
        print("gate: ignore UNLOAD (bad lane)", ev)
        with _busy_lock: _busy = False
        return

    target_extr = extruder_name_for_head(head)

    try:
        if ev.get('src') != 'ui':
            _swap_temp_assert(head, lane, PURGE_TEMP_C, 'unload_begin_early')
    except Exception as e:
        print('gate: WARN unload_swap_temp_assert_early_failed', {'head': head, 'lane': lane, 'err': str(e)})

    try:
        if int(os.getenv('PUCK_ENABLE', '1') or 0):
            tokmap = globals().setdefault('_puck_tok', {})
            tok = int(tokmap.get(head, 0) or 0) + 1
            tokmap[head] = tok
            servo_toolhead_move(head + 1, 'open')
    except Exception as e:
        print('gate: WARN puck_open_failed', {'head': head, 'err': str(e)})
    active_extr, state = u1_active_extruder_and_state()

    if state in ("printing","paused") and active_extr == target_extr:
        u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=FAULT reason=active_extruder_unload head={head} src=sidecar"')
        print("gate: FAULT unload requested on active extruder", {"active": active_extr, "target": target_extr})
        with _busy_lock: _busy = False
        return

    try:
        unit = head + 1
        if unit < 1 or unit > 4:
            print('gate: FAULT bad_unit (UNLOAD)', {'head': head, 'lane': lane, 'unit': unit, 'ev': ev})
            try:
                u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=FAULT reason=bad_unit head={head} lane={lane} unit={unit} src=sidecar"')
            except Exception:
                pass
            with _busy_lock: _busy = False
            return
        v = bt_vars()
        owner = int(v.get(bt_key('hub_owner', unit), 0) or 0)
    except Exception:
        owner = 0
    if owner != lane:
        u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=FAULT reason=unload_owner_mismatch lane={lane} owner={owner} src=sidecar"')
        print("gate: FAULT unload_owner_mismatch", {"lane": lane, "owner": owner})
        with _busy_lock: _busy = False
        return

    pre_e   = float(os.getenv("UNLOAD_PRE_E", "5.0"))
    pre_v   = float(os.getenv("UNLOAD_PRE_V", "10.0"))
    r1_mm   = float(os.getenv("UNLOAD_R1_MM", "27.0"))
    r1_v    = float(os.getenv("UNLOAD_R1_V",  "45.0"))
    r2_mm   = float(os.getenv("UNLOAD_R2_MM", "5.5"))
    r2_v    = float(os.getenv("UNLOAD_R2_V",  "0.667"))
    dwell_s = float(os.getenv("UNLOAD_DWELL_S", "3.5"))
    r3_mm   = float(os.getenv("UNLOAD_R3_MM", "37.5"))
    r3_v    = float(os.getenv("UNLOAD_R3_V",  "25.0"))
    a       = float(os.getenv("UNLOAD_A", "0.0"))

    poll    = float(os.getenv("UNLOAD_POLL_SEC", "0.05"))
    pre_to  = float(os.getenv("PREDRAIN_TIMEOUT", "25.0"))
    burst   = float(os.getenv("DRAIN_BURST_MM", "5.0"))
    dv      = float(os.getenv("DRAIN_V", "150.0"))
    da      = float(os.getenv("DRAIN_A", "800.0"))
    rspeed = float(os.getenv("UNLOAD_RSPEED", "150.0"))
    raccel = float(os.getenv("UNLOAD_RACCEL", "400.0"))
    bg_preflight_timeout = float(os.getenv("UNLOAD_BG_PREFLIGHT_TIMEOUT", "2.0"))
    bg_preflight_attempts = int(os.getenv("UNLOAD_BG_PREFLIGHT_ATTEMPTS", "4"))
    bg_preflight_retry_delay = float(os.getenv("UNLOAD_BG_PREFLIGHT_RETRY_DELAY", "0.75"))

    print(f"gate: UNLOAD head={head} lane={lane} extr={target_extr}")


    ok, why, _cfg = sc_cfg_validate(head, lane, for_unload=True)

    if not ok:

        u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=FAULT reason={why} head={head} lane={lane} src=sidecar"')

        print('gate: FAULT', why, {'head': head, 'lane': lane})

        with _busy_lock: _busy = False

        return


    try:
        _set_bfu_inhibit(head, 1)
        ev['_unload_inhibit_set'] = True
    except Exception:
        ev['_unload_inhibit_set'] = False

    try:
        if ev.get('src') != 'ui':
            _swap_temp_assert(head, lane, PURGE_TEMP_C, 'unload_begin')
    except Exception as e:
        print('gate: WARN unload_swap_temp_assert_failed', {'head': head, 'lane': lane, 'err': str(e)})

    try:
        _bfu_stop_for_head(head)
        print(f"gate: BFU_STOP{unit} OK")
    except Exception as e:
        print("gate: WARN BFU_STOP failed (continuing)", {"unit": unit, "lane": lane, "err": str(e)})

    rsplr_started = False
    try:
        if False and unit != 1:
            rsplr_run = float(os.getenv('UNLOAD_RSPLR_RUN', '0.50'))
            rsplr_dir = int(os.getenv('UNLOAD_RSPLR_DIR', '0'))
            bt_gcode(f"RSPLR_RUN{unit} LANE={lane} RUN={rsplr_run:g} DIR={rsplr_dir}")
            rsplr_started = True
    except Exception as e:
        print('gate: WARN rsplr_start_failed', {'unit': unit, 'lane': lane, 'err': str(e)})

    if u1_bg_status_retry(target_extr, attempts=bg_preflight_attempts,
                          timeout=bg_preflight_timeout, delay=bg_preflight_retry_delay) is None:
        _park_failed_unload_temp(head, lane)
        u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=FAULT reason=bg_unavailable_unload head={head} lane={lane} src=sidecar"')
        print("gate: FAULT bg_unavailable_unload (no SC_BG_BUSY response)",
              {"head": head, "lane": lane, "attempts": bg_preflight_attempts, "timeout": bg_preflight_timeout})
        with _busy_lock:
            _busy = False
        return

    t0 = time.time()
    while True:
        if bt_tension_state(unit) == 1:
            break
        if time.time() - t0 > pre_to:
            u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=FAULT reason=predrain_timeout lane={lane} src=sidecar"')
            print("gate: FAULT predrain_timeout", {"lane": lane})
            try:
                if 'rsplr_started' in locals() and rsplr_started and unit != 1:
                    bt_gcode(f"RSPLR_STOP{unit} LANE={lane}")
            except Exception:
                pass
            _park_failed_unload_temp(head, lane)
            with _busy_lock: _busy = False
            return
        bt_lane_retract_burst(lane, burst, dv, da, unit=unit)
        time.sleep(poll)
    print("gate: predrain OK (TENSW triggered)")


    stop_flag = {"stop": False}
    def drain_thread():
        deadline = time.time() + 120.0
        while (not stop_flag["stop"]) and time.time() < deadline:
            try:
                comp = bt_comp_state(head + 1)
                if comp == 1:
                    while not stop_flag["stop"]:
                        if bt_tension_state(unit) == 1:
                            break
                        bt_lane_retract_burst(lane, burst, dv, da, unit=unit)
                        time.sleep(poll)
                time.sleep(poll)
            except Exception:
                time.sleep(poll)

    threading.Thread(target=drain_thread, daemon=True).start()

    unload_heat_timeout = float(os.getenv('UNLOAD_BG_HEAT_TIMEOUT', '20.0'))
    unload_heat_min_c = float(os.getenv('UNLOAD_BG_MIN_TEMP_C', str(PURGE_TEMP_C)))
    unload_cmd_timeout = max(10.0, unload_heat_timeout + 20.0)
    unload_motion_s = 0.0
    for _dist, _vel in ((pre_e, pre_v), (r1_mm, r1_v), (r2_mm, r2_v), (r3_mm, r3_v)):
        if _dist and _vel:
            unload_motion_s += abs(_dist) / max(float(_vel), 0.01)
    unload_wait_timeout = max(180.0, unload_heat_timeout + unload_motion_s + dwell_s + 10.0)

    u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=UNLOAD_BEGIN head={head} lane={lane} src=sidecar"')
    u1_gcode(
        f'SET_STEPPER_ENABLE STEPPER={target_extr} ENABLE=1\n'
        f'SC_BG_UNLOAD EXTRUDER={target_extr} TEMP={PURGE_TEMP_C:g} MIN_TEMP={unload_heat_min_c:g} '
        f'HEAT_TIMEOUT={unload_heat_timeout:g} '
        f'PRE_DIST={pre_e:g} PRE_V={pre_v:g} '
        f'R1_DIST={-r1_mm:g} R1_V={r1_v:g} '
        f'R2_DIST={-r2_mm:g} R2_V={r2_v:g} '
        f'DWELL_S={dwell_s:g} '
        f'R3_DIST={-r3_mm:g} R3_V={r3_v:g} '
        f'ACCEL={a:g}',
        timeout=unload_cmd_timeout,
    )
    print(
        f"gate: U1 SC_BG_UNLOAD queued head={head} lane={lane} extr={target_extr} "
        f"pre={pre_e:g}@{pre_v:g} r1={r1_mm:g}@{r1_v:g} r2={r2_mm:g}@{r2_v:g} dwell={dwell_s:g} r3={r3_mm:g}@{r3_v:g}"
    )

    try:
        print(f"gate: UNLOAD_PROFILE_WAIT_BEGIN t={time.time():.3f} head={head} lane={lane} extr={target_extr}")
    except Exception:
        pass
    ok = u1_wait_bg_idle(target_extr, timeout=unload_wait_timeout, poll=poll)
    if not ok:
        u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=FAULT reason=bg_timeout head={head} lane={lane} src=sidecar"')
        print('gate: FAULT bg_timeout')
        stop_flag['stop'] = True
        try:
            if 'rsplr_started' in locals() and rsplr_started and unit != 1:
                bt_gcode(f"RSPLR_STOP{unit} LANE={lane}")
        except Exception:
            pass
        _park_failed_unload_temp(head, lane)
        with _busy_lock: _busy = False
        return
    try:
        print(f"gate: UNLOAD_PROFILE_IDLE t={time.time():.3f} head={head} lane={lane} extr={target_extr}")
    except Exception:
        pass

    try:
        post_r3_settle_s = float(os.getenv("UNLOAD_POST_R3_SETTLE_S", "0.10"))
    except Exception:
        post_r3_settle_s = 1.00
    if post_r3_settle_s > 0.0:
        try:
            print(f"gate: UNLOAD_POST_R3_SETTLE t={time.time():.3f} head={head} lane={lane} wait={post_r3_settle_s:.3f}")
        except Exception:
            pass
        time.sleep(post_r3_settle_s)

    stop_flag['stop'] = True


    try:
        cmd = (f"UNLOADL{lane}" if unit == 1 else f"{bt_key('SCLUNLOAD', unit)} LANE={lane} SPEED={rspeed:g}")
        try:
            print(f"gate: UNLOAD_FINAL_PULL_ARM t={time.time():.3f} head={head} lane={lane} unit={unit} cmd={cmd}")
        except Exception:
            pass
        print(f"gate: issuing UNLOAD cmd={cmd} head={head} unit={unit} lane={lane}")
        if unit != 1:
            rsplr_run = float(os.getenv('UNLOAD_RSPLR_RUN', '0.50'))
            rsplr_dir = int(os.getenv('UNLOAD_RSPLR_DIR', '0'))
            try:
                bt_gcode(f"RSPLR_RUN{unit} LANE={lane} RUN={rsplr_run:g} DIR={rsplr_dir}")
            except Exception as e:
                print('gate: WARN rsplr_start_failed', {'unit': unit, 'lane': lane, 'err': str(e)})
            try:
                bt_gcode(cmd)
            finally:
                try:
                    bt_gcode(f"RSPLR_STOP{unit} LANE={lane}")
                except Exception:
                    pass
        else:
            bt_gcode(cmd)
        sc_cfg_clear_active(head, lane)

    except Exception as e:
        print("gate: WARN UNLOAD finish failed", {"lane": lane, "unit": unit, "err": str(e)})
        try:
            u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=FAULT reason=unload_finish_fail lane={lane} unit={unit} src=sidecar"')
        except Exception:
            pass
        _park_failed_unload_temp(head, lane)
        with _busy_lock: _busy = False
        return

    try:
        v = bt_vars()
        agk = bt_key('at_gears', unit)
        oky = bt_key('hub_owner', unit)
        lky = f"need_lth{lane}" if unit == 1 else f"need_lth{lane}{unit}"
        if int(v.get(agk, 0) or 0) == lane:
            bt_gcode(f"SAVE_VARIABLE VARIABLE={agk} VALUE=0")
        if int(v.get(oky, 0) or 0) == lane:
            bt_gcode(f"SAVE_VARIABLE VARIABLE={oky} VALUE=0")
        if int(v.get(lky, 0) or 0) != 0:
            bt_gcode(f"SAVE_VARIABLE VARIABLE={lky} VALUE=0")
    except Exception as e:
        print('gate: WARN unload_clear_state_failed', {'unit': unit, 'lane': lane, 'err': str(e)})

    try:
        if int(os.getenv('PUCK_ENABLE', '1') or 0):
            tok = globals().get('_puck_tok', {}).get(head, 0)
            if ev.get('src') != 'ui':
                print(f"gate: PUCK_AFTER_UNLOAD skip_auto head={head} tok={tok}")
            else:
                try:
                    print(f"gate: PUCK_AFTER_UNLOAD start head={head} tok={tok}")
                    if globals().get('_puck_tok', {}).get(head, tok) != tok:
                        print(f"gate: PUCK_AFTER_UNLOAD canceled(head={head}) before delay")
                    else:
                        delay = float(os.getenv('PUCK_POST_UNLOAD_DELAY', os.getenv('PUCK_POST_PURGE_DELAY', '3.0')))
                        print(f"gate: PUCK_AFTER_UNLOAD delay={delay} head={head}")
                        time.sleep(delay)
                        if globals().get('_puck_tok', {}).get(head, tok) != tok:
                            print(f"gate: PUCK_AFTER_UNLOAD canceled(head={head}) after delay")
                        else:
                            n = int(os.getenv('PUCK_TOGGLE_COUNT_UNLOAD', os.getenv('PUCK_TOGGLE_COUNT', '10')))
                            d = float(os.getenv('PUCK_TOGGLE_DWELL', '0.25'))
                            print(f"gate: PUCK_AFTER_UNLOAD toggling n={n} dwell={d} head={head}")
                            for _ in range(n):
                                if globals().get('_puck_tok', {}).get(head, tok) != tok:
                                    print(f"gate: PUCK_AFTER_UNLOAD canceled(head={head}) mid-toggle")
                                    break
                                servo_toolhead_move(head + 1, 'close'); time.sleep(d)
                                servo_toolhead_move(head + 1, 'open');  time.sleep(d)
                            servo_toolhead_move(head + 1, 'close')
                            print(f"gate: PUCK_AFTER_UNLOAD done head={head} (closed)")
                except Exception as e:
                    print('gate: WARN puck_after_unload_failed', {'head': head, 'err': str(e)})
                    print(__import__('traceback').format_exc())
                finally:
                    try:
                        if globals().get('_puck_tok', {}).get(head) == tok:
                            servo_toolhead_move(head + 1, 'close')
                    except Exception:
                        pass
    except Exception:
        pass

    u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=UNLOAD_DONE head={head} lane={lane} src=sidecar"')

    ev['_unload_success'] = True

    try:
        if ev.get('src') == 'ui':
            u1_gcode(f"M104 T{head} A0 S0")
    except Exception:
        pass
    with _busy_lock:
        _busy = False

def jrpc(method, params=None, _id=1):
    m = {"jsonrpc": "2.0", "method": method, "id": _id}
    if params is not None:
        m["params"] = params
    return json.dumps(m)

def on_open(ws):
    print("gate: WS connected ->", U1_WS)
    ws.send(jrpc("server.connection.identify",
                 {"client_name":"sc-gate","version":"0.3","type":"agent","url":CLIENT_URL}, 1))
    ws.send(jrpc("printer.objects.subscribe",
                 {"objects":{"print_stats":None,"virtual_sdcard":None}}, 2))
    print("gate: listening for EV=LOAD … (Ctrl+C to exit)")

def on_message(ws, message):
    global _busy, _bg_capable
    try:
        msg = json.loads(message)
    except Exception:
        return
    if "id" in msg:
        return
    if msg.get("method") != "notify_gcode_response":
        return

    line = (msg.get("params") or [""])[0]
    if not isinstance(line, str):
        return

    if "SC_BG_" in line and "unknown command" in line.lower():
        _bg_capable = False
        with _bg_cond:
            _bg_cond.notify_all()


    m_busy = re.search(r'SC_BG_BUSY\s+busy=(\d+)\s+remaining=([0-9.]+)', line)

    if m_busy:

        with _bg_cond:

            global _bg_last

            _bg_capable = True

            _bg_last = (int(m_busy.group(1)), float(m_busy.group(2)))

            _bg_cond.notify_all()



    ev = parse_ev(line)
    if not ev:
        return
    if ev.get("src") == "sidecar":
        return
    kind = ev.get("EV")
    if kind not in ("LOAD", "UNLOAD"):
        return

    with _busy_lock:
        if _busy:
            print("gate: BUSY queueing", kind, ev)
            _enqueue_ev(ev)
            return
            try:
                h = ev.get("head", "?")
                l = ev.get("lane", "?")
                u1_gcode(f'RESPOND PREFIX="SC" MSG="EV=BUSY kind={kind} reason=gate_busy head={h} lane={l} src=sidecar"')
            except Exception:
                pass
            return
        _busy = True

    if kind == "LOAD":
        threading.Thread(target=_handle_load_safe, args=(ev,), daemon=True).start()
    else:
        threading.Thread(target=_handle_unload_safe, args=(ev,), daemon=True).start()


BF_FOLLOW_ACTIVE = int(os.getenv("BF_FOLLOW_ACTIVE", "1") or 0)
BF_FOLLOW_POLL_S = float(os.getenv("BF_FOLLOW_POLL_S", "0.25"))

def _u1_head_from_extruder_name(extr: str) -> int:
    if extr == "extruder":
        return 0
    m = re.match(r"^extruder(\d+)$", str(extr or "").strip())
    return int(m.group(1)) if m else -1

def _bt_hub_owner_lane_for_head(head: int) -> int:
    v = bt_vars()
    unit = head + 1
    key = "hub_owner" if unit == 1 else ("hub_owner" + str(unit))
    try:
        return int(v.get(key, 0) or 0)
    except Exception:
        return 0

def _bt_bf_stop_all():
    bt_gcode("BFU_STOP1\nBFU_STOP2\nBFU_STOP3\nBFU_STOP4")

def _bt_bf_start(unit: int, lane: int):
    _ = lane
    bt_gcode(f"BFU_START{unit}")

def bf_follow_active_loop():
    last = None
    while True:
        try:
            if not BF_FOLLOW_ACTIVE:
                time.sleep(BF_FOLLOW_POLL_S)
                continue

            active_extr, state = u1_active_extruder_and_state()
            if state not in ("printing", "paused"):
                last = None
                time.sleep(BF_FOLLOW_POLL_S)
                continue

            head = _u1_head_from_extruder_name(active_extr)
            if head not in (0,1,2,3):
                time.sleep(BF_FOLLOW_POLL_S)
                continue

            try:
                with _busy_lock:
                    busy_now = bool(_busy)
            except Exception:
                busy_now = False
            if busy_now:
                time.sleep(BF_FOLLOW_POLL_S)
                continue

            lane = _bt_hub_owner_lane_for_head(head)
            unit = head + 1
            if lane not in (1,2,3,4):
                time.sleep(BF_FOLLOW_POLL_S)
                continue

            cur = (unit, lane)
            if cur != last:
                _bt_bf_stop_all()
                _bt_bf_start(unit, lane)
                print(f"gate: BF_FOLLOW active_head={head} unit={unit} lane={lane}")
                last = cur

        except Exception as e:
            print("gate: BF_FOLLOW_ERROR", str(e))

        time.sleep(BF_FOLLOW_POLL_S)


def on_error(ws, err):  print("gate: WS_ERROR", err)
def on_close(ws, c, r): print("gate: WS closed", c, r)

if __name__ == "__main__":
    threading.Thread(target=start_api_server, daemon=True).start()
    threading.Thread(target=bf_follow_active_loop, daemon=True).start()

    app = websocket.WebSocketApp(U1_WS, on_open=on_open, on_message=on_message,
                                 on_error=on_error, on_close=on_close)
    app.run_forever(ping_interval=20, ping_timeout=10)
