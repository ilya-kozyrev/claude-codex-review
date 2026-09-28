#!/usr/bin/env python3
"""codex-watch.py <run-dir> — follow a Codex run's events.jsonl line by line while it runs.

One line per event worth attention:
  $ <command> → exit N        a command_execution finished
  ✎ add|update|delete <path>  a file_change (path relative to the working directory)
  💬 <text>                    an agent_message (first 240 characters)
  ■ done …                     turn.completed — exits 0
  ■ process ended without turn.completed — exits 1 (crashed or killed)
Reasoning is not printed: it is noise for a watcher.
Made for a line-based watcher (Claude Code Monitor): each line is an event, exit = end of watch.
"""
import json, os, sys, time

run = sys.argv[1] if len(sys.argv) > 1 else None
if not run or not os.path.isdir(run):
    print(__doc__); sys.exit(2)
events = os.path.join(run, "events.jsonl")
meta = {}
try:
    for line in open(os.path.join(run, "meta")):
        k, _, v = line.strip().partition("="); meta[k] = v
except FileNotFoundError:
    pass
root = meta.get("dir", "")
pid = None
try: pid = int(open(os.path.join(run, "pid")).read().strip())
except Exception: pass

def alive():
    if pid is None: return True
    try: os.kill(pid, 0); return True
    except OSError: return False

def rel(p):
    return os.path.relpath(p, root) if root and p.startswith(root) else p

def show(e):
    t = e.get("type")
    if t == "thread.started":
        print(f"▶ thread {e.get('thread_id')}  ({meta.get('model','?')} / {meta.get('effort','?')})")
    elif t == "item.completed":
        it = e.get("item", {}); k = it.get("type")
        if k == "command_execution":
            cmd = it.get("command", "").replace("/bin/zsh -lc ", "").strip("'")
            print(f"$ {cmd[:160]} → exit {it.get('exit_code')}")
        elif k == "file_change":
            for ch in it.get("changes", []):
                print(f"✎ {ch.get('kind')} {rel(ch.get('path',''))}")
        elif k == "agent_message":
            txt = (it.get("text") or "").replace("\n", " ")
            print(f"💬 {txt[:240]}")
    elif t == "turn.completed":
        u = e.get("usage", {})
        print(f"■ done: in={u.get('input_tokens')} cached={u.get('cached_input_tokens')} out={u.get('output_tokens')} reasoning={u.get('reasoning_output_tokens')}")
        return "done"
    elif t and "error" in t:
        print(f"✖ {json.dumps(e, ensure_ascii=False)[:300]}")
    return None

sys.stdout.reconfigure(line_buffering=True)
pos = 0; buf = ""
while True:
    try:
        with open(events, encoding="utf-8", errors="replace") as f:
            f.seek(pos); chunk = f.read(); pos = f.tell()
    except FileNotFoundError:
        chunk = ""
    buf += chunk
    while "\n" in buf:
        line, buf = buf.split("\n", 1)
        line = line.strip()
        if not line: continue
        try: e = json.loads(line)
        except json.JSONDecodeError: continue
        if show(e) == "done":
            sys.exit(0)
    if not alive():
        # the tail was already read above
        print("■ process ended without turn.completed — see stderr.log")
        sys.exit(1)
    time.sleep(2)
