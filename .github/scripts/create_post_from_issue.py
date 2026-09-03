#!/usr/bin/env python3
"""Turns one "Submit a new post" issue-form submission into a real
_posts/*.md file (plus any attached, resized photos), for
new-post-submission.yml to commit and open as a PR.

Reads the raw issue body from the ISSUE_BODY env var (never interpolated
into a shell command by the caller -- issue text is untrusted input, and
substituting it into bash is a real injection vector) and writes:

- The new _posts/YYYY-MM-DD-slug.md file, directly under _posts/.
- Any successfully processed photos, directly under wp-content/uploads/.
- A manifest JSON (NEW_POST_MANIFEST_PATH) listing exactly the paths
  written, so the workflow's `git add` only stages what this script
  actually created -- never `git add -A`.
- A plain-English summary (NEW_POST_SUMMARY_PATH) of what happened,
  including anything skipped and why, for the workflow to use as the PR
  body and the comment posted back on the originating issue.

Exit 0 even when some non-essential part of the submission was skipped
(a bad date, a photo that failed to download) -- those are noted in the
summary, not fatal. Exit 1 only when the post itself can't be built at
all (missing title/body, or an unexpected internal failure) -- nothing
here reaches `main` without a human reviewing the resulting PR, so a
loud failure is just useful signal for the calling workflow to relay
back to the submitter, not a risk to the live site.
"""
import io
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POSTS_DIR = os.path.join(REPO_ROOT, "_posts")
UPLOADS_ROOT = os.path.join(REPO_ROOT, "wp-content", "uploads")

USER_AGENT = ("SumnerLabWebsiteBot/1.0 (+https://sumner-lab.github.io/website/; "
              "fetches photos attached to new-post issue submissions)")

MAX_PHOTOS = 5
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_LONG_EDGE = 1600
TARGET_MAX_BYTES = 500 * 1024
JPEG_QUALITY_STEPS = [82, 72, 62]

# Must exactly match the `label:` strings in
# .github/ISSUE_TEMPLATE/new-post.yml -- GitHub renders each field as a
# "### <label>" heading in the issue body, in field order, and that's the
# only way this script has to find them back (the webhook payload gives
# the whole body as one string, not a field id -> value map).
FIELD_LABELS = {
    "title": "Post title",
    "author": "Your name",
    "publish_date": "Publish date (optional)",
    "body": "Post content",
    "photos": "Photos (optional)",
}

IMG_RE = re.compile(
    r'!\[[^\]]*\]\((https://(?:github\.com/user-attachments/assets'
    r'|user-images\.githubusercontent\.com)/[^\)\s]+)\)'
)


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


def slugify(title, max_len=80):
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    text = re.sub(r"-{2,}", "-", text)
    if len(text) > max_len:
        text = text[:max_len].rsplit("-", 1)[0].strip("-")
    return text or "post"


def resolve_date(publish_date, issue_created_at, notes):
    if publish_date:
        try:
            return datetime.strptime(publish_date, "%Y-%m-%d").date().isoformat()
        except ValueError:
            notes.append(f"\"{publish_date}\" isn't a valid date (expected YYYY-MM-DD) "
                          f"-- used today's date instead.")
    return datetime.fromisoformat(issue_created_at.replace("Z", "+00:00")).date().isoformat()


def yaml_quote(s):
    """Matches the quoting style already used across _posts/*.md titles
    that contain a colon or other YAML-significant character."""
    if re.search(r'[:#\[\]{}&*!|>\'"%@`]', s) or s.strip() != s:
        return "'" + s.replace("'", "''") + "'"
    return s


def extract_photo_urls(photos_field, notes):
    urls = IMG_RE.findall(photos_field)
    if photos_field and not urls:
        notes.append("The photos field had content but no recognizable image attachments -- "
                      "treated as no photos.")
    if len(urls) > MAX_PHOTOS:
        notes.append(f"{len(urls) - MAX_PHOTOS} extra photo(s) beyond the first {MAX_PHOTOS} "
                      f"were skipped.")
    return urls[:MAX_PHOTOS]


def download_image(url, notes):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read(MAX_IMAGE_BYTES + 1)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        notes.append(f"Couldn't download a photo ({e}) -- skipped.")
        return None
    if len(data) > MAX_IMAGE_BYTES:
        notes.append("A photo was too large (over 15MB) -- skipped.")
        return None
    return data


