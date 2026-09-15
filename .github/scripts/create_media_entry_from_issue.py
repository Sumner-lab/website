#!/usr/bin/env python3
"""Turns one "Submit a media appearance" issue-form submission into a new
entry in _data/media.yml (plus a resized photo, if one was attached and
consented to), for new-media-submission.yml to commit and open as a PR.

Reuses create_post_from_issue.py's field parsing, date resolution, and
image download/resize/EXIF-strip pipeline rather than re-implementing it
(safe to import -- that module guards its entry point behind
`if __name__ == "__main__":`).

Unlike a blog post, a media entry isn't its own file -- _data/media.yml is
one shared list that's also hand-edited (headline/image/credit added after
the fact), so this script only ever *appends* a new entry to it as text.
It never loads the file into a YAML structure and re-dumps the whole
thing, which would reformat it and blow up the PR diff, and risk losing a
maintainer's hand-edits/comments. The appended text is re-parsed
afterwards purely to validate it -- if that fails, nothing is written.

Reads the raw issue body from the ISSUE_BODY env var (never interpolated
into a shell command -- issue text is untrusted input). Writes:

- The appended _data/media.yml (unless validation failed).
- Any successfully processed photo, directly under wp-content/uploads/.
- A manifest JSON (NEW_MEDIA_MANIFEST_PATH) listing exactly the paths
  written, so the workflow's `git add` only stages what this script
  actually created -- never `git add -A`.
- A plain-English summary (NEW_MEDIA_SUMMARY_PATH) of what happened, for
  the workflow to use as the PR body and the issue comment.

Exit 0 even when the photo or the YAML append was skipped for some
non-essential reason -- those are noted in the summary, not fatal. Exit 1
only when the entry itself can't be built at all (missing outlet/type, or
an unexpected internal failure) -- nothing here reaches `main` without a
human reviewing the resulting PR.
"""
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import create_post_from_issue as post_lib  # noqa: E402


def safe_url(url, notes):
    """Only http(s) links are ever embedded as an href -- issue text is
    untrusted input, and something like a javascript: URL would otherwise
    go live in the page the moment a reviewer merges the PR without
    spotting it in the diff."""
    url = url.strip()
    if not url:
        return None
    if not re.match(r'^https?://', url):
        notes.append(f"\"{url}\" doesn't look like a web link (must start with http:// or https://) -- skipped.")
        return None
    return url

REPO_ROOT = post_lib.REPO_ROOT
PEOPLE_DIR = os.path.join(REPO_ROOT, "_people")
DATA_PATH = os.path.join(REPO_ROOT, "_data", "media.yml")
MEDIA_PAGE_PATH = os.path.join(REPO_ROOT, "media.md")
UPLOADS_ROOT = post_lib.UPLOADS_ROOT

# A Featured section is inserted directly after this exact line in
# media.md (see that file) -- if the marker's ever edited away, featuring
# is skipped (noted in the summary) rather than guessing where to insert.
FEATURED_INSERT_MARKER = (
    "<!-- new-media-submission bot inserts new Featured sections directly "
    "below this marker -- see .github/scripts/create_media_entry_from_issue.py -->"
)

# Must exactly match the `label:` strings in
# .github/ISSUE_TEMPLATE/new-media.yml -- see create_post_from_issue.py's
# FIELD_LABELS docstring note for why this string-matching is necessary.
FIELD_LABELS = {
    "outlet": "Outlet or event name",
    "type": "Type",
    "date": "Date (optional)",
    "url": "Link (optional)",
    "headline": "Headline (optional)",
    "people": "Lab members involved (optional)",
    "photo": "Photo (optional)",
    "consent": "Photo permission",
    "feature": "Feature this",
    "description": "Description (optional, featured entries only)",
    "other_links": "Other links (optional, featured entries only)",
}

VALID_TYPES = {"TV", "Radio", "Podcast", "Print", "Talk", "Prize", "Exhibition", "Other"}


