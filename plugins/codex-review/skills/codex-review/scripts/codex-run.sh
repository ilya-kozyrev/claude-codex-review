#!/usr/bin/env bash
# codex-run.sh — run Codex CLI detached, streaming its events to a file.
#
#   codex-run.sh -C <dir> -b <brief.md> [-m model] [-e effort] [-s sandbox] [-n name]
#                [--delta <sha>] [--dry-run]
#
# -m  a model family (sol | astra | luna, any case) or a full id (gpt-…, passed through as is).
#     A family resolves to the newest model of that family in the Codex CLI's catalog cache
#     ($CODEX_HOME/models_cache.json, default ~/.codex): only entries with visibility "list",
#     the highest version in the slug (gpt-<major>[.<minor>]-<family>) wins, ties go to the lower
#     priority number. No catalog, or no model of that family: refuse (exit 3), pass a full id.
#     Default sol (CODEX_MODEL overrides); astra only for work whose judgement needs justify it.
# -e  default high for a read-only review, medium otherwise.
#
# Creates the run directory ~/.codex/runs/<name>-<time>/ with a copy of the brief and writes:
#   events.jsonl — the `--json` event stream (commands, file changes, messages, usage)
#   final.md     — the model's final answer (`-o`)
#   stderr.log   — human-readable progress (a dump of skills at the start is normal)
#   pid, meta    — for codex-watch.py / codex-status.sh
# Prints the run directory and ready-to-use watch commands.
#
# Refuses before starting (exit 3):
#   - Codex does not see Claude's setup: codex-init.py --preflight fails (run codex-init.py once;
#     CODEX_SKIP_INIT=1 skips the check). Its repo part runs every time: <repo>/.agents/skills;
#   - effort xhigh/max (it burned a whole 5-hour window without a final.md for us);
#     override with CODEX_ALLOW_XHIGH=1;
#   - CODEX_MAX_RUNS (default 2) runs already alive, by the pid files in the runs directory;
#   - 5-hour window left below the threshold: review (sandbox read-only) 5 %, anything else 30 %
#     (override: CODEX_MIN_LEFT=N); weekly window below 5 % refuses too.
#     If codex-limits.py cannot read the limits, that is a warning, not a refusal.
# --delta <sha>  a follow-up review round: appends "look only at git diff <sha>..HEAD" and the
#                previous findings — final.md of the latest run with the same -n (else the same -C).
# --dry-run      everything up to `codex exec`: checks, the final brief and the command are printed;
#                no run directory, no Codex usage (reading the limits is free).
# Test overrides: CODEX_RUNS_DIR (runs directory), CODEX_LIMITS_JSON (a file instead of
# calling codex-limits.py --json).
#
# Why this shape: without `--json` stdout gets only the final answer and progress goes to stderr;
# `</dev/null` is required — exec reads stdin and otherwise hangs silently; `codex exec` has no
# `--full-auto`. Checked on codex-cli 0.153–0.155.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
RUNS="${CODEX_RUNS_DIR:-$HOME/.codex/runs}"
MAX_RUNS="${CODEX_MAX_RUNS:-2}"
MODEL="${CODEX_MODEL:-sol}"; EFFORT=""; SANDBOX="workspace-write"; NAME="run"; DIR=""; BRIEF=""
DELTA=""; DRY=0

# long options -> short, getopts in bash 3.2 has no long options
ARGS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --delta) [ $# -ge 2 ] || { echo "--delta needs <sha>" >&2; exit 2; }; DELTA="$2"; shift 2 ;;
    --delta=*) DELTA="${1#--delta=}"; shift ;;
    --dry-run) DRY=1; shift ;;
    *) ARGS="$ARGS$(printf '%q' "$1") "; shift ;;
  esac
done
eval "set -- $ARGS"

while getopts "C:b:m:e:s:n:h" opt; do
  case "$opt" in
    C) DIR="$OPTARG" ;; b) BRIEF="$OPTARG" ;; m) MODEL="$OPTARG" ;; e) EFFORT="$OPTARG" ;;
    s) SANDBOX="$OPTARG" ;; n) NAME="$OPTARG" ;;
    h|*) sed -n 2,30p "$0"; exit 2 ;;
  esac
done
[ -n "$DIR" ] && [ -d "$DIR" ] || { echo "need -C <existing directory>" >&2; exit 2; }
[ -n "$BRIEF" ] && [ -f "$BRIEF" ] || { echo "need -b <brief file>" >&2; exit 2; }
command -v codex >/dev/null || { echo "codex is not on PATH (install: npm i -g @openai/codex or brew install codex)" >&2; exit 2; }
DIR="$(cd "$DIR" && pwd)"

