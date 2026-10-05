#!/usr/bin/env python3
import os, time, json
from urllib.parse import quote
import urllib.request

MOONRAKER = os.getenv("MOONRAKER_URL", "http://10.42.0.10:7125").rstrip("/")
POLL_SEC = float(os.getenv("POLL_SEC", "0.5"))
AUTO_START_WINDOW = int(os.getenv("AUTO_START_WINDOW", "300"))
LOG_PREFIX = os.getenv("LOG_PREFIX", "SC_AUTO")
SCAN_BYTES = int(os.getenv("SCAN_BYTES", "1048576"))

CANCEL_RAW_ON_ARM = os.getenv("CANCEL_RAW_ON_ARM", "1").strip().lower() in ("1","true","yes","on")

APPLY_MAP = os.getenv("APPLY_MAP", "1").strip().lower() in ("1","true","yes","on")
SC_HEADS_CFG = os.getenv("SC_HEADS_CFG", "/home/sidecar/sidecar/state/sc_heads.json")
LANES_PER_SC = int(os.getenv("LANES_PER_SC", "4"))

API_KEY = os.getenv("MOONRAKER_API_KEY")
BEARER = os.getenv("MOONRAKER_BEARER_TOKEN")

MARK_REQ = b"SIDECAR:REQUEST=1"
MARK_PRO = b"SIDECAR:PROCESSED=1"
MARK_BLK = b"SIDECAR:BLOCKED=1"

def _auth_headers():
    h = {}
    if API_KEY:
        h["X-Api-Key"] = API_KEY
    if BEARER:
        h["Authorization"] = f"Bearer {BEARER}"
    return h

def http_get_json(url: str, timeout: float = 8.0) -> dict:
    req = urllib.request.Request(url, method="GET", headers=_auth_headers())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))

def http_post_json(url: str, payload: dict, timeout: float = 10.0) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, method="POST", data=data, headers=_auth_headers())
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))

def get_gcodes_meta():
    j = http_get_json(f"{MOONRAKER}/server/files/list?root=gcodes")
    files = j.get('result', [])
    meta = {}
    for it in files:
        p = it.get('path')
        if isinstance(p, str):
            meta[p] = it
    return meta

def get_modified(meta: dict, rel_path: str):
    try:
        return float((meta.get(rel_path) or {}).get('modified', 0.0) or 0.0)
    except Exception:
        return 0.0

def get_print_state():
    j = http_get_json(f"{MOONRAKER}/printer/objects/query?print_stats&virtual_sdcard")
    st = j.get("result", {}).get("status", {})
    ps = st.get("print_stats", {}) or {}
    vsd = st.get("virtual_sdcard", {}) or {}
    return ps, vsd

def is_idle(ps: dict, vsd: dict) -> bool:
    st = (ps.get("state") or "")
    active = bool(vsd.get("is_active"))
    return (st not in ("printing", "paused")) and (not active)

def is_active(ps: dict, vsd: dict) -> bool:
    st = (ps.get("state") or "")
    return bool(vsd.get("is_active")) or (st in ("printing", "paused"))

def file_exists_gcodes(rel_path: str) -> bool:
    url = f"{MOONRAKER}/server/files/gcodes/{quote(rel_path, safe='/')}"
    req = urllib.request.Request(url, method="GET", headers=_auth_headers())
    req.add_header("Range", "bytes=0-0")
    try:
        with urllib.request.urlopen(req, timeout=8.0) as r:
            return r.status in (200, 206)
    except Exception:
        return False

def scan_markers(rel_path: str, scan_bytes: int = SCAN_BYTES):
    url = f"{MOONRAKER}/server/files/gcodes/{quote(rel_path, safe='/')}"
    req = urllib.request.Request(url, method="GET", headers=_auth_headers())
    req.add_header("Range", f"bytes=0-{max(0, scan_bytes-1)}")
    try:
        with urllib.request.urlopen(req, timeout=8.0) as r:
            data = r.read()
        return (MARK_REQ in data, MARK_PRO in data, MARK_BLK in data)
    except Exception:
        return (False, False, False)

def start_print(rel_path: str) -> None:
    http_post_json(f"{MOONRAKER}/printer/gcode/script",
                   {"script": f'SDCARD_PRINT_FILE FILENAME="{rel_path}"'})

def cancel_print() -> None:
    http_post_json(f"{MOONRAKER}/printer/gcode/script", {"script": "CANCEL_PRINT"})

