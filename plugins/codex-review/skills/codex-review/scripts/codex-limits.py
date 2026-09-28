#!/usr/bin/env python3
"""codex-limits.py — what is left of the Codex account limits (what the TUI shows on /status).

Starts `codex app-server` over stdio (JSON-RPC, protocol v2), sends `initialize`, then
`account/rateLimits/read`, and prints the windows: primary (usually 5 hours) and secondary
(weekly) — percent used and when it resets. `--json` prints the raw answer.
Needs network access to OpenAI; on error exits non-zero with the error text.
"""
import json, subprocess, sys, time, datetime

raw = "--json" in sys.argv
proc = subprocess.Popen(["codex", "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, text=True, bufsize=1)

def send(id_, method, params):
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": id_, "method": method, "params": params}) + "\n")
    proc.stdin.flush()

def wait_for(id_, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        try: msg = json.loads(line)
        except json.JSONDecodeError: continue
        if msg.get("id") == id_:
            return msg
    raise SystemExit(f"no answer to {id_} within {timeout} s")

try:
    send(1, "initialize", {"clientInfo": {"name": "claude-codex-skill", "version": "1.0"}})
    wait_for(1)
    send(2, "account/rateLimits/read", {})
    resp = wait_for(2)
finally:
    try: proc.terminate()
    except Exception: pass

if "error" in resp:
    print("error:", json.dumps(resp["error"], ensure_ascii=False)); sys.exit(1)
res = resp.get("result", {})
if raw:
    print(json.dumps(res, ensure_ascii=False, indent=1)); sys.exit(0)

def fmt_window(name, w):
    if not w: return f"  {name}: —"
    used = w.get("usedPercent"); mins = w.get("windowDurationMins"); reset = w.get("resetsAt")
    win = f"{mins//60} h" if mins and mins % 60 == 0 else (f"{mins} min" if mins else "?")
    when = datetime.datetime.fromtimestamp(reset).strftime("%d.%m %H:%M") if reset else "?"
    left = ""
    if reset:
        d = max(0, int(reset - time.time())); left = f", in {d//3600} h {d%3600//60} min"
    return f"  {name} (window {win}): used {used} %, left {100-used} %; resets {when}{left}"

buckets = res.get("rateLimitsByLimitId") or {}
if not buckets and res.get("rateLimits"): buckets = {"codex": res["rateLimits"]}
for lid, snap in buckets.items():
    plan = snap.get("planType"); name = snap.get("limitName") or lid
    print(f"{name} (plan {plan}):")
    print(fmt_window("primary  ", snap.get("primary")))
    print(fmt_window("secondary", snap.get("secondary")))
    if snap.get("rateLimitReachedType"): print("  ! limit reached:", snap["rateLimitReachedType"])
    cr = snap.get("credits")
    if cr: print("  credits:", json.dumps(cr, ensure_ascii=False))
if not buckets:
    print("limits snapshot is empty:", json.dumps(res, ensure_ascii=False)[:300])