refuse() { echo "REFUSED: $*" >&2; exit 3; }
lc() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

# 0. model: a family alias -> the newest listed id of that family, a full id passes through
[ -n "$EFFORT" ] || case "$SANDBOX" in read-only) EFFORT="high" ;; *) EFFORT="medium" ;; esac
MODEL_FAMILY=""
case "$(lc "$MODEL")" in
  gpt-*) ;;
  *)
    MODEL_FAMILY="$(lc "$MODEL")"
    MODEL="$(python3 "$HERE/codex-model.py" "$MODEL_FAMILY" "${CODEX_HOME:-$HOME/.codex}/models_cache.json")" \
      || refuse "cannot resolve model family '$MODEL_FAMILY' (see above). Pass a full id, e.g. -m gpt-<version>-<family>."
    ;;
esac

# 1. no xhigh
case "$(lc "$EFFORT")" in
  *xhigh*|max) [ "${CODEX_ALLOW_XHIGH:-0}" = 1 ] \
    || refuse "effort=$EFFORT: review with -m sol -e high, implementation with -m sol -e medium; astra only for judgement work (CODEX_ALLOW_XHIGH=1 to override)." ;;
esac

# 2. at most MAX_RUNS live runs; alive = kill -0 on the pid file and the process is codex (pids get reused)
ALIVE=0; ALIVE_LIST=""
if [ -d "$RUNS" ]; then
  for pf in "$RUNS"/*/pid; do
    [ -f "$pf" ] || continue
    p="$(tr -dc '0-9' < "$pf")"
    [ -n "$p" ] || continue
    kill -0 "$p" 2>/dev/null || continue
    c="$(ps -p "$p" -o comm= 2>/dev/null)"; [ "$(basename "$c" 2>/dev/null)" = codex ] || continue
    ALIVE=$((ALIVE + 1)); ALIVE_LIST="$ALIVE_LIST $(basename "$(dirname "$pf")")(pid $p)"
  done
fi
[ "$ALIVE" -lt "$MAX_RUNS" ] || refuse "$ALIVE Codex runs already alive (limit $MAX_RUNS):$ALIVE_LIST. Wait for one (codex-status.sh) or use another reviewer."

# 3. Codex sees Claude's rules, memory and skills: the repo part is linked here, the global part
#    only checked (codex-init.py sets it up once). --dry-run changes nothing.
if [ "${CODEX_SKIP_INIT:-0}" != 1 ]; then
  PF=""; [ "$DRY" -eq 1 ] && PF="--check"
  python3 "$HERE/codex-init.py" --preflight "$DIR" --quiet $PF >&2 \
    || refuse "Codex would start without the project's rules. Run the command above once (CODEX_SKIP_INIT=1 to skip)."
fi

# 4. limits
case "$SANDBOX" in read-only) MODE="review"; DEF_MIN=5 ;; *) MODE="implementation"; DEF_MIN=30 ;; esac
MIN_LEFT="${CODEX_MIN_LEFT:-$DEF_MIN}"
if [ -n "${CODEX_LIMITS_JSON:-}" ]; then LIMJSON="$(cat "$CODEX_LIMITS_JSON")"; LIMRC=$?
else LIMJSON="$(python3 "$HERE/codex-limits.py" --json 2>&1)" && LIMRC=0 || LIMRC=$?; fi
if [ "$LIMRC" -ne 0 ]; then
  echo "WARNING: limits not read (codex-limits.py exit=$LIMRC): $(printf '%s' "$LIMJSON" | head -c 200). Skipping the limits check." >&2
else
  VERDICT="$(printf '%s' "$LIMJSON" | python3 -c '
import json, sys
min_left = float(sys.argv[1])
try:
    res = json.load(sys.stdin)
except ValueError:
    print("warn|limits answer is not JSON"); sys.exit()
b = res.get("rateLimitsByLimitId") or {}
if not b and res.get("rateLimits"): b = {"codex": res["rateLimits"]}
if not b: print("warn|limits snapshot is empty"); sys.exit()
out, bad = [], []
for lid, s in b.items():
    p = (s.get("primary") or {}).get("usedPercent"); w = (s.get("secondary") or {}).get("usedPercent")
    pl = None if p is None else 100 - p; wl = None if w is None else 100 - w
    out.append(f"{lid}: 5h left {pl} %, week left {wl} %")
    rt = s.get("rateLimitReachedType")
    if rt: bad.append(f"{lid}: limit reached ({rt})")
    if pl is not None and pl < min_left: bad.append(f"{lid}: 5h left {pl} % < {min_left:g} %")
    if wl is not None and wl < 5: bad.append(f"{lid}: week left {wl} % < 5 %")
print(("bad|" + "; ".join(bad)) if bad else ("ok|" + "; ".join(out)))
' "$MIN_LEFT")"
  case "$VERDICT" in
    bad*) refuse "Codex limits ($MODE, 5-hour threshold $MIN_LEFT %): ${VERDICT#bad|}. Use another reviewer." ;;
    ok*)  echo "limits: ${VERDICT#ok|} ($MODE threshold $MIN_LEFT %)" ;;
    *)    echo "WARNING: ${VERDICT#warn|}; skipping the limits check." >&2 ;;
  esac
fi

# 5. final brief (+ delta)
STAGE="$(mktemp "${TMPDIR:-/tmp}/codex-brief.XXXXXX")"
trap 'rm -f "$STAGE"' EXIT
cp "$BRIEF" "$STAGE"
if [ -n "$DELTA" ]; then
  git -C "$DIR" rev-parse --verify -q "${DELTA}^{commit}" >/dev/null \
    || { echo "--delta: $DELTA is not a commit in $DIR" >&2; exit 2; }
  FULL="$(git -C "$DIR" rev-parse "${DELTA}^{commit}")"
  PREV=""
  # the latest run with the same name, then with the same directory; only a non-empty final.md
  for d in $(ls -1dt "$RUNS/${NAME}"-* 2>/dev/null); do [ -s "$d/final.md" ] && { PREV="$d/final.md"; break; }; done
  if [ -z "$PREV" ]; then
    for d in $(ls -1dt "$RUNS"/*/ 2>/dev/null); do
      d="${d%/}"; [ -s "$d/final.md" ] && [ -f "$d/meta" ] || continue
      [ "$(sed -n 's/^dir=//p' "$d/meta")" = "$DIR" ] && { PREV="$d/final.md"; break; }
    done
  fi
  {
    printf '\n\n## Follow-up review round (delta)\n\n'
    printf 'Look only at `git diff %s..HEAD` in %s: it is the author'"'"'s answer to the previous findings. ' "$FULL" "$DIR"
    printf 'Do not re-review code outside this diff. For each previous finding: closed / not closed / partly closed; plus new findings introduced by the diff itself.\n\n'
    if [ -n "$PREV" ]; then
      printf 'Previous findings (%s):\n\n' "$PREV"
      printf -- '---8<---\n'; head -c 60000 "$PREV"; printf '\n---8<---\n'
    else
      printf 'Previous findings: the previous round'"'"'s file was not found; reconstruct them from the commit messages of the diff.\n'
    fi
  } >> "$STAGE"
  echo "delta:  git diff ${FULL:0:12}..HEAD; previous findings: ${PREV:-not found}"
