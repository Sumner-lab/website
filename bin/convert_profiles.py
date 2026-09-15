#!/usr/bin/env python3
"""Moves the free-text sections of each _people/*.md profile into the
template fields that _layouts/person.html reads (see "Profile fields" in
README.md).

Profiles used to be written as one block of Markdown with bold labels --
"**Position:** PhD Student", "**Background**" followed by a list, and so
on. This script recognises those labels and moves their content into front
matter fields:

    Position                               -> position
    Project, Current project               -> project
    Research interests, Interests          -> interests
    Other interests                        -> other_interests
    Biography (and prose under Background) -> biography
    Background, Background/Biography,
    Timeline (list lines)                  -> background (a list)
    Publications, Selected/Main
    publications (a plain list)            -> publications (+ publications_label)
    Contact, Email, Address                -> contact
    text before the first label            -> intro

Anything it doesn't recognise -- Teaching, Book chapters, a publications
list mixed with other text, stray images -- stays in the page body exactly
as written, and still shows on the profile's About tab. Nothing is
reworded or dropped.

Existing front matter is left untouched (new fields are appended after
it), so the diff only shows what moved. A profile that already has any
template field is skipped, so this is safe to re-run -- e.g. after a
profile was edited on main while the conversion PR was open.

Usage (needs PyYAML):
    python3 bin/convert_profiles.py            # convert every profile
    python3 bin/convert_profiles.py --check    # report only, write nothing
"""
import os
import re
import sys

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PEOPLE_DIR = os.path.join(REPO_ROOT, "_people")

TEMPLATE_FIELDS = ["intro", "position", "project", "interests", "other_interests", "biography",
                   "background", "publications_label", "publications", "contact"]

LABELS = {
    "position": "position",
    "project": "project", "current project": "project",
    "research interests": "interests", "interests": "interests",
    "other interests": "other_interests",
    "biography": "biography",
    "background": "background", "background/biography": "background", "timeline": "background",
    "publications": "publications", "selected publications": "publications", "main publications": "publications",
    "contact": "contact", "email": "contact", "address": "contact",
}

BOLD_HEADING = re.compile(r'^\*\*(?P<label>[^*\n]{1,40}?):?\*\*:?[ \t]*(?P<rest>.*)$')
MD_HEADING = re.compile(r'^##[ \t]+(?P<label>[^#\n]+?)[ \t]*$')
LIST_ITEM = re.compile(r'^(?:[-*]|\d+\.)[ \t]+(?P<item>.*)$')


class Dumper(yaml.SafeDumper):
    pass


def _str_representer(dumper, value):
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


Dumper.add_representer(str, _str_representer)


def split_front_matter(text):
    if not text.startswith("---\n"):
        raise ValueError("no front matter")
    end = text.index("\n---\n", 3)
    return text[4:end + 1], text[end + 5:]


def tidy(lines):
    """Joins lines into Markdown: trailing spaces and surplus blank lines removed."""
    text = "\n".join(line.rstrip() for line in lines).strip("\n")
    return re.sub(r'\n{3,}', "\n\n", text)


def parse_sections(body):
    """Splits a profile body into (intro_lines, [section]) where each section
    is a dict: label (as written), key (template field or None), heading
    (the original heading line), rest (text after an inline label) and
    lines (everything up to the next heading)."""
    intro, sections = [], []
    for line in body.split("\n"):
        m = BOLD_HEADING.match(line) or MD_HEADING.match(line)
        if m:
            label = m.group("label").strip().rstrip(":").strip()
            sections.append({"label": label, "key": LABELS.get(label.lower()), "heading": line,
                             "rest": (m.groupdict().get("rest") or "").strip(), "lines": []})
        elif sections:
            sections[-1]["lines"].append(line)
        else:
            intro.append(line)
    return intro, sections


def split_list(lines):
    """Returns (items, prose_lines) if the list lines are simple one-line
    items, or None if an item wraps onto a following line (too ambiguous to
    move safely)."""
    items, prose, prev_was_item = [], [], False
    for line in lines:
        if not line.strip():
            prev_was_item = False
            prose.append("")
            continue
        m = LIST_ITEM.match(line)
        if m:
            items.append(m.group("item").strip())
            prev_was_item = True
        elif prev_was_item:
            return None
        else:
            prose.append(line)
    return items, prose


def leading_paragraph(lines):
    """Splits off the first paragraph (up to a blank line) from lines."""
    stripped = list(lines)
    while stripped and not stripped[0].strip():
        stripped.pop(0)
    for i, line in enumerate(stripped):
        if not line.strip():
            return stripped[:i], stripped[i:]
    return stripped, []


