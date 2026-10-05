#!/usr/bin/env python3
"""Read-only check that the stock U1 integration has the gate's commands."""
import json
import os
from pathlib import Path
import time
import urllib.request


U1 = os.getenv("U1_MOONRAKER", "http://10.42.0.10:7125").rstrip("/")
OUT = Path(os.getenv("OUT_JSON", "/home/sidecar/sidecar/preprocess/health/u1_commands.json"))
COMMANDS = ("SC_BG_BUSY", "SC_BG_LOAD", "SC_BG_UNLOAD")


def get_json(url, timeout=5.0):
    headers = {}
    api_key = os.getenv("MOONRAKER_API_KEY")
    bearer = os.getenv("MOONRAKER_BEARER_TOKEN")
    if api_key:
        headers["X-Api-Key"] = api_key
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    req = urllib.request.Request(url, method="GET", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = json.load(response)
    if not isinstance(data, dict) or data.get("error"):
        raise ValueError("Moonraker query failed: %s" % data)
    return data


def main():
    status = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "u1": U1,
        "klippy_connected": False,
        "klippy_state": None,
        "print_state": None,
        "missing_commands": list(COMMANDS),
        "ok": False,
        "error": None,
    }
    try:
        info = get_json(U1 + "/server/info").get("result", {})
        status["klippy_connected"] = bool(info.get("klippy_connected"))
        status["klippy_state"] = info.get("klippy_state")
        query = get_json(U1 + "/printer/objects/query?print_stats")
        status["print_state"] = (query.get("result", {})
                                 .get("status", {}).get("print_stats", {})
                                 .get("state"))
        help_result = get_json(U1 + "/printer/gcode/help").get("result", {})
        if not isinstance(help_result, dict):
            raise ValueError("Unexpected G-code help response")
        status["missing_commands"] = [name for name in COMMANDS
                                      if name not in help_result]
        status["ok"] = (status["klippy_connected"]
                        and status["klippy_state"] == "ready"
                        and not status["missing_commands"])
    except Exception as e:
        status["error"] = str(e)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    print("U1_COMMANDS:", "OK" if status["ok"] else "FAIL")
    return 0 if status["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