def parse_issue_body(body):
    sections = {}
    parts = re.split(r'^### (.+)$', body, flags=re.MULTILINE)
    for i in range(1, len(parts), 2):
        label = parts[i].strip()
        value = parts[i + 1].strip() if i + 1 < len(parts) else ""
        sections[label] = value

    def get(key):
        v = sections.get(FIELD_LABELS[key], "")
        return "" if v == "_No response_" else v

    return {k: get(k) for k in FIELD_LABELS}


def checkbox_checked(field):
    return bool(re.search(r'-\s*\[[xX]\]', field))


def parse_other_links(text, notes):
    """Parses the "Label | https://..." one-per-line format. A line
    without a recognizable URL is skipped (noted) rather than guessed at."""
    links = []
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("-").strip()
        if not line:
            continue
        if "|" in line:
            label, _, url = line.partition("|")
            label, url = label.strip(), url.strip()
        else:
            label, url = "", line.strip()
        url = safe_url(url, notes)
        if url is None:
            continue
        links.append((label or url, url))
    return links


def load_people():
    """{slug: name} for every _people/*.md file. The slug is the file name,
    which is also what the archive looks people up by (and their
    /people/<slug>/ URL)."""
    people = {}
    for fname in sorted(os.listdir(PEOPLE_DIR)):
        if not fname.endswith(".md"):
            continue
        with open(os.path.join(PEOPLE_DIR, fname), encoding="utf-8") as f:
            m = re.search(r'^name:\s*["\']?(.+?)["\']?\s*$', f.read(), flags=re.MULTILINE)
        slug = fname[:-3]
        people[slug] = m.group(1) if m else slug.replace("-", " ")
    return people


def resolve_people(text, notes):
    """Matches the comma-separated "Lab members involved" names to _people/
    slugs, trying in turn: the exact full name (or file name), first + last
    name allowing a shortened first name (so "Femi Benny" finds "Femi E.
    Benny" and "Chris Wyatt" finds "Christopher Wyatt"), then a first name
    alone if only one person has it. A name that's unmatched or ambiguous is left out
    and noted, for the reviewer to add by hand rather than guessed at."""
    people = {slug: post_lib.slugify(name).split("-") for slug, name in load_people().items()}
    slugs = []
    for raw_name in re.split(r'[,;&\n]|\band\b', text):
        name = raw_name.strip()
        if not name:
            continue
        words = post_lib.slugify(name).split("-")
        matches = [s for s, w in people.items() if w == words or s.split("-") == words]
        if not matches and len(words) >= 2:
            matches = [s for s, w in people.items() if w[0].startswith(words[0]) and w[-1] == words[-1]]
        if not matches and len(words) == 1:
            matches = [s for s, w in people.items() if w[0] == words[0]]
        if len(matches) == 1:
            if matches[0] not in slugs:
                slugs.append(matches[0])
        elif matches:
            notes.append(f"\"{name}\" matches more than one person on the People page -- left out, "
                         f"add the right one to `people:` by hand.")
        else:
            notes.append(f"Couldn't find \"{name}\" on the People page -- left out, add them to "
                         f"`people:` by hand if they should be shown.")
    return slugs


def build_entry_block(fields, date_str, photo_path, people, notes):
    lines = [f"- outlet: {post_lib.yaml_quote(fields['outlet'].strip())}"]
    lines.append(f"  type: {fields['type'].strip()}")
    lines.append(f"  date: {date_str}")
    url = safe_url(fields["url"], notes)
    if url:
        lines.append(f"  url: {post_lib.yaml_quote(url)}")
    headline = fields["headline"].strip()
    if headline:
        lines.append(f"  headline: {post_lib.yaml_quote(headline)}")
    if photo_path:
        lines.append(f"  image: {post_lib.yaml_quote(photo_path)}")
    if people:
        lines.append(f"  people: [{', '.join(people)}]")
    lines.append(f"  submitted_via_issue: {os.environ.get('ISSUE_NUMBER', '0')}")
    return "\n".join(lines) + "\n"