fi

if [ "$DRY" -eq 1 ]; then
  echo "DRY-RUN: would start. model $MODEL${MODEL_FAMILY:+ (family $MODEL_FAMILY)}/$EFFORT, sandbox $SANDBOX, -C $DIR, live runs $ALIVE/$MAX_RUNS"
  echo "command: codex exec --skip-git-repo-check -m $MODEL -c model_reasoning_effort=\"$EFFORT\" --sandbox $SANDBOX -C $DIR --json -o <run>/final.md <brief $(wc -c < "$STAGE" | tr -d ' ') bytes>"
  echo "brief tail:"; tail -n 8 "$STAGE"
  exit 0
fi

RUN="$RUNS/${NAME}-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RUN"
cp "$STAGE" "$RUN/brief.md"
printf 'dir=%s\nmodel=%s\nmodel_family=%s\neffort=%s\nsandbox=%s\ndelta=%s\nstarted=%s\n' "$DIR" "$MODEL" "$MODEL_FAMILY" "$EFFORT" "$SANDBOX" "$DELTA" "$(date -u +%FT%TZ)" > "$RUN/meta"

nohup codex exec --skip-git-repo-check -m "$MODEL" -c "model_reasoning_effort=\"$EFFORT\"" \
  --sandbox "$SANDBOX" -C "$DIR" --json -o "$RUN/final.md" "$(cat "$RUN/brief.md")" \
  </dev/null > "$RUN/events.jsonl" 2> "$RUN/stderr.log" &
echo $! > "$RUN/pid"

echo "run:    $RUN"
echo "model:  $MODEL${MODEL_FAMILY:+ (family $MODEL_FAMILY)}, effort $EFFORT"
echo "pid:    $(cat "$RUN/pid")"
echo "watch:  python3 $HERE/codex-watch.py $RUN      # one line per event; run it under a watcher"
echo "status: $HERE/codex-status.sh $RUN"
