#!/usr/bin/env python3
"""codex-model.py <family> <models_cache.json> — print the newest listed model id of a family.

Reads the Codex CLI's model catalog cache: models[] with slug, visibility ("list" = selectable)
and priority. Within the family the highest version parsed from gpt-<major>[.<minor>]-<family>
wins, ties go to the lower priority number. Exit 1 with a message on stderr if the catalog is
missing or unreadable, or lists no model of that family: never guess an id.
"""
import json
import re
import sys


def fail(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


def main():
    if len(sys.argv) != 3:
        fail("usage: codex-model.py <family> <models_cache.json>")
    family, path = sys.argv[1].lower(), sys.argv[2]
    try:
        with open(path) as f:
            models = json.load(f)["models"]
        if not isinstance(models, list):
            raise TypeError("models is not a list")
    except (OSError, ValueError, KeyError, TypeError) as e:
        fail(f"model catalog {path} is missing or unreadable ({e.__class__.__name__}: {e})")
    pat = re.compile(r"^gpt-(\d+)(?:\.(\d+))?-" + re.escape(family) + r"$")
    best = None
    for m in models:
        if not isinstance(m, dict) or m.get("visibility") != "list":
            continue
        hit = pat.match(str(m.get("slug", "")))
        if not hit:
            continue
        prio = m.get("priority")
        key = (-int(hit.group(1)), -int(hit.group(2) or 0),
               prio if isinstance(prio, (int, float)) else float("inf"))
        if best is None or key < best[0]:
            best = (key, m["slug"])
    if best is None:
        fail(f"no listed model of family '{family}' in {path}")
    print(best[1])


main()