def apply_extruder_map() -> bool:
    """
    Block-of-four virtual tool numbering:
      head = T // 4   (0..3)
      lane = (T % 4) + 1

    Native mapping before starting SCPRO_:
      T0..T3   -> head0
      T4..T7   -> head1
      T8..T11  -> head2
      T12..T15 -> head3
    """
    if not APPLY_MAP:
        return True

    try:
        with open(SC_HEADS_CFG, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        heads = (cfg.get("heads") or {})
        managed = sorted([int(k) for k,v in heads.items() if isinstance(v, dict) and v.get("managed")])
    except Exception:
        managed = []

    ops = {}
    for t in range(0, 16):
        ops[t] = t // 4

    for t in range(16, 32):
        ops[t] = 0

    script = "\n".join([f"SET_PRINT_EXTRUDER_MAP CONFIG_EXTRUDER={t} MAP_EXTRUDER={p}"
                        for t, p in sorted(ops.items())])

    try:
        script = "SET_PRINT_USED_EXTRUDERS EXTRUDERS=0,1,2,3\n" + script
        http_post_json(f"{MOONRAKER}/printer/gcode/script", {"script": script})
        print(f"{LOG_PREFIX}: MAP_OK toolmap=block4 managed={managed} ops={len(ops)}")
        return True
    except Exception as e:
        print(f"{LOG_PREFIX}: MAP_ERROR toolmap=block4 gcode_fail {e}")
        return False
def main():
    ps_init, vsd_init = get_print_state()
    prev_active = is_active(ps_init, vsd_init)
    prev_fn = (ps_init.get("filename") or "")

    pending = None

    print(f"{LOG_PREFIX}: running poll={POLL_SEC}s window={AUTO_START_WINDOW}s moonraker={MOONRAKER} cancel_on_arm={int(CANCEL_RAW_ON_ARM)} apply_map={int(APPLY_MAP)}")

    while True:
        try:
            ps, vsd = get_print_state()
            fn = (ps.get("filename") or "")
            active_now = is_active(ps, vsd)
            rising = (not prev_active) and active_now
            fn_changed = bool(fn) and (fn != prev_fn)
            prev_active = active_now
            prev_fn = fn

            if (rising or fn_changed) and fn and (not os.path.basename(fn).startswith("SCPRO_")):
                req, pro, blk = scan_markers(fn)
                if not req or pro or blk:
                    time.sleep(POLL_SEC)
                    continue

                base = os.path.basename(fn)
                d = os.path.dirname(fn)
                proc = f"{d}/SCPRO_{base}" if d else f"SCPRO_{base}"
                pending = {"raw": fn, "proc": proc, "armed_at": time.time(), "cancel_sent": False}
                print(f"{LOG_PREFIX}: ARMED raw={fn} proc={proc}")

                if CANCEL_RAW_ON_ARM and active_now:
                    try:
                        cancel_print()
                        pending["cancel_sent"] = True
                        print(f"{LOG_PREFIX}: CANCEL_SENT raw={fn}")
                    except Exception as e:
                        print(f"{LOG_PREFIX}: CANCEL_ERROR {e}")

            if pending:
                age = time.time() - pending["armed_at"]
                if age > AUTO_START_WINDOW:
                    print(f"{LOG_PREFIX}: EXPIRE raw={pending['raw']}")
                    pending = None
                else:
                    meta2 = get_gcodes_meta()
                    proc_mod = get_modified(meta2, pending['proc'])
                    if proc_mod and proc_mod < float(pending.get('raw_mod', 0.0)):
                        time.sleep(POLL_SEC)
                        continue
                    if file_exists_gcodes(pending["proc"]):
                        ps2, vsd2 = get_print_state()
                        if is_idle(ps2, vsd2):
                            if not apply_extruder_map():
                                print(f"{LOG_PREFIX}: AUTO_START_ABORT map_failed proc={pending['proc']}")
                                pending = None
                            else:
                                try:
                                    start_print(pending["proc"])
                                    print(f"{LOG_PREFIX}: AUTO_START_OK {pending['proc']}")
                                except Exception as e:
                                    print(f"{LOG_PREFIX}: AUTO_START_ERROR {e}")
                                pending = None

        except Exception as e:
            print(f"{LOG_PREFIX}: LOOP_ERROR {e}")

        time.sleep(POLL_SEC)

if __name__ == "__main__":
    main()