def process_image(raw_bytes, notes):
    """Returns (bytes, extension) or (None, None) if unusable. Re-encodes
    unconditionally (never byte-copies) -- besides resizing/compressing,
    this also strips EXIF, including GPS location, which Pillow drops by
    default unless explicitly re-attached. A real privacy plus for field
    photos, on top of the size goal."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        notes.append("Image processing isn't available in this run -- all photos skipped.")
        return None, None

    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img.load()
    except Exception as e:
        notes.append(f"A photo couldn't be read as an image ({e}) -- skipped.")
        return None, None

    img = ImageOps.exif_transpose(img)
    w, h = img.size
    if max(w, h) > MAX_LONG_EDGE:
        scale = MAX_LONG_EDGE / max(w, h)
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)

    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    if has_alpha:
        buf = io.BytesIO()
        img.convert("RGBA").save(buf, format="PNG", optimize=True)
        return buf.getvalue(), "png"

    img = img.convert("RGB")
    data = None
    for quality in JPEG_QUALITY_STEPS:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        data = buf.getvalue()
        if len(data) <= TARGET_MAX_BYTES:
            break
    return data, "jpg"


def unique_post_path(date_str, slug, issue_number):
    path = os.path.join(POSTS_DIR, f"{date_str}-{slug}.md")
    if not os.path.exists(path):
        return path
    return os.path.join(POSTS_DIR, f"{date_str}-{slug}-issue{issue_number}.md")


def build_post(fields, issue_number, issue_created_at, notes):
    title = fields["title"].strip()
    body_text = fields["body"].strip().replace("\r\n", "\n")
    if not title or not body_text:
        return None  # fatal, caller handles

    date_str = resolve_date(fields["publish_date"].strip(), issue_created_at, notes)
    slug = slugify(title)
    post_path = unique_post_path(date_str, slug, issue_number)

    photo_urls = extract_photo_urls(fields["photos"], notes)
    saved_images = []  # list of (repo-relative path)
    year, month = date_str[:4], date_str[5:7]
    for i, url in enumerate(photo_urls, start=1):
        raw = download_image(url, notes)
        if raw is None:
            continue
        data, ext = process_image(raw, notes)
        if data is None:
            continue
        upload_dir = os.path.join(UPLOADS_ROOT, year, month)
        os.makedirs(upload_dir, exist_ok=True)
        filename = f"{slug}-issue{issue_number}-{i}.{ext}"
        with open(os.path.join(upload_dir, filename), "wb") as f:
            f.write(data)
        saved_images.append(f"/wp-content/uploads/{year}/{month}/{filename}")

    front_matter = ["---", f"title: {yaml_quote(title)}"]
    if saved_images:
        front_matter.append(f"image: {saved_images[0]}")
    front_matter.append("---")

    body_parts = [f"<!-- Submitted via issue #{issue_number} -->"]
    author = fields["author"].strip()
    if author:
        body_parts.append(f"*By {author}*")
    body_parts.append(body_text)
    for img in saved_images[1:]:
        body_parts.append(f"![]({{{{ site.baseurl }}}}{img})")
    body = "\n\n".join(body_parts)

    # An innocent paste that happens to contain literal Liquid-looking
    # syntax would otherwise build fine in the PR diff but break the site
    # only after merge -- invisible until too late for a non-technical
    # submitter and reviewer alike. Auto-wrap rather than reject.
    if "{{" in body or "{%" in body:
        body = "{% raw %}\n" + body + "\n{% endraw %}"

    content = "\n".join(front_matter) + "\n" + body + "\n"
    os.makedirs(POSTS_DIR, exist_ok=True)
    with open(post_path, "w", encoding="utf-8") as f:
        f.write(content)

    return {
        "post": os.path.relpath(post_path, REPO_ROOT),
        "images": [os.path.relpath(os.path.join(UPLOADS_ROOT, p.split("/wp-content/uploads/", 1)[1]), REPO_ROOT)
                   for p in saved_images],
        "title": title,
        "photo_count": len(saved_images),
        "photo_attempted": len(photo_urls),
    }


def main():
    issue_number = os.environ.get("ISSUE_NUMBER", "0")
    issue_body = os.environ.get("ISSUE_BODY", "")
    issue_created_at = os.environ.get("ISSUE_CREATED_AT", "")
    summary_path = os.environ.get("NEW_POST_SUMMARY_PATH", "/tmp/new_post_summary.md")
    manifest_path = os.environ.get("NEW_POST_MANIFEST_PATH", "/tmp/new_post_manifest.json")

    if not issue_body or not issue_created_at:
        print("Missing ISSUE_BODY or ISSUE_CREATED_AT -- can't proceed.")
        sys.exit(1)

    fields = parse_issue_body(issue_body)
    notes = []

    if not fields["title"].strip() or not fields["body"].strip():
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("This submission is missing a title or post content, both required -- "
                    "please try submitting the form again with those filled in.\n")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({"post": None, "images": []}, f)
        print("Fatal: missing title or body.")
        sys.exit(1)

    result = build_post(fields, issue_number, issue_created_at, notes)
    if result is None:
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("Something went wrong building this post -- please check the workflow run log.\n")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({"post": None, "images": []}, f)
        print("Fatal: build_post returned None unexpectedly.")
        sys.exit(1)

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({"post": result["post"], "images": result["images"], "title": result["title"]}, f)

    summary_lines = [f"New post: **{result['title']}**", "", f"- File: `{result['post']}`"]
    if result["photo_attempted"]:
        summary_lines.append(f"- Photos: {result['photo_count']} of {result['photo_attempted']} "
                              f"attached photo(s) processed successfully.")
    if notes:
        summary_lines.append("")
        summary_lines.append("Notes from processing this submission:")
        summary_lines += [f"- {n}" for n in notes]
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(summary_lines) + "\n")

    print(f"Wrote {result['post']} with {result['photo_count']} photo(s).")


if __name__ == "__main__":
    main()
