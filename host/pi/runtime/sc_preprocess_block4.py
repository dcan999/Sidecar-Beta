#!/usr/bin/env python3
"""
Preprocess (block-of-4 tool numbering + docked-prep EVs)

Virtual tool numbering:
  head = T // 4   (0..3)
  lane = (T % 4) + 1   (1..4)

Behavior:
- Keep T numbers as-is (native extruder_map routes pickup/temps/fans)
- Emit EV=UNLOAD/EV=LOAD for the *docked* head (after a tool switch), not the active one
- No src=sidecar (sc_gate ignores that)
- Hard block T16+
"""
from __future__ import annotations
import argparse, os, time, re
from typing import List, Tuple, Optional

LOAD_TO_NOZZLE_MM = float(os.getenv("SIDECAR_LOAD_TO_NOZZLE_MM", "70"))
MIN_PRIME_MM = float(os.getenv("SIDECAR_MIN_PRIME_MM", "10"))

TOOL_RE = re.compile(r'^(\s*)T(\d+)\b')
COOLDOWN_RE = re.compile(r'^(?P<indent>\s*)M104\s+(?:(?:T(?P<t1>\d+)\s+S(?P<s1>\d+))|(?:S(?P<s2>\d+)\s+T(?P<t2>\d+)))(?P<rest>.*)$', re.IGNORECASE)

SIDECAR_COOLDOWN_FROM_C = int(os.getenv("SIDECAR_COOLDOWN_FROM_C", "70"))
SIDECAR_STANDBY_C = int(os.getenv("SIDECAR_STANDBY_C", "140"))

def hl(tool: int) -> Tuple[int,int]:
    if tool >= 16:
        raise ValueError(f"tool T{tool} is not supported yet (max is T15)")
    head = tool // 4
    lane = (tool % 4) + 1
    return head, lane

def sc(msg: str, indent: str = "") -> str:
    return f'{indent}RESPOND PREFIX="SC" MSG="{msg}"\n'

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--purge-len", type=float, default=80.0)
    ap.add_argument("--lanes-per-sc", type=int, default=4)
    ap.add_argument("--sc-heads", default="0,1,2,3")
    args = ap.parse_args()

    if args.lanes_per_sc != 4:
        ap.error("block-of-four tool mapping requires --lanes-per-sc=4")
    try:
        sc_heads = [int(value.strip()) for value in args.sc_heads.split(",")]
    except ValueError:
        ap.error("--sc-heads must be a comma-separated list of head indices 0..3")
    if not sc_heads or len(set(sc_heads)) != len(sc_heads) or any(h not in range(4) for h in sc_heads):
        ap.error("--sc-heads must contain unique head indices 0..3")
    enabled_heads = set(sc_heads)

    with open(args.input, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    tool_pos: List[Tuple[int,int,str]] = []
    for i, line in enumerate(lines):
        m = TOOL_RE.match(line)
        if m:
            t = int(m.group(2))
            _ = hl(t)
            tool_pos.append((i, t, m.group(1)))

    next_tool_same_head: List[Optional[int]] = [None]*len(tool_pos)
    next_idx_by_head = {0: None, 1: None, 2: None, 3: None}
    for k in range(len(tool_pos)-1, -1, -1):
        _, t, _ = tool_pos[k]
        h, _lane = hl(t)
        nxt = next_idx_by_head[h]
        next_tool_same_head[k] = tool_pos[nxt][1] if nxt is not None else None
        next_idx_by_head[h] = k

    out: List[str] = []

    if not any(l.startswith(";SIDECAR:PROCESSED=1") for l in lines[:30]):
        out.append(";SIDECAR:PROCESSED=1\n")
        out.append(";SIDECAR:NATIVE_MAP=1\n")
        out.append(";SIDECAR:TOOLMAP=block4\n")
        out.append(f";SIDECAR:JOB_ID=SC_{int(time.time())}\n")
        out.append(f";SIDECAR:SOURCE={os.path.basename(args.input)}\n")

    pos_to_k = {i:k for k,(i,_,_) in enumerate(tool_pos)}

    last_tool: Optional[int] = None
    last_k: Optional[int] = None

    for i, line in enumerate(lines):
        cd = COOLDOWN_RE.match(line)
        if cd:
            rest = cd.group('rest') or ''
            tool_s = cd.group('t1') or cd.group('t2')
            temp_s = cd.group('s1') or cd.group('s2')
            if ('cooldown' in rest.lower() and tool_s is not None
                    and temp_s is not None
                    and int(temp_s) == SIDECAR_COOLDOWN_FROM_C):
                tool = int(tool_s)
                if 0 <= tool <= 15 and hl(tool)[0] in enabled_heads:
                    h_cd, lane_cd = hl(tool)
                    for _j, _t, _indent in tool_pos:
                        if _j <= i:
                            continue
                        h2, lane2 = hl(_t)
                        if h2 == h_cd and lane2 != lane_cd:
                            line = ""
                            break

        out.append(line)

        m = TOOL_RE.match(line)
        if not m:
            continue

        k = pos_to_k.get(i)
        if k is None:
            continue

        t = tool_pos[k][1]
        indent = tool_pos[k][2]

        if last_tool is not None and last_k is not None:
            h_prev, lane_prev = hl(last_tool)
            h_now, _lane_now = hl(t)

            if h_prev != h_now:
                t_next = next_tool_same_head[last_k]
                if h_prev in enabled_heads and t_next is not None:
                    h_next, lane_next = hl(t_next)
                    if h_next == h_prev and lane_next != lane_prev:
                        prime = args.purge_len if args.purge_len > MIN_PRIME_MM else MIN_PRIME_MM
                        go_dist = prime
                        out.append(sc(f"EV=UNLOAD head={h_prev} lane={lane_prev} from=T{last_tool} to=T{t} src=gcode", indent))
                        out.append(sc(f"EV=LOAD head={h_prev} lane={lane_next} go_dist={go_dist:g} v=2.0 a=0.0 src=gcode", indent))

        last_tool = t
        last_k = k

    outp = os.path.join(os.path.dirname(args.input), f"SCPRO_{os.path.basename(args.input)}")
    with open(outp, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(out)

    print("OK", outp)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
