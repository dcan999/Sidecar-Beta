#!/usr/bin/env python3
import os, json, urllib.request, urllib.error
from urllib.parse import quote

MOONRAKER = os.getenv("MOONRAKER_URL", "http://10.42.0.10:7125").rstrip("/")
SCAN_BYTES = int(os.getenv("SCAN_BYTES", "8192"))

MARK_REQ = b"SIDECAR:REQUEST=1"
MARK_PRO = b"SIDECAR:PROCESSED=1"

def http_get_json(url: str, timeout: float = 10.0):
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))

def http_get_range(url: str, nbytes: int, timeout: float = 10.0) -> bytes:
    req = urllib.request.Request(url, method="GET")
    req.add_header("Range", f"bytes=0-{nbytes-1}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def main():
    j = http_get_json(f"{MOONRAKER}/server/files/list?root=gcodes")
    files = j.get("result", [])
    print(f"Moonraker={MOONRAKER}")
    print(f"files={len(files)} scan_bytes={SCAN_BYTES}")

    candidates = []
    for it in files:
        path = it.get("path", "")
        if not path:
            continue
        base = os.path.basename(path)

        if base.startswith("SCPRO_"):
            continue
        if ".sidecar_raw" in base:
            continue
        if base.startswith("SCBLOCK_") or base.startswith("SCFAIL_"):
            continue

        url = f"{MOONRAKER}/server/files/gcodes/{quote(path, safe='/')}"
        try:
            head = http_get_range(url, SCAN_BYTES)
        except Exception as e:
            print(f"WARN: fetch failed: {path}: {e}")
            continue

        has_req = (MARK_REQ in head)
        has_pro = (MARK_PRO in head)

        if has_req and not has_pro:
            candidates.append((path, it.get("size"), it.get("modified")))

    if not candidates:
        print("candidates=0")
        return

    print(f"candidates={len(candidates)}")
    for (p, sz, mod) in sorted(candidates):
        print(f"  - {p}  size={sz}  modified={mod}")

if __name__ == "__main__":
    main()