def convert(front, body):
    """Returns (fields, new_body, notes) for one profile."""
    intro, sections = parse_sections(body)
    fields, leftover, notes = {}, [], []

    def add_text(key, text):
        if not text:
            return
        fields[key] = f"{fields[key]}\n\n{text}" if key in fields else text

    def keep(section, lines=None):
        leftover.append(section["heading"])
        leftover.extend(section["lines"] if lines is None else lines)
        leftover.append("")

    if tidy(intro):
        fields["intro"] = tidy(intro)

    for sec in sections:
        key, rest, lines = sec["key"], sec["rest"], sec["lines"]

        if key in ("position", "project", "other_interests"):
            if key in fields:
                keep(sec)
                notes.append(f"second '{sec['label']}' section kept as text")
                continue
            first, after = ([rest], lines) if rest else leading_paragraph(lines)
            value = " ".join(line.strip() for line in first if line.strip())
            if not value:
                keep(sec)
                continue
            fields[key] = value
            if tidy(after):
                leftover.extend(after)
                leftover.append("")

        elif key in ("interests", "biography"):
            add_text(key, tidy(([rest, ""] if rest else []) + lines))

        elif key == "background":
            parsed = split_list(lines)
            if parsed is None:
                keep(sec)
                notes.append(f"'{sec['label']}' has wrapped list lines, kept as text")
                continue
            items, prose = parsed
            if items:
                fields.setdefault("background", []).extend(items)
            add_text("biography", tidy(([rest, ""] if rest else []) + prose))

        elif key == "publications":
            parsed = split_list(lines)
            if rest or parsed is None or not parsed[0] or tidy(parsed[1]) or "publications" in fields:
                keep(sec)
                notes.append(f"'{sec['label']}' isn't a plain list, kept as text")
                continue
            fields["publications"] = parsed[0]
            if sec["label"].lower() != "publications":
                fields["publications_label"] = sec["label"]

        elif key == "contact":
            # Only the label's own line and a list straight after it; anything
            # further (photos, a caption) stays as page text.
            head = rest if sec["label"].lower() == "contact" else sec["heading"]
            taken = []
            remaining = list(lines)
            while remaining and not remaining[0].strip():
                remaining.pop(0)
            while remaining and LIST_ITEM.match(remaining[0]):
                taken.append(remaining.pop(0))
            add_text("contact", tidy(([head] if head else []) + ([""] if head and taken else []) + taken))
            if tidy(remaining):
                leftover.extend(remaining)
                leftover.append("")

        else:
            keep(sec)

    return fields, tidy(leftover), notes


def render(front, fields, new_body):
    extra = "".join(yaml.dump({k: fields[k]}, Dumper=Dumper, allow_unicode=True, sort_keys=False, width=10**9)
                    for k in TEMPLATE_FIELDS if k in fields)
    return "---\n" + front + extra + "---\n" + (new_body + "\n" if new_body else "")


def main():
    check_only = "--check" in sys.argv[1:]
    changed = 0
    for fname in sorted(os.listdir(PEOPLE_DIR)):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(PEOPLE_DIR, fname)
        text = open(path, encoding="utf-8").read()
        front, body = split_front_matter(text)
        existing = yaml.safe_load(front) or {}
        if any(k in existing for k in TEMPLATE_FIELDS):
            print(f"{fname}: already uses template fields, skipped")
            continue

        fields, new_body, notes = convert(front, body)
        if not fields:
            print(f"{fname}: nothing recognised, left as is")
            continue

        output = render(front, fields, new_body)
        parsed = yaml.safe_load(split_front_matter(output)[0])
        assert all(parsed.get(k) == v for k, v in fields.items()), f"{fname}: fields didn't round-trip"
        assert all(parsed.get(k) == v for k, v in existing.items()), f"{fname}: existing front matter changed"

        summary = ", ".join(k if not isinstance(fields[k], list) else f"{k} ({len(fields[k])})" for k in TEMPLATE_FIELDS if k in fields)
        print(f"{fname}: {summary}" + (f" | body kept: {len(new_body.splitlines())} lines" if new_body else "")
              + ("".join(f"\n    note: {n}" for n in notes)))
        if not check_only:
            with open(path, "w", encoding="utf-8") as f:
                f.write(output)
        changed += 1
    print(f"\n{changed} profile(s) {'would be ' if check_only else ''}converted.")


if __name__ == "__main__":
    main()
