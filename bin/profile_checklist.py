#!/usr/bin/env python3
"""Lists what each _people/*.md profile is missing, as a Markdown table.

Nothing breaks when a profile is incomplete -- the field notebook layout
just leaves out a tab, a specimen-label row or the career ruler -- but the
page looks thinner. This prints what each person could add, so the list
can be shared with the lab (e.g. pasted into an issue).

Usage (needs PyYAML):
    python3 bin/profile_checklist.py
"""
import os
import re
import sys

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PEOPLE_DIR = os.path.join(REPO_ROOT, "_people")
YEAR_LINE = re.compile(r'^\s*(?:[A-Za-z]{3,9}\.?\s+)?(19|20)\d{2}\s*(?:[–—-]|:|$)')


def front_matter(path):
    text = open(path, encoding="utf-8").read()
    end = text.index("\n---\n", 3)
    return yaml.safe_load(text[4:end + 1]) or {}


def missing_for(p):
    current = p.get("status") != "alumni"
    stints = p.get("stints") or ([{"joined": p.get("joined"), "left": p.get("left")}] if p.get("joined") else [])
    links = [str(l.get("label", "")).lower() for l in (p.get("links") or [])]
    todo = []
    if not p.get("photo"):
        todo.append("photo")
    if not p.get("position"):
        todo.append("position")
    if current and not p.get("project"):
        todo.append("project")
    if not p.get("interests"):
        todo.append("research interests")
    background = p.get("background") or []
    if not background:
        todo.append("career history (background)")
    else:
        undated = [b for b in background if not YEAR_LINE.match(str(b))]
        if undated:
            todo.append(f"years on {len(undated)} of {len(background)} career lines")
    if not stints:
        todo.append("year joined" + ("" if current else " and left"))
    elif not current and any(not s.get("left") for s in stints):
        todo.append("year left")
    if current and "orcid" not in links:
        todo.append("ORCID link")
    if current and not p.get("contact"):
        todo.append("contact email")
    if current:
        new = [label for key, label in (("studies", "study organism"), ("themes", "research themes")) if not p.get(key)]
        if new:
            todo.append("new: " + ", ".join(new))
    return todo


def main():
    rows = []
    for fname in sorted(os.listdir(PEOPLE_DIR)):
        if fname.endswith(".md"):
            p = front_matter(os.path.join(PEOPLE_DIR, fname))
            rows.append((p.get("status") != "alumni", p.get("name") or fname[:-3], missing_for(p)))
    rows.sort(key=lambda r: (not r[0], r[1]))
    print("| Person | | Could add |")
    print("|---|---|---|")
    for current, name, todo in rows:
        print(f"| {name} | {'Current' if current else 'Alumni'} | {'; '.join(todo) if todo else 'Complete'} |")
    complete = sum(1 for r in rows if not r[2])
    print(f"\n{complete} of {len(rows)} profiles complete.", file=sys.stderr)


if __name__ == "__main__":
    main()