def build_featured_section(fields, date_str, outlet, image_path, links, notes):
    """Builds a Featured-story Markdown block matching the hand-written
    style already used elsewhere on the page (## heading, optional bold
    headline, optional description, then an image / highlights layout).
    Degrades gracefully: no image -> plain highlights list (no grid); no
    links -> image alone; neither -> just the heading and text.

    All free text is HTML-escaped before being embedded -- issue text is
    untrusted input, and this block is written straight into media.md,
    which is served as-is once a reviewer merges the resulting PR. URLs
    are pre-validated by the caller (safe_url), so href values here are
    already known to be plain http(s) links."""
    import datetime
    pretty_date = datetime.date.fromisoformat(date_str).strftime("%-d %B %Y")
    esc_outlet = html.escape(outlet)

    lines = [f"## {esc_outlet}, {pretty_date}", ""]

    headline = fields["headline"].strip()
    if headline:
        lines += [f"**{html.escape(headline)}**", ""]

    description = fields["description"].strip()
    if description:
        lines += [html.escape(description), ""]

    main_url = safe_url(fields["url"], notes)
    all_links = ([(esc_outlet, main_url)] if main_url else []) + [(html.escape(l), u) for l, u in links]

    if image_path and all_links:
        lines.append('<div class="media-feature">')
        lines.append(f'  <img class="media-feature-image" src="{{{{ site.baseurl }}}}{image_path}" alt="{esc_outlet}">')
        lines.append('  <div class="media-feature-highlights">')
        lines.append('    <p class="media-feature-highlights-label">Media highlights</p>')
        lines.append('    <ul>')
        for label, url in all_links:
            lines.append(f'      <li><a href="{html.escape(url)}">{label}</a></li>')
        lines.append('    </ul>')
        lines.append('  </div>')
        lines.append('</div>')
    elif image_path:
        lines.append(f'![{esc_outlet}]({{{{ site.baseurl }}}}{image_path})')
    elif all_links:
        lines.append('**Media highlights**')
        lines.append('')
        for label, url in all_links:
            lines.append(f'- [{label}]({url})')

    lines += ["", "---"]
    return "\n".join(lines) + "\n"


CARD_LINK_TEXT = {"Print": "Read the article", "TV": "Watch", "Radio": "Listen", "Podcast": "Listen"}

# A row of Featured cards, as written by build_featured_card_group -- the
# group's own tags sit at column 0 and everything inside is indented, so
# the first unindented </div> is always the group's end.
CARD_GROUP_RE = re.compile(r'<div class="media-feature-cards">\n(?P<cards>.*?)\n</div>', re.S)
CARD_OPEN = '  <article class="media-feature-card">'


def is_compact_feature(fields, other_links):
    """A Featured submission with nothing to it beyond an image, headline
    and one link would leave most of a full-width section empty, so it's
    shown as a half-width card instead (paired side by side with the next
    one). Anything with a description or extra links keeps the full
    section layout, which has room for them."""
    return not fields["description"].strip() and not other_links


def build_featured_card(fields, date_str, outlet, media_type, image_path, notes):
    """One card's HTML, indented to sit inside a media-feature-cards group.
    Plain HTML rather than Markdown (Markdown isn't parsed inside an HTML
    block), with all free text escaped -- issue text is untrusted input."""
    import datetime
    pretty_date = datetime.date.fromisoformat(date_str).strftime("%-d %B %Y")
    esc_outlet = html.escape(outlet)
    url = safe_url(fields["url"], notes)
    href = html.escape(url) if url else None
    headline = fields["headline"].strip()

    lines = [CARD_OPEN]
    if image_path:
        img = f'<img src="{{{{ site.baseurl }}}}{image_path}" alt="{esc_outlet}" loading="lazy">'
        lines.append(f'    <a class="media-feature-card-image" href="{href}">{img}</a>' if href
                     else f'    <span class="media-feature-card-image">{img}</span>')
    lines.append('    <div class="media-feature-card-body">')
    lines.append(f'      <h2>{esc_outlet}, {pretty_date}</h2>')
    if headline:
        lines.append(f'      <p class="media-feature-card-headline">{html.escape(headline)}</p>')
    if href:
        link_text = CARD_LINK_TEXT.get(media_type, "Find out more")
        lines.append(f'      <p class="media-feature-card-link"><a href="{href}">{link_text} →</a></p>')
    lines.append('    </div>')
    lines.append('  </article>')
    return "\n".join(lines)


