#!/usr/bin/env python3
from __future__ import annotations

import os, sys, json, time, shutil, subprocess
from pathlib import Path
from urllib.parse import quote
import urllib.request

MARK_REQ = b"SIDECAR:REQUEST=1"
MARK_PRO = b"SIDECAR:PROCESSED=1"
MARK_BLK = b"SIDECAR:BLOCKED=1"

def ebool(name: str, default: bool=False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1","true","yes","on")

def get_int(name: str, default: int) -> int:
    v = os.getenv(name)
    return default if not v else int(v)

def get_float(name: str, default: float) -> float:
    v = os.getenv(name)
    return default if not v else float(v)

MOONRAKER = os.getenv("MOONRAKER_URL", "http://10.42.0.10:7125").rstrip("/")
API_KEY = os.getenv("MOONRAKER_API_KEY")
BEARER = os.getenv("MOONRAKER_BEARER_TOKEN")

def _auth_headers() -> dict[str,str]:
    h = {}
    if API_KEY:
        h["X-Api-Key"] = API_KEY
    if BEARER:
        h["Authorization"] = f"Bearer {BEARER}"
    return h

def http_get_json(url: str, timeout: float=12.0) -> dict:
    req = urllib.request.Request(url, method="GET", headers=_auth_headers())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))

def http_get_range(url: str, nbytes: int, timeout: float=12.0) -> bytes:
    req = urllib.request.Request(url, method="GET", headers=_auth_headers())
    req.add_header("Range", f"bytes=0-{nbytes-1}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def http_download(url: str, dest: Path, timeout: float=180.0) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, method="GET", headers=_auth_headers())
    with urllib.request.urlopen(req, timeout=timeout) as r, dest.open("wb") as f:
        shutil.copyfileobj(r, f)

def curl_json(args: list[str]) -> dict:
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"curl rc={p.returncode}: {p.stderr.strip()}")
    try:
        response = json.loads(p.stdout)
    except (ValueError, TypeError) as e:
        raise RuntimeError("Moonraker returned invalid JSON") from e
    if not isinstance(response, dict) or response.get("error"):
        raise RuntimeError("Moonraker request failed: %s" % response)
    return response

def _curl_auth_args() -> list[str]:
    a = []
    if API_KEY:
        a += ["-H", f"X-Api-Key: {API_KEY}"]
    if BEARER:
        a += ["-H", f"Authorization: Bearer {BEARER}"]
    return a

def upload_file(local_path: Path, dest_dir: str, dest_name: str) -> dict:
    url = f"{MOONRAKER}/server/files/upload"
    args = ["curl","-sS"] + _curl_auth_args() + ["-X","POST","-F","root=gcodes"]
    if dest_dir:
        args += ["-F", f"path={dest_dir}"]
    args += ["-F", f"file=@{str(local_path)};filename={dest_name}", url]
    return curl_json(args)

def move_file(src_rel: str, dst_rel: str) -> dict:
    url = f"{MOONRAKER}/server/files/move"
    body = json.dumps({"source": f"gcodes/{src_rel}", "dest": f"gcodes/{dst_rel}"})
    args = ["curl","-sS"] + _curl_auth_args() + [
        "-H","Content-Type: application/json",
        "-X","POST","-d", body, url
    ]
    return curl_json(args)


def delete_file(rel_path: str) -> dict:
    url = f"{MOONRAKER}/server/files/gcodes/{quote(rel_path, safe='/')}"
    args = ["curl","-sS"] + _curl_auth_args() + ["-X","DELETE", url]
    return curl_json(args)



def get_print_state():
    j = http_get_json(f"{MOONRAKER}/printer/objects/query?print_stats&virtual_sdcard")
    st = j.get("result", {}).get("status", {})
    ps = st.get("print_stats", {}) or {}
    vsd = st.get("virtual_sdcard", {}) or {}
    return ps, vsd

def run_gcode(script: str) -> dict:
    body = json.dumps({"script": script})
    url = f"{MOONRAKER}/printer/gcode/script"
    args = ["curl","-sS"] + _curl_auth_args() + ["-H","Content-Type: application/json","-X","POST","-d", body, url]
    return curl_json(args)


