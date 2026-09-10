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


def build_entry_block(fields, date_str, photo_path, notes):
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

    entry_block = build_entry_block(fields, date_str, photo_path, notes)
    saved_to_data = append_entry(entry_block, notes)

    added_to_media_page = False
    if is_featured:
        other_links = parse_other_links(fields["other_links"], notes)
        section_md = build_featured_section(fields, date_str, outlet, photo_path, other_links, notes)
        added_to_media_page = insert_featured_section(section_md, notes)

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
        summary_lines.append("- Added as a Featured section on the Media page.")
    if saved_images:
        summary_lines.append(f"- Photo: `{saved_images[0]}`.")
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
