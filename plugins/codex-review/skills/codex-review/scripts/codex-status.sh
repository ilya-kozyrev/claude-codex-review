#!/usr/bin/env bash
# codex-status.sh <run-dir> — is the run alive, since when, what it did, what git status shows.
set -u
RUN="${1:?run-dir}"; cd "$RUN" || exit 2
DIR=$(sed -n 's/^dir=//p' meta); PID=$(cat pid 2>/dev/null)
if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then ST="running"; else ST="finished"; fi
echo "run:      $RUN"
echo "state:    $ST (pid $PID), started $(sed -n 's/^started=//p' meta), model $(sed -n 's/^model=//p' meta)/$(sed -n 's/^effort=//p' meta)"
python3 - "$RUN" <<'PY'
import json,sys,os
run=sys.argv[1]; c={"cmd":0,"files":set(),"msgs":0,"done":False}
try:
    for line in open(os.path.join(run,"events.jsonl")):
        try: e=json.loads(line)
        except Exception: continue
        if e.get("type")=="item.completed":
            it=e["item"]; k=it.get("type")
            if k=="command_execution": c["cmd"]+=1
            elif k=="file_change": c["files"].update(ch["path"] for ch in it.get("changes",[]))
            elif k=="agent_message": c["msgs"]+=1
        elif e.get("type")=="turn.completed": c["done"]=True
except FileNotFoundError: pass
print(f"events:   commands {c['cmd']}, files touched {len(c['files'])}, messages {c['msgs']}, turn.completed={c['done']}")
PY
[ -s final.md ] && { echo "final.md: $(wc -c < final.md) bytes"; } || echo "final.md: empty so far"
if [ -n "$DIR" ] && git -C "$DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then echo "git ($DIR):"; git -C "$DIR" status --short | head -15; else echo "git:      $DIR — not a git repository"; fi