def insert_featured_card(card_html, notes):
    """Inserts a card below FEATURED_INSERT_MARKER in media.md: into the
    card group directly below the marker if that group holds a single card
    (making a side-by-side pair, newest on the left), otherwise as a new
    group of its own. Returns (written, paired)."""
    with open(MEDIA_PAGE_PATH, "r", encoding="utf-8") as f:
        current = f.read()

    if FEATURED_INSERT_MARKER not in current:
        notes.append("Couldn't find the Featured-section insert marker in media.md -- "
                      "not added as a Featured section (the archive entry was still saved).")
        return False, False

    head, _, rest = current.partition(FEATURED_INSERT_MARKER)
    top = CARD_GROUP_RE.match(rest.lstrip("\n"))
    if top and top.group("cards").count(CARD_OPEN) == 1:
        rest = rest.lstrip("\n")
        rest = ('<div class="media-feature-cards">\n' + card_html + "\n" + top.group("cards")
                + "\n</div>" + rest[top.end():])
        new_content = head + FEATURED_INSERT_MARKER + "\n\n" + rest
        paired = True
    else:
        group = '<div class="media-feature-cards">\n' + card_html + "\n</div>\n\n---"
        new_content = head + FEATURED_INSERT_MARKER + "\n\n" + group + rest
        paired = False

    with open(MEDIA_PAGE_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)
    return True, paired


def insert_featured_section(section_md, notes):
    """Inserts section_md directly after FEATURED_INSERT_MARKER in
    media.md. Returns True if the marker was found and the file written."""
    with open(MEDIA_PAGE_PATH, "r", encoding="utf-8") as f:
        current = f.read()

    if FEATURED_INSERT_MARKER not in current:
        notes.append("Couldn't find the Featured-section insert marker in media.md -- "
                      "not added as a Featured section (the archive entry was still saved).")
        return False

    new_content = current.replace(
        FEATURED_INSERT_MARKER,
        FEATURED_INSERT_MARKER + "\n\n" + section_md.rstrip("\n"),
        1,
    )
    with open(MEDIA_PAGE_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)
    return True


def append_entry(entry_block, notes):
    """Appends entry_block to _data/media.yml as text, validating the
    result still parses as YAML before writing. Returns True if written."""
    try:
        from yaml import safe_load
    except ImportError:
        notes.append("YAML validation isn't available in this run -- entry not saved to _data/media.yml.")
        return False

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        current = f.read()

    new_content = current.rstrip("\n") + "\n\n" + entry_block + "\n"

    try:
        parsed = safe_load(new_content)
    except Exception as e:
        notes.append(f"The new entry didn't produce valid YAML ({e}) -- not saved to _data/media.yml.")
        return False
    if not isinstance(parsed, list) or len(parsed) < 1:
        notes.append("The new entry didn't parse as expected -- not saved to _data/media.yml.")
        return False

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)
    return True