def run_preprocess(job_dir: Path, preprocessor: Path, sc_heads: str, lanes_per_sc: int, purge_len: float, infile: Path) -> Path:
    cmd = [
        sys.executable, str(preprocessor),
        "--sc-heads", sc_heads,
        "--lanes-per-sc", str(lanes_per_sc),
        "--purge-len", str(purge_len),
        infile.name,
    ]
    p = subprocess.run(cmd, cwd=str(job_dir), capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"preprocess rc={p.returncode}\nSTDERR:\n{(p.stderr or '')[-3000:]}")
    out = job_dir / f"SCPRO_{infile.name}"
    if not out.exists():
        raise RuntimeError(f"missing output: {out}")
    return out

def main() -> int:
    poll_sec = get_float("POLL_SEC", 2.0)
    scan_bytes = get_int("SCAN_BYTES", 8192)
    stability_passes = get_int("STABILITY_PASSES", 2)
    max_check = get_int("MAX_CHECK", 10)

    run_once = ebool("RUN_ONCE", False)
    dry_run = ebool("DRY_RUN", False)
    firewall = ebool("FIREWALL_RAW", False)
    delete_raw = ebool("DELETE_RAW", False)
    auto_start = ebool("AUTO_START", False)
    auto_start_window = get_int("AUTO_START_WINDOW", 180)
    keep_jobs = ebool("KEEP_JOBS", False)
    verbose = ebool("VERBOSE", False)

    preprocessor = Path(os.getenv("PREPROCESSOR", "/home/sidecar/sidecar/preprocess/sc_preprocess_block4.py"))
    block_stub = Path(os.getenv("BLOCK_STUB", "/home/sidecar/sidecar/preprocess/SC_BLOCK_STUB.gcode"))
    job_root = Path(os.getenv("JOB_ROOT", "/home/sidecar/sidecar/preprocess/_jobs"))

    sc_heads = os.getenv("SC_HEADS", "0,1,2,3")
    lanes_per_sc = get_int("LANES_PER_SC", 4)
    purge_len = get_float("PURGE_LEN", 80.0)

    info = http_get_json(f"{MOONRAKER}/server/info").get("result", {})
    print(f"Moonraker={MOONRAKER} klippy_state={info.get('klippy_state')} connected={info.get('klippy_connected')}")

    stable: dict[str, tuple[float,int,int]] = {}

    def pass_once() -> None:
        j = http_get_json(f"{MOONRAKER}/server/files/list?root=gcodes")
        files = j.get("result", [])
        meta = {it.get("path"): it for it in files if isinstance(it.get("path"), str)}

        if verbose: print(f"files={len(files)} scan_bytes={scan_bytes} stability_passes={stability_passes} dry_run={int(dry_run)} firewall={int(firewall)}")

        candidates: list[tuple[float,str,int]] = []
        paths_sorted = sorted(meta.keys(), key=lambda p: float(meta[p].get('modified',0.0)), reverse=True)
        for path in paths_sorted[:max_check]:
            it = meta[path]
            if not isinstance(path, str) or not path.lower().endswith(".gcode"):
                continue
            base = os.path.basename(path)
            if path.startswith("sidecar_quarantine/"):
                continue


            if base.startswith("SCPRO_"):
                continue
            if ".sidecar_raw." in base:
                continue
            if base.startswith("SCBLOCK_") or base.startswith("SCFAIL_"):
                continue

            modified = float(it.get("modified", 0.0))
            size = int(it.get("size", 0))

            prev = stable.get(path)
            st = (prev[2] + 1) if (prev and prev[0] == modified and prev[1] == size) else 1
            stable[path] = (modified, size, st)
            if st < stability_passes:
                continue

            dest_dir = os.path.dirname(path)
            pro_path = f"{dest_dir}/SCPRO_{base}" if dest_dir else f"SCPRO_{base}"
            pro_it = meta.get(pro_path)

            if pro_it:
                pro_mod = float(pro_it.get("modified", 0.0))
                if pro_mod >= modified:
                    continue

            url = f"{MOONRAKER}/server/files/gcodes/{quote(path, safe='/')}"
            try:
                head = http_get_range(url, scan_bytes)
            except Exception as e:
                print(f"WARN head-scan failed: {path}: {e}")
                continue

            if (MARK_REQ in head) and (MARK_PRO not in head) and (MARK_BLK not in head):
                candidates.append((modified, path, size))

        if not candidates:
            if verbose: print("candidates=0")
            return

        candidates.sort(key=lambda x: x[0])
        print(f"candidates={len(candidates)}")
        for m,pth,sz in candidates[:10]:
            print(f"  - {pth} size={sz} modified={m}")

        _, path, expected_size = candidates[0]
        base = os.path.basename(path)
        dest_dir = os.path.dirname(path)
        out_name = f"SCPRO_{base}"

        print(f"SELECT: {path}")
        print(f"PLAN: preprocess -> upload {out_name} (dir='{dest_dir or '.'}')")
        if firewall:
            print("PLAN: firewall raw (move + stub replace)")

        if dry_run:
            return

        ts = int(time.time())
        job_dir = job_root / f"job_{ts}_{os.getpid()}"
        job_dir.mkdir(parents=True, exist_ok=True)

        try:
            raw_local = job_dir / base
            raw_url = f"{MOONRAKER}/server/files/gcodes/{quote(path, safe='/')}"
            http_download(raw_url, raw_local)
            actual_size = raw_local.stat().st_size
            if expected_size and actual_size != expected_size:
                raise RuntimeError(f"download size mismatch raw={path} expected={expected_size} got={actual_size}")

            try:
                out_local = run_preprocess(job_dir, preprocessor, sc_heads, lanes_per_sc, purge_len, raw_local)
                up = upload_file(out_local, dest_dir, out_name)
                print(f"UPLOAD_OK: {up.get('action')} path={up.get('item',{}).get('path')}")
            except Exception as e:
                print(f"PREPROCESS_FAIL: {e}")
                if not firewall:
                    print(f"RAW_UNCHANGED: {path}")
                    return
                try:
                    bak = (path[:-6] + f".sidecar_raw.{ts}.gcode") if path.lower().endswith(".gcode") else f"{path}.sidecar_raw.{ts}.gcode"
                    mv = move_file(path, bak)
                    print(f"MOVE_OK: {mv.get('result',{}).get('item',{}).get('path')}")
                except Exception as e2:
                    print(f"MOVE_ERROR: {e2}")
                try:
                    reason = str(e).replace("\n"," ")[:160]
                    stub_txt = (
                        ";SIDECAR:BLOCKED=1\n"
                        ";SIDECAR:REQUEST=1\n"
                        f";SIDECAR:REASON={reason}\n"
                        f"RESPOND PREFIX=\"SC\" MSG=\"BLOCKED {reason}\"\n"
                        "CANCEL_PRINT\n"
                    )
                    stub_local = job_dir / f"SCBLOCK_{base}"
                    stub_local.write_text(stub_txt, encoding="utf-8")
                    stub = upload_file(stub_local, dest_dir, base)
                    print(f"STUB_OK: {stub.get('action')} path={stub.get('item',{}).get('path')}")
                except Exception as e2:
                    print(f"STUB_ERROR: {e2}")
                return
            if auto_start and (time.time() - float(m0)) < float(auto_start_window):
                try:
                    ps, vsd = get_print_state()
                    fn = (ps.get('filename') or '')
                    if fn.endswith(base):
                        proc_path = f"{dest_dir}/{out_name}" if dest_dir else out_name
                        deadline = time.time() + 120
                        while time.time() < deadline:
                            ps2, vsd2 = get_print_state()
                            st2 = (ps2.get('state') or '')
                            active = bool(vsd2.get('is_active'))
                            if st2 not in ('printing','paused') and not active:
                                break
                            time.sleep(1)
                        run_gcode(f'SDCARD_PRINT_FILE FILENAME="{proc_path}"')
                        print(f"AUTO_START_OK: {proc_path}")
                except Exception as e:
                    print(f"AUTO_START_ERROR: {e}")
            if delete_raw and (not firewall):
                try:
                    delete_file(path)
                    print(f"DELETE_OK: {path}")
                except Exception as e:
                    print(f"DELETE_ERROR: {e}")

            if firewall:
                if not block_stub.exists():
                    raise RuntimeError(f"BLOCK_STUB missing: {block_stub}")
                bak = (path[:-6] + f".sidecar_raw.{ts}.gcode") if path.lower().endswith(".gcode") else f"{path}.sidecar_raw.{ts}.gcode"
                mv = move_file(path, bak)
                print(f"MOVE_OK: {mv.get('result',{}).get('item',{}).get('path')}")
                stub = upload_file(block_stub, dest_dir, base)
                print(f"STUB_OK: {stub.get('action')} path={stub.get('item',{}).get('path')}")

        finally:
            if keep_jobs:
                print(f"KEEP_JOBS=1 leaving {job_dir}")
            else:
                shutil.rmtree(job_dir, ignore_errors=True)

    while True:
        try:
            pass_once()
        except Exception as e:
            print(f"LOOP_ERROR: {e}")
        if run_once:
            break
        time.sleep(poll_sec)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
