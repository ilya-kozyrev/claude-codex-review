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
scripts/codex-run.sh -C <repo> -b review.md -m sol -e high -s read-only -n mr42    # review
scripts/codex-run.sh -C <repo> -b review.md -m sol -e high -s read-only -n mr42 --delta <sha>  # round 2
scripts/codex-run.sh -C <worktree> -b task.md [-m sol] [-e medium] [-s workspace-write] -n task  # implementation
scripts/codex-run.sh ... --dry-run          # all checks and the final brief, no `codex exec`
python3 scripts/codex-watch.py <run-dir>     # one line per event; run it under Monitor
scripts/codex-status.sh <run-dir>            # alive or not, what it did, git status
python3 scripts/codex-limits.py [--json]     # what is left of the Codex account limits (5-hour and weekly)
```

`codex-run.sh` prints `run: ~/.codex/runs/<name>-<time>` and the resolved `model:`; the run directory
holds `brief.md`, `events.jsonl` (the `--json` stream), `final.md` (the final answer, `-o`),
`stderr.log`, `pid` and `meta` (`model=` the resolved id, `model_family=` the alias you passed).

**Models are chosen by family, not by versioned id.** `-m sol|astra|luna` (any case) resolves to the
newest listed model of that family in the Codex CLI's catalog cache, `$CODEX_HOME/models_cache.json`
(default `~/.codex`; only entries with `visibility: "list"`, the highest version in the slug wins,
ties go to the lower `priority`). A full id passes through unchanged (`-m gpt-6-sol`, to pin one).
So the skill does not go stale when a new model ships. If the catalog is missing or lists no model
of that family, the script refuses (exit 3): pass a full id.

**It refuses before starting (exit 3; reasons in `codex-run.sh -h`):** Codex cannot see Claude's
setup, the model family cannot be resolved, effort is xhigh/max, too many runs are live, or too
little is left in the limits. If the
limits cannot be read, that is a warning, not a refusal. In the other cases use another reviewer.

## Codex sees what Claude sees: `codex-init.py`

A bare Codex knows nothing about the project, so it either reviews blind or spends its budget
reading docs. `codex-init.py` links Claude's configuration into Codex instead of copying it:

- `~/.codex/AGENTS.md` → `~/.claude/CLAUDE.md`, for the global rules;
- `project_doc_fallback_filenames = ["CLAUDE.md"]`, so Codex reads a repo's `CLAUDE.md` wherever
  the repo has no `AGENTS.md`;
- `project_doc_max_bytes` raised so the rules fit. The 32 KiB default truncates longer rules
  silently;
- `~/.codex/claude-projects` → `~/.claude/projects` plus `developer_instructions`, so Codex reads
  the project's Claude memory index;
- `~/.agents/skills/<name>` → every skill in `~/.claude/skills` and in the enabled Claude plugins;
- per repo, `<repo>/.agents/skills` → `.claude/skills`, hidden from git through `.git/info/exclude`.

Run it once: `python3 scripts/codex-init.py --repo <repo>`. It backs up `config.toml` first and
never overwrites anything it did not create. Run it again after installing or updating Claude
plugins, so the skill links follow. `codex-run.sh` calls it as a precondition
(`--preflight <dir>`): the repo part is linked on every run, and the global part is only checked.
If the global part is missing, `codex-run.sh` refuses and prints the exact command.
`codex-init.py --check [--repo DIR]` reports without changing anything.

## Steps

1. **Write the brief to a file, complete the first time.** You cannot correct it mid-run, only
   `resume`. A review brief is narrow: the diff range by sha (`git diff <base>..HEAD`), what exactly to
   check, the author's test results, the finding format, a verdict line (see
   `examples/review-brief.md`). For an implementation
   brief, give the contract (paths to specs and fixtures), what not to touch, the checks to run and
   how to read their exit codes, and the report format. Keep the core to 5–10 files.
2. **Model and effort.** Ordinary review and implementation run on `sol` (the script's default):
   review `-m sol -e high -s read-only`, implementation `-m sol -e medium` with a narrow task.
   `astra` is opt-in (`-m astra`), for work whose judgement needs justify it: architecture
   trade-offs, a spec with gaps, contested findings, hard diagnosis. State the reason before
   launching it. `luna` on `-e low` is for probe calls: search, log extraction, a check with an
   unambiguous answer. The script refuses xhigh: once it spent a whole 5-hour window without
   producing `final.md`.
3. **Sandbox.** `workspace-write` cannot commit (`.git/index.lock`) or reach the network, so the
   caller commits and runs network checks. `-s danger-full-access` only in a separate, isolated
   worktree. A `read-only` review cannot write files or create temp dirs either: it comes back as
   the final answer (`final.md`), and the review brief carries the author's test results instead of
   asking the reviewer to rerun them.
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
