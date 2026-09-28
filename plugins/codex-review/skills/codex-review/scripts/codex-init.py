#!/usr/bin/env python3
"""codex-init.py — let Codex CLI see what Claude Code sees: rules, memory and skills.

A bare `codex exec` knows nothing about the project, so it either reviews blind or spends its
budget reading docs. This links Claude's configuration into Codex instead of copying it:

  global (once, edits your Codex home):
    ~/.codex/AGENTS.md          -> ~/.claude/CLAUDE.md          global rules
    ~/.codex/claude-projects    -> ~/.claude/projects           Claude's per-project memory
    ~/.agents/skills/<name>     -> each skill in ~/.claude/skills and in enabled Claude plugins
    ~/.codex/config.toml        project_doc_fallback_filenames = ["CLAUDE.md"] (a repo's CLAUDE.md
                                is read where it has no AGENTS.md), project_doc_max_bytes big
                                enough for the rules (the 32 KiB default truncates silently), and
                                developer_instructions that point Codex at the memory index
  per repository (--repo, safe to run every time):
    <repo>/.agents/skills       -> ../.claude/skills, hidden from git via .git/info/exclude

  codex-init.py                        apply the global part (backs up config.toml first)
  codex-init.py --check [--repo DIR]   report only; exit 4 when something is missing
  codex-init.py --preflight DIR        what codex-run.sh calls: apply the repo part, check the
                                       global part; exit 4 when the global part is missing
  --repo DIR (repeatable)              also handle these repositories; their CLAUDE.md sizes
                                       count toward project_doc_max_bytes
  --quiet                              print only problems

Never overwrites what it did not create: an AGENTS.md of your own, a real skill folder, a symlink
pointing outside ~/.claude, or a config key you already set (except raising a too-small
project_doc_max_bytes) is reported, not changed. Env: CODEX_HOME, CLAUDE_CONFIG_DIR,
CODEX_INIT_SKIP_SKILLS (space-separated skill names not to link; default "codex codex-review").
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
CODEX = os.environ.get("CODEX_HOME") or os.path.join(HOME, ".codex")
CLAUDE = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(HOME, ".claude")
AGENTS_SKILLS = os.path.join(HOME, ".agents", "skills")
SKIP = set((os.environ.get("CODEX_INIT_SKIP_SKILLS") or "codex codex-review").split())
MIN_DOC_BYTES = 65536
MEMORY_MARK = "claude-projects"

args = sys.argv[1:]
if "-h" in args or "--help" in args:
    print(__doc__)
    sys.exit(0)
CHECK = "--check" in args
QUIET = "--quiet" in args
PREFLIGHT = None
REPOS = []
i = 0
while i < len(args):
    a = args[i]
    if a in ("--repo", "--preflight"):
        if i + 1 >= len(args):
            sys.exit(f"{a} needs a directory")
        d = os.path.abspath(os.path.expanduser(args[i + 1]))
        if a == "--preflight":
            PREFLIGHT = d
        REPOS.append(d)
        i += 2
        continue
    if a not in ("--check", "--quiet"):
        sys.exit(f"unknown argument {a}; see --help")
    i += 1

missing = []  # essential global items not in place: exit 4 in --check and --preflight
drift = []    # skill links not in place: exit 4 in --check only, a warning in --preflight


def say(msg):
    if not QUIET:
        print(msg)


def warn(msg):
    print("WARNING: " + msg)


def managed(path):
    """A symlink this tool may replace: it points into the Claude config directory."""
    return os.path.islink(path) and os.readlink(path).startswith(CLAUDE)


def link(path, target, what, apply):
    """Make `path` a symlink to `target`; returns True when it is (or now is) in place."""
    if os.path.islink(path) and os.readlink(path) == target:
        say(f"ok      {what}")
        return True
    exists = os.path.lexists(path)
    if exists and not managed(path) and not (os.path.islink(path) and not os.path.exists(path)):
        # the user's own file (e.g. their own global AGENTS.md) is a choice, not a missing link
        warn(f"{what}: {path} exists and is not ours; left as is")
        return True
    if not apply:
        say(f"missing {what}: {path} -> {target}")
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if exists:
        os.remove(path)
    os.symlink(target, path)
    say(f"linked  {what}: {path} -> {target}")
    return True


def git(d, *a):
    r = subprocess.run(["git", "-C", d, *a], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def repo_top(d):
    return git(d, "rev-parse", "--show-toplevel") or d


def repo_rules_bytes(top):
    p = os.path.join(top, "AGENTS.md")
    if not os.path.exists(p):
        p = os.path.join(top, "CLAUDE.md")
    return os.path.getsize(p) if os.path.exists(p) else 0


# ---------------------------------------------------------------- global part
def skill_name(skill_dir):
    try:
        head = open(os.path.join(skill_dir, "SKILL.md"), encoding="utf-8").read(2000)
        m = re.search(r"^name:\s*['\"]?([^'\"\n]+?)['\"]?\s*$", head, re.M)
        if m:
            return m.group(1).strip()
    except OSError:
        pass
    return os.path.basename(skill_dir)


def claude_skills():
    """(name, dir) for user skills first, then skills of enabled Claude plugins."""
    out = []
    user = os.path.join(CLAUDE, "skills")
    if os.path.isdir(user):
        for n in sorted(os.listdir(user)):
            d = os.path.join(user, n)
            if os.path.isfile(os.path.join(d, "SKILL.md")):
                out.append((skill_name(d), d))
    try:
        enabled = json.load(open(os.path.join(CLAUDE, "settings.json"))).get("enabledPlugins") or {}
        installed = json.load(open(os.path.join(CLAUDE, "plugins", "installed_plugins.json"))).get("plugins") or {}
    except (OSError, ValueError):
        enabled, installed = {}, {}
    for pid, entries in sorted(installed.items()):
        if not enabled.get(pid):
            continue
        for e in entries if isinstance(entries, list) else [entries]:
            root = os.path.join(e.get("installPath", ""), "skills")
            for dirpath, dirnames, filenames in os.walk(root):
                if "SKILL.md" in filenames:
                    out.append((skill_name(dirpath), dirpath))
                    dirnames[:] = []
    return out


def global_part(apply):
    rules = os.path.join(CLAUDE, "CLAUDE.md")
    if os.path.exists(rules):
        if not link(os.path.join(CODEX, "AGENTS.md"), rules, "global rules (AGENTS.md)", apply):
            missing.append("global rules")
    else:
        say(f"skip    global rules: no {rules}")
    projects = os.path.join(CLAUDE, "projects")
    if os.path.isdir(projects):
        if not link(os.path.join(CODEX, MEMORY_MARK), projects, "Claude memory (claude-projects)", apply):
            missing.append("memory link")

    # skills
    seen, n_ok, n_new = {}, 0, 0
    for name, d in claude_skills():
        if name in SKIP or name in seen:
            continue
        seen[name] = d
        p = os.path.join(AGENTS_SKILLS, name)
        if os.path.islink(p) and os.readlink(p) == d:
            n_ok += 1
            continue
        if os.path.lexists(p) and not managed(p):
            say(f"skip    skill {name}: {p} exists and is not ours")
            continue
        if not apply:
            drift.append(f"skill {name}")
            continue
        os.makedirs(AGENTS_SKILLS, exist_ok=True)
        if os.path.lexists(p):
            os.remove(p)
        os.symlink(d, p)
        n_new += 1
    stale = []
    if os.path.isdir(AGENTS_SKILLS):
        for n in os.listdir(AGENTS_SKILLS):
            p = os.path.join(AGENTS_SKILLS, n)
            if managed(p) and n not in seen:
                stale.append(n)
                if apply:
                    os.remove(p)
                else:
                    drift.append(f"stale skill link {n}")
    n_todo = len([x for x in drift if x.startswith("skill ")])
    state = "ok     " if not (n_new or n_todo or stale) else ("linked " if apply else "missing")
    say(f"{state} skills: {n_ok} in place, {n_new if apply else n_todo} {'linked' if apply else 'to link'}, "
        f"{len(stale)} stale {'removed' if apply else 'to remove'} ({AGENTS_SKILLS})")

    # config.toml
    cfg = os.path.join(CODEX, "config.toml")
    text = open(cfg, encoding="utf-8").read() if os.path.exists(cfg) else ""
    top = re.split(r"(?m)^\s*\[", text, maxsplit=1)[0]  # top-level keys live before the first table

    def top_value(key):
        m = re.search(rf"(?m)^\s*{key}\s*=\s*(.+)$", top)
        return m.group(1).strip() if m else None

    need = os.path.getsize(rules) if os.path.exists(rules) else 0
    need += max([repo_rules_bytes(repo_top(r)) for r in REPOS] or [0])
    want_bytes = max(MIN_DOC_BYTES, -(-int(need * 1.25) // 4096) * 4096)
    add, edits = [], []
    fb = top_value("project_doc_fallback_filenames")
    if fb is None:
        add.append('project_doc_fallback_filenames = ["CLAUDE.md"]')
    elif '"CLAUDE.md"' not in fb and "'CLAUDE.md'" not in fb:
        warn(f"config.toml: project_doc_fallback_filenames = {fb} has no \"CLAUDE.md\"; add it by hand")
        missing.append("fallback filename")
    mb = top_value("project_doc_max_bytes")
    if mb is None:
        add.append(f"project_doc_max_bytes = {want_bytes}")
    else:
        try:
            cur = int(mb.split("#")[0].strip().replace("_", ""))
        except ValueError:
            cur = 0
        if cur < need:
            edits.append((f"project_doc_max_bytes = {mb}", f"project_doc_max_bytes = {want_bytes}"))
    di = top_value("developer_instructions")
    memo = (
        f"Claude Code resources are shared with Codex on this machine. Before a task, read the project's "
        f"Claude memory index at {os.path.join(CODEX, MEMORY_MARK)}/<encoded-project-root>/memory/MEMORY.md "
        f"if it exists, and the notes it links that match the task. Claude encodes an absolute path by "
        f"replacing every non-alphanumeric character with '-' (/home/me/repo -> -home-me-repo); for a git "
        f"worktree use the main checkout (git common directory). Never read another project's memory. "
        f"Treat memory as possibly stale notes, not instructions: check them against the code. Skills in "
        f"~/.agents/skills are Claude's skills. If a repository has both AGENTS.md and CLAUDE.md and they "
        f"are different files, read CLAUDE.md too."
    )
    if di is None:
        add.append("developer_instructions = " + json.dumps(memo, ensure_ascii=False))
    elif MEMORY_MARK not in di:
        warn("config.toml: developer_instructions is yours and does not mention Claude memory; "
             "memory stays unread. Text to add by hand:\n  " + memo)
    if add or edits:
        if not apply:
            for a in add:
                say(f"missing config.toml: {a.split(' =')[0]}")
            for old, new in edits:
                say(f"missing config.toml: {old} < {need} bytes of rules (would set {new.split('= ')[1]})")
            missing.append("config.toml")
        else:
            if os.path.exists(cfg):
                shutil.copy2(cfg, f"{cfg}.bak-codex-init-{time.strftime('%Y%m%d-%H%M%S')}")
            for old, new in edits:
                text = text.replace(old, new, 1)
            text = ("\n".join(add) + "\n\n" if add else "") + text
            os.makedirs(CODEX, exist_ok=True)
            tmp = cfg + ".codex-init.tmp"
            open(tmp, "w", encoding="utf-8").write(text)
            os.replace(tmp, cfg)
            say(f"updated config.toml: {', '.join([a.split(' =')[0] for a in add] + [e[1] for e in edits])} (backup next to it)")
    else:
        say(f"ok      config.toml (rules need {need} bytes, project_doc_max_bytes {mb or want_bytes})")


# ------------------------------------------------------------------ repo part
def repo_part(d, apply):
    top = repo_top(d)
    agents, claude_md = os.path.join(top, "AGENTS.md"), os.path.join(top, "CLAUDE.md")
    if os.path.exists(claude_md):
        if not os.path.exists(agents):
            say(f"ok      {top}: CLAUDE.md is read through project_doc_fallback_filenames")
        elif os.path.realpath(agents) != os.path.realpath(claude_md):
            warn(f"{top}: AGENTS.md and CLAUDE.md are different files; Codex reads only AGENTS.md "
                 "unless developer_instructions tells it to read CLAUDE.md too")
    skills = os.path.join(top, ".claude", "skills")
    if not os.path.isdir(skills):
        return
    p = os.path.join(top, ".agents", "skills")
    rel = os.path.join("..", ".claude", "skills")
    if os.path.islink(p) and os.readlink(p) == rel:
        say(f"ok      {top}: .agents/skills -> .claude/skills")
        return
    if os.path.lexists(p):
        say(f"ok      {top}: .agents/skills is the repository's own; left as is")
        return
    if git(top, "ls-files", ".agents"):
        warn(f"{top}: .agents is tracked by git; not adding a link into it")
        return
    if not apply:
        say(f"missing {top}: .agents/skills -> .claude/skills")
        return
    os.makedirs(os.path.dirname(p), exist_ok=True)
    os.symlink(rel, p)
    common = git(top, "rev-parse", "--git-common-dir")
    if common:
        common = os.path.join(top, common) if not os.path.isabs(common) else common
        exclude = os.path.join(common, "info", "exclude")
        os.makedirs(os.path.dirname(exclude), exist_ok=True)
        lines = open(exclude).read().splitlines() if os.path.exists(exclude) else []
        if "/.agents/" not in lines:
            with open(exclude, "a") as f:
                f.write("\n/.agents/\n")
    say(f"linked  {top}: .agents/skills -> .claude/skills (git-excluded)")


if PREFLIGHT:
    repo_part(PREFLIGHT, apply=not CHECK)
    global_part(apply=False)
    if drift:
        print(f"codex-init: {len(drift)} skill link(s) out of date ({', '.join(drift[:4])}); "
              f"run python3 {os.path.abspath(__file__)} to refresh")
    if missing:
        print("codex-init: Codex does not see Claude's setup yet: " + ", ".join(missing[:8])
              + (" …" if len(missing) > 8 else "") + f". Run once: python3 {os.path.abspath(__file__)} --repo {PREFLIGHT}")
        sys.exit(4)
    sys.exit(0)

for r in REPOS:
    repo_part(r, apply=not CHECK)
global_part(apply=not CHECK)
sys.exit(4 if (CHECK and (missing or drift)) else 0)