def main():
    issue_number = os.environ.get("ISSUE_NUMBER", "0")
    issue_body = os.environ.get("ISSUE_BODY", "")
    issue_created_at = os.environ.get("ISSUE_CREATED_AT", "")
    summary_path = os.environ.get("NEW_MEDIA_SUMMARY_PATH", "/tmp/new_media_summary.md")
    manifest_path = os.environ.get("NEW_MEDIA_MANIFEST_PATH", "/tmp/new_media_manifest.json")

    if not issue_body or not issue_created_at:
        print("Missing ISSUE_BODY or ISSUE_CREATED_AT -- can't proceed.")
        sys.exit(1)

    fields = parse_issue_body(issue_body)
    notes = []

    outlet = fields["outlet"].strip()
    media_type = fields["type"].strip()
    if not outlet or media_type not in VALID_TYPES:
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("This submission is missing an outlet name or a valid type, both required -- "
                    "please try submitting the form again with those filled in.\n")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({"data_file": None, "images": [], "outlet": None}, f)
        print("Fatal: missing outlet or invalid type.")
        sys.exit(1)

    date_str = post_lib.resolve_date(fields["date"].strip(), issue_created_at, notes)

    is_featured = checkbox_checked(fields["feature"])

    photo_path = None
    saved_images = []
    if checkbox_checked(fields["consent"]):
        photo_urls = post_lib.extract_photo_urls(fields["photo"], notes)
        if photo_urls:
            raw = post_lib.download_image(photo_urls[0], notes)
            if raw is not None:
                data, ext = post_lib.process_image(raw, notes)
                if data is not None:
                    year, month = date_str[:4], date_str[5:7]
                    upload_dir = os.path.join(UPLOADS_ROOT, year, month)
                    os.makedirs(upload_dir, exist_ok=True)
                    slug = post_lib.slugify(outlet)
                    filename = f"media-{slug}-issue{issue_number}-1.{ext}"
                    with open(os.path.join(upload_dir, filename), "wb") as f:
                        f.write(data)
                    photo_path = f"/wp-content/uploads/{year}/{month}/{filename}"
                    saved_images.append(os.path.relpath(os.path.join(upload_dir, filename), post_lib.REPO_ROOT))
    elif fields["photo"].strip():
        notes.append("A photo was attached but the permission checkbox wasn't ticked -- photo skipped.")

    people = resolve_people(fields["people"], notes)
    entry_block = build_entry_block(fields, date_str, photo_path, people, notes)
    saved_to_data = append_entry(entry_block, notes)

    added_to_media_page = False
    featured_note = None
    if is_featured:
        other_links = parse_other_links(fields["other_links"], notes)
        if is_compact_feature(fields, other_links):
            card_html = build_featured_card(fields, date_str, outlet, media_type, photo_path, notes)
            added_to_media_page, paired = insert_featured_card(card_html, notes)
            featured_note = ("- Added as a Featured card on the Media page, side by side with the one below it."
                             if paired else
                             "- Added as a Featured card on the Media page (it'll sit side by side with the "
                             "next short featured entry).")
        else:
            section_md = build_featured_section(fields, date_str, outlet, photo_path, other_links, notes)
            added_to_media_page = insert_featured_section(section_md, notes)
            featured_note = "- Added as a Featured section on the Media page."

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({
            "data_file": os.path.relpath(DATA_PATH, post_lib.REPO_ROOT) if saved_to_data else None,
            "media_page": os.path.relpath(MEDIA_PAGE_PATH, post_lib.REPO_ROOT) if added_to_media_page else None,
            "images": saved_images if (saved_to_data or added_to_media_page) else [],
            "outlet": outlet,
        }, f)

    summary_lines = [f"New media entry: **{outlet}** ({media_type}, {date_str})"]
    if saved_to_data:
        summary_lines.append("- Added to `_data/media.yml`.")
    if added_to_media_page:
        summary_lines.append(featured_note)
    if saved_images:
        summary_lines.append(f"- Photo: `{saved_images[0]}`.")
    if people and saved_to_data:
        summary_lines.append(f"- Lab members shown: {', '.join(f'`{s}`' for s in people)}.")
    if notes:
        summary_lines.append("")
        summary_lines.append("Notes from processing this submission:")
        summary_lines += [f"- {n}" for n in notes]
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(summary_lines) + "\n")

    print(f"Processed media entry for {outlet!r}, saved_to_data={saved_to_data}, "
          f"featured={added_to_media_page}, photo={bool(saved_images)}.")


if __name__ == "__main__":
    main()
