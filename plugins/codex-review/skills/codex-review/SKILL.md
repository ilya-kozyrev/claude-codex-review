---
name: codex-review
description: Code review (and narrow implementation tasks) by OpenAI Codex CLI, run detached from Claude Code — a reviewer from another vendor, off the Claude limits, with limit checks, live event stream and follow-up rounds. Triggers — Codex review, review with Codex, second opinion on a diff, codex exec, отдай кодексу, ревью Codex'ом.
---

# Codex review from Claude Code

Codex CLI runs as a detached process. Claude keeps working and watches its event stream, then reads
`final.md`. A reviewer from another vendor catches different things than a Claude reviewer, and it
spends your OpenAI plan, not your Claude limits.

Scripts are in `scripts/` inside this skill's base directory (shown when the skill loads):

```bash
scripts/codex-run.sh -C <repo> -b review.md -m gpt-6-sol -e high -s read-only -n mr42    # review
scripts/codex-run.sh -C <repo> -b review.md -m gpt-6-sol -e high -s read-only -n mr42 --delta <sha>  # round 2
scripts/codex-run.sh -C <worktree> -b task.md [-m gpt-6-astra] [-e medium] [-s workspace-write] -n task  # implementation
scripts/codex-run.sh ... --dry-run          # all checks and the final brief, no `codex exec`
python3 scripts/codex-watch.py <run-dir>     # one line per event; run it under Monitor
scripts/codex-status.sh <run-dir>            # alive or not, what it did, git status
python3 scripts/codex-limits.py [--json]     # what is left of the Codex account limits (5-hour and weekly)
```

`codex-run.sh` prints `run: ~/.codex/runs/<name>-<time>`, which holds `brief.md`, `events.jsonl`
(the `--json` stream), `final.md` (the final answer, `-o`), `stderr.log`, `pid` and `meta`.

**It refuses before starting (exit 3; reasons in `codex-run.sh -h`):** effort xhigh/max, too many
live runs, or too little left in the limits. Then use another reviewer. If the limits cannot be read,
that is a warning, not a refusal.

## Steps

1. **Write the brief to a file, complete the first time.** You cannot correct it mid-run, only
   `resume`. A review brief is narrow: the diff range by sha (`git diff <base>..HEAD`), what exactly to
   check, the finding format, a verdict line (see `examples/review-brief.md`). For an implementation
   brief, give the contract (paths to specs and fixtures), what not to touch, the checks to run and
   how to read their exit codes, and the report format. Keep the core to 5–10 files.
2. **Model and effort.** For review use `-m gpt-6-sol -e high -s read-only`. For implementation use a
   `gpt-6-astra`-class model on `-e medium` with a narrow task (the script's default). For probe calls
   use a small model on `-e low`. The script refuses xhigh: once it spent a whole 5-hour window
   without producing `final.md`.
3. **Sandbox.** `workspace-write` cannot commit (`.git/index.lock`) or reach the network, so the
   caller commits and runs network checks. `-s danger-full-access` only in a separate, isolated
   worktree.
4. **Watch, don't wait.** Right after the start, run `Monitor` with
   `python3 scripts/codex-watch.py <run>`: one line per command, edit or message; it exits on
   `turn.completed` or when the process dies (exit 1 means it crashed). After 3–4 minutes of an
   implementation run, run `codex-status.sh`. If it has touched 0 files, the brief is too broad:
   stop it (`kill $(cat <run>/pid)`) and narrow it.
5. **Result: `final.md`, plus the diff in the working tree for implementation.** Codex is a
   colleague, not an authority: verify every finding in the code before acting on it.
6. **Round 2:** after the author's fixes, run the same `-n` with `--delta <sha-before-fixes>`. The
   script appends the previous `final.md` and restricts the review to the fix diff.
7. **Continue the same session:** `echo "…" | codex exec --skip-git-repo-check resume --last 2>/dev/null`.
   Add no flags: they are inherited.

## What to know about `codex exec` (0.153–0.155)

- There is no `--full-auto` (`unexpected argument`). Set effort with `-c model_reasoning_effort="…"`.
- `</dev/null` is required: exec reads stdin and otherwise hangs silently (0 bytes, 0 CPU).
- Without `--json`, stdout gets only the final answer and progress goes to stderr; a dump of skills
  from `~/.codex` at the start is normal. With `--json` the output is JSONL: `thread.started`,
  `item.started`/`item.completed` (`command_execution`, `file_change`, `agent_message`, `reasoning`),
  and `turn.completed` with usage.
