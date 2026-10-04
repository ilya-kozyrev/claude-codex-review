# codex-review

**OpenAI Codex CLI as a detached code reviewer for Claude Code.**

**English** · [Русский](README.ru.md)

Claude writes the code, and a reviewer built on a different model catches what a Claude reviewer
misses. Codex CLI runs as a separate process while Claude keeps working. Claude follows its event
stream and takes the result from `final.md`. The review spends your OpenAI subscription, not your
Claude limits.

We have run more than 250 reviews through this skill in three weeks. One example: on a merge request,
Codex found a high-severity path that bypassed a permission check and changed other departments'
data. Two independent Claude reviews of the same brief missed it.

## Install

As a plugin, from this repository used as a marketplace:

```bash
claude plugin marketplace add ilya-kozyrev/claude-codex-review
claude plugin install codex-review@codex-review
```

Inside a Claude Code session, `/plugin marketplace add ilya-kozyrev/claude-codex-review` and
`/plugin install codex-review@codex-review` do the same. The skill is `/codex-review:codex-review`, or
just ask Claude to "send this review to Codex".

By hand, as a plain skill:

```bash
git clone https://github.com/ilya-kozyrev/claude-codex-review
mkdir -p ~/.claude/skills
cp -R claude-codex-review/plugins/codex-review/skills/codex-review ~/.claude/skills/
```

Requirements:
- [Codex CLI](https://github.com/openai/codex), installed with `npm i -g @openai/codex` or
  `brew install codex`, and logged in with `codex login`. Tested on 0.153–0.155.
- `python3`, `git` and `bash`.

## First run: Codex should know what Claude knows

A bare Codex knows nothing about your project. It either reviews blind or spends its limits reading
the docs. `codex-init.py` connects Claude's setup to Codex with symlinks instead of copies:

- global rules: `~/.codex/AGENTS.md` points to `~/.claude/CLAUDE.md`;
- each repository's `CLAUDE.md`, through `project_doc_fallback_filenames` in `~/.codex/config.toml`;
- `project_doc_max_bytes` is raised so the rules fit. The default is 32 KiB, and Codex silently cuts
  longer rules. Our global and project rules together are 57 KB;
- Claude's per-project memory (`~/.claude/projects`), through a link and `developer_instructions`;
- Claude's skills, your own and those of enabled plugins, as links in `~/.agents/skills`;
- project skills: `<repo>/.agents/skills` points to `.claude/skills`, hidden from git through
  `.git/info/exclude`.

```bash
python3 ~/.claude/skills/codex-review/scripts/codex-init.py --repo ~/code/myrepo
```

The command backs up `config.toml` first and leaves anything it did not create alone: your own
`AGENTS.md`, your own skill folders, keys you already set. Run it again after you install or update
Claude plugins, so the skill links keep pointing at live folders. `codex-run.sh` calls it before
every run as a precondition. It sets up the repository part itself. If the global part is missing,
it refuses and prints the exact command to run. `--check` only reports what is missing.

## Usage

```bash
S=~/.claude/skills/codex-review/scripts        # for the plugin, it lives under ~/.claude/plugins/cache/…
$S/codex-run.sh -C ~/code/myrepo -b review.md -m sol -e high -s read-only -n mr42
python3 $S/codex-watch.py ~/.codex/runs/mr42-<time>   # one line per event; in Claude Code, run it under Monitor
cat ~/.codex/runs/mr42-<time>/final.md

# round two, after the author's fixes: only the fix diff, plus the previous findings
$S/codex-run.sh -C ~/code/myrepo -b review.md -m sol -e high -s read-only -n mr42 --delta <sha-before-fixes>

python3 $S/codex-limits.py                     # what is left in the 5-hour and weekly windows
```

Write the brief like
[`examples/review-brief.md`](plugins/codex-review/skills/codex-review/examples/review-brief.md): a
narrow diff by sha, exactly what to check, the author's test results (a read-only review cannot
rerun them), the finding format and a verdict line. A read-only review cannot write files, so it
comes back as the final answer, `final.md`.

## What the script does

- **Picks the model by family.** `-m sol|astra|luna` (any case) resolves to the newest listed model
  of that family in the Codex CLI's catalog cache (`$CODEX_HOME/models_cache.json`, default
  `~/.codex`), so nothing here goes stale on the next release. A full id (`-m gpt-…`) passes through
  unchanged. The default is `sol`: effort `medium` for implementation, `high` for a read-only review.
  `astra` is opt-in, for work whose judgement needs justify it. If the catalog is missing or has no
  model of the family, the script refuses (exit 3) and asks for a full id. The resolved id is printed
  at the start and written to `meta` (`model=`, `model_family=`).
- **Checks the limits before it starts.** A review (`-s read-only`) needs at least 5% left in
  Codex's 5-hour window, an implementation task at least 30%, and both need at least 5% of the weekly
  window. Otherwise the script refuses with exit code 3, so a run does not die halfway. Change the
  threshold with `CODEX_MIN_LEFT`.
- **Runs at most two Codex processes at once** (`CODEX_MAX_RUNS`).
- **Refuses effort xhigh/max.** For us, xhigh once burned the whole 5-hour window and produced no
  `final.md`. Override with `CODEX_ALLOW_XHIGH=1`.
- **`--delta <sha>`**: the second round looks only at the fix diff and gets the previous findings
  from the last run's `final.md` with the same `-n`.
- **`--dry-run`**: all the checks and the final brief, without starting Codex.
- **Run files** live in `~/.codex/runs/<name>-<time>/`: `brief.md`, `events.jsonl`, `final.md`,
  `stderr.log`, `pid` and `meta`.

## `codex exec` pitfalls the script already handles

- `codex exec` has no `--full-auto`. Set effort with `-c model_reasoning_effort="…"`.
- Without `</dev/null`, exec hangs silently waiting for stdin.
- Without `--json`, stdout gets only the final answer and the progress goes to stderr.
- The `workspace-write` sandbox cannot commit or reach the network, so the caller commits.

## When Codex runs out of limits

Fall back to a Claude review. Until November 5, 2026 you can run it for free in a cloud session on
the cloud credit: [claude-cloud-review](https://github.com/ilya-kozyrev/claude-cloud-review).

## License

MIT
