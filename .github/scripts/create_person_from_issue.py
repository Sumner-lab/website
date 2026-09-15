#!/usr/bin/env python3
"""Turns one "Add a new lab member" issue-form submission into a new
_people/<slug>.md profile (plus their resized photo), for
new-member-submission.yml to commit and open as a PR.

A profile is the only file a new member needs: the People page and the
media archive's people photos both read straight from the _people
collection, and the People page lists current members alphabetically
after anyone pinned with `order:` (see _layouts/people-index.html), so
nothing else has to be edited or renumbered.

Reuses create_post_from_issue.py's slugify / YAML quoting / image
download-resize-EXIF-strip pipeline, and create_media_entry_from_issue.py's
http(s)-only link check and "Label | URL" parsing, rather than
re-implementing them (both are safe to import -- their entry points are
guarded behind `if __name__ == "__main__":`).

Reads the raw issue body from the ISSUE_BODY env var (never interpolated
into a shell command -- issue text is untrusted input). Writes:

- The new _people/<slug>.md file.
- The processed photo, under wp-content/uploads/.
- A manifest JSON (NEW_MEMBER_MANIFEST_PATH) listing exactly the paths
  written, so the workflow's `git add` only stages what this script
  actually created -- never `git add -A`.
- A plain-English summary (NEW_MEMBER_SUMMARY_PATH) of what happened, for
  the workflow to use as the PR body and the issue comment.

Exit 0 even when something optional was skipped (a photo that failed to
download, an unrecognisable link) -- those are noted in the summary. Exit 1
only when the profile can't be built at all (a required field missing, or
a profile with that name already exists) -- nothing here reaches `main`
without a human reviewing the resulting PR.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import create_post_from_issue as post_lib  # noqa: E402
import create_media_entry_from_issue as media_lib  # noqa: E402

REPO_ROOT = post_lib.REPO_ROOT
PEOPLE_DIR = os.path.join(REPO_ROOT, "_people")
UPLOADS_ROOT = post_lib.UPLOADS_ROOT

# Must exactly match the `label:` strings in
# .github/ISSUE_TEMPLATE/new-member.yml -- see create_post_from_issue.py's
# FIELD_LABELS note for why this string-matching is necessary.
FIELD_LABELS = {
    "name": "Full name",
    "role": "Role and topic",
    "position": "Position",
    "joined": "Year you joined the lab",
    "photo": "Profile photo",
    "consent": "Permission",
    "interests": "Research interests",
    "project": "Project (optional)",
    "background": "Background (optional)",
    "email": "Contact email (optional)",
    "publications": "Publications (optional)",
    "other_interests": "Other interests (optional)",
    "bluesky": "Bluesky",
    "twitter": "X / Twitter",
    "instagram": "Instagram",
    "linkedin": "LinkedIn",
    "orcid": "ORCID",
    "scholar": "Google Scholar",
    "github": "GitHub",
    "website": "Personal website",
    "other_links": "Other links",
}

REQUIRED = ["name", "role", "position", "joined", "interests"]

# (field, button label, URL for a bare username/ID -- None if only a full
# link makes sense). Labels match the ones already used across _people/.
LINK_FIELDS = [
    ("bluesky", "Bluesky", lambda h: f"https://bsky.app/profile/{h}"),
    ("twitter", "Twitter", lambda h: f"https://x.com/{h}"),
    ("instagram", "Instagram", lambda h: f"https://instagram.com/{h}"),
    ("linkedin", "LinkedIn", None),
    ("orcid", "ORCID", lambda h: f"https://orcid.org/{h}"),
    ("scholar", "Google Scholar", None),
    ("github", "GitHub", lambda h: f"https://github.com/{h}"),
    ("website", "Personal website", None),
]


def parse_issue_body(body):
    sections = {}
    parts = re.split(r'^### (.+)$', body, flags=re.MULTILINE)
    for i in range(1, len(parts), 2):
        sections[parts[i].strip()] = parts[i + 1].strip() if i + 1 < len(parts) else ""

    def get(key):
        v = sections.get(FIELD_LABELS[key], "")
        return "" if v == "_No response_" else v.replace("\r\n", "\n")

    return {k: get(k) for k in FIELD_LABELS}


def one_line(text, field, notes):
    """Name/role go into front matter and are output unescaped by the
    layouts, so they're kept to plain single-line text: no newlines, and no
    angle brackets (which have no legitimate use there and could otherwise
    carry HTML onto every page that lists this person)."""
    cleaned = " ".join(text.split())
    if "<" in cleaned or ">" in cleaned:
        cleaned = re.sub(r'<[^>]*>', '', cleaned).replace("<", "").replace(">", "")
        cleaned = " ".join(cleaned.split())
        notes.append(f"Removed HTML/angle brackets from the {field} -- plain text only there.")
    return cleaned


def resolve_link(field, label, from_handle, value, notes):
    value = value.strip()
    if not value:
        return None
    if re.match(r'^https?://', value):
        return media_lib.safe_url(value, notes)
    handle = value.lstrip("@").strip("/")
    if from_handle and re.fullmatch(r'[A-Za-z0-9._-]+', handle):
        return from_handle(handle)
    # A web address typed without the https:// (eg. "linkedin.com/in/jane").
    if re.fullmatch(r'(?:www\.)?[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?:/\S*)?', value):
        return "https://" + value
    notes.append(f"The {label} entry \"{value}\" isn't a full link (starting with https://)"
                 f"{' or a plain username/ID' if from_handle else ''} -- left out.")
    return None


def as_list(text):
    """One item per line as a Markdown list, keeping any bullets the
    submitter typed themselves rather than doubling them up."""
    items = [re.sub(r'^\s*(?:[-*•]|\d+[.)])\s+', '', line).strip() for line in text.splitlines()]
    return "\n".join(f"- {item}" for item in items if item)


def save_photo(fields, slug, issue_number, issue_created_at, notes):
    if not media_lib.checkbox_checked(fields["consent"]):
        if fields["photo"].strip():
            notes.append("A photo was attached but the permission box wasn't ticked -- photo skipped.")
        return None
    urls = post_lib.extract_photo_urls(fields["photo"], notes)
    if not urls:
        notes.append("No usable photo was attached -- the profile will show their initial until one is added.")
        return None
    raw = post_lib.download_image(urls[0], notes)
    if raw is None:
        return None
    data, ext = post_lib.process_image(raw, notes)
    if data is None:
        return None
    year, month = issue_created_at[:4], issue_created_at[5:7]
    upload_dir = os.path.join(UPLOADS_ROOT, year, month)
    os.makedirs(upload_dir, exist_ok=True)
    filename = f"{slug}.{ext}"
    if os.path.exists(os.path.join(upload_dir, filename)):
        filename = f"{slug}-issue{issue_number}.{ext}"
    with open(os.path.join(upload_dir, filename), "wb") as f:
        f.write(data)
    return f"/wp-content/uploads/{year}/{month}/{filename}"


def build_profile(fields, photo_path, links, notes):
    name = one_line(fields["name"], "name", notes)
    role = one_line(fields["role"], "role", notes)

    front = [
        "---",
        f"name: {post_lib.yaml_quote(name)}",
        f"role: {post_lib.yaml_quote(role)}",
        "status: current",
        f'joined: "{fields["joined"].strip()}"',
    ]
    if photo_path:
        front.append(f"photo: {photo_path}")
    front.append(f"title: {post_lib.yaml_quote(name)}")
    if links:
        front.append("links:")
        for label, url in links:
            front.append(f"  - label: {post_lib.yaml_quote(label)}")
            front.append(f"    url: {post_lib.yaml_quote(url)}")
    front.append("---")

    sections = [f"**Position:** {' '.join(fields['position'].split())}"]
    if fields["project"].strip():
        sections.append(f"**Project:** {' '.join(fields['project'].split())}")
    sections.append(f"**Research Interests:** {fields['interests'].strip()}")
    if fields["other_interests"].strip():
        sections.append(f"**Other interests:** {fields['other_interests'].strip()}")
    if as_list(fields["background"]):
        sections.append("**Background**\n\n" + as_list(fields["background"]))
    email = fields["email"].strip()
    if email:
        if re.fullmatch(r'[^@\s<>()\[\]]+@[^@\s<>()\[\]]+\.[A-Za-z]{2,}', email):
            sections.append(f"**Contact:** [{email}](mailto:{email})")
        else:
            notes.append(f"\"{email}\" doesn't look like an email address -- left out.")
    if as_list(fields["publications"]):
        sections.append("**Publications**\n\n" + as_list(fields["publications"]))

    body = "\n\n".join(sections)
    # Same guard as new posts: literal Liquid-looking text in a paste would
    # build fine in review but break the site after merge.
    if "{{" in body or "{%" in body:
        body = "{% raw %}\n" + body + "\n{% endraw %}"

    return "\n".join(front) + "\n" + body + "\n"


def front_matter_is_valid(content, notes):
    try:
        from yaml import safe_load
    except ImportError:
        notes.append("YAML validation isn't available in this run -- check the front matter by eye.")
        return True
    try:
        data = safe_load(content.split("---\n", 2)[1])
    except Exception as e:
        notes.append(f"The profile's front matter didn't produce valid YAML ({e}).")
        return False
    return isinstance(data, dict) and bool(data.get("name"))


def fail(summary_path, manifest_path, message):
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(message + "\n")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({"person": None, "images": [], "name": None}, f)
    print(f"Fatal: {message}")
    sys.exit(1)


def main():
    issue_number = os.environ.get("ISSUE_NUMBER", "0")
    issue_body = os.environ.get("ISSUE_BODY", "")
    issue_created_at = os.environ.get("ISSUE_CREATED_AT", "")
    summary_path = os.environ.get("NEW_MEMBER_SUMMARY_PATH", "/tmp/new_member_summary.md")
    manifest_path = os.environ.get("NEW_MEMBER_MANIFEST_PATH", "/tmp/new_member_manifest.json")

    if not issue_body or not issue_created_at:
        print("Missing ISSUE_BODY or ISSUE_CREATED_AT -- can't proceed.")
        sys.exit(1)

    fields = parse_issue_body(issue_body)
    notes = []

    missing = [FIELD_LABELS[k] for k in REQUIRED if not fields[k].strip()]
    if missing:
        fail(summary_path, manifest_path,
             f"This submission is missing required information ({', '.join(missing)}) -- "
             f"please submit the form again with those filled in.")
    if not re.fullmatch(r'(19|20)\d{2}', fields["joined"].strip()):
        fail(summary_path, manifest_path,
             f"\"{fields['joined'].strip()}\" isn't a year (expected something like 2026) -- "
             f"please submit the form again with the year you joined.")

    name = one_line(fields["name"], "name", [])
    slug = post_lib.slugify(name)
    person_path = os.path.join(PEOPLE_DIR, f"{slug}.md")
    if os.path.exists(person_path):
        fail(summary_path, manifest_path,
             f"There's already a profile for **{name}** (`_people/{slug}.md`). If you're returning "
             f"to the lab, a maintainer can update that page instead -- nothing was changed.")

    links = []
    for field, label, from_handle in LINK_FIELDS:
        url = resolve_link(field, label, from_handle, fields[field], notes)
        if url:
            links.append((label, url))
    links += media_lib.parse_other_links(fields["other_links"], notes)

    photo_path = save_photo(fields, slug, issue_number, issue_created_at, notes)
    saved_images = [photo_path.lstrip("/")] if photo_path else []

    content = build_profile(fields, photo_path, links, notes)
    if not front_matter_is_valid(content, notes):
        for img in saved_images:
            os.remove(os.path.join(REPO_ROOT, img))
        fail(summary_path, manifest_path,
             "Something in this submission couldn't be turned into a valid profile -- a maintainer "
             "will need to take a look.\n\n" + "\n".join(f"- {n}" for n in notes))

    with open(person_path, "w", encoding="utf-8") as f:
        f.write(content)

    person_rel = os.path.relpath(person_path, REPO_ROOT)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({"person": person_rel, "images": saved_images, "name": name}, f)

    summary = [f"New lab member: **{name}**", "", f"- Profile: `{person_rel}` (will be at `/people/{slug}/`)."]
    summary.append(f"- Photo: `{saved_images[0]}`." if saved_images else "- Photo: none yet.")
    if links:
        summary.append(f"- Links: {', '.join(label for label, _ in links)}.")
    if notes:
        summary += ["", "Notes from processing this submission:"] + [f"- {n}" for n in notes]
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(summary) + "\n")

    print(f"Wrote {person_rel}, photo={bool(saved_images)}, links={len(links)}.")


if __name__ == "__main__":
    main()
