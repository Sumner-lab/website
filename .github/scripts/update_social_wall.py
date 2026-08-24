#!/usr/bin/env python3
"""Pulls recent #sumnerlabucl posts from Bluesky and writes
_data/social_wall.json, which _includes/social-wall.html renders at build
time.

Bluesky's public unauthenticated AppView (public.api.bsky.app) hard-blocks
cloud/datacenter IPs -- including GitHub Actions runners -- with a flat 403
("Request forbidden by administrative rules") on effectively every request,
confirmed across 10+ scheduled runs that all "succeeded" but never actually
got data. Authenticating (BSKY_HANDLE + BSKY_APP_PASSWORD env vars, an app
password from Settings -> Privacy and Security -> App Passwords, NOT the
account's real password) routes calls through the account's own session
instead of the anonymous path, which isn't subject to that block.

Falls back to the unauthenticated endpoint if no credentials are set, so
this still runs (best-effort) before that's configured. Retries a handful of
times either way; if every attempt still fails, this leaves the existing
data file untouched (exit 0, no write) so the site always keeps showing the
last good fetch rather than going blank.

HASHTAG below must match the data-hashtag attribute in
_includes/social-wall.html.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HASHTAG = "sumnerlabucl"
PUBLIC_API_BASE = "https://public.api.bsky.app/xrpc"
AUTH_API_BASE = "https://bsky.social/xrpc"
USER_AGENT = "SumnerLabWebsiteBot/1.0 (+https://sumner-lab.github.io/website/; fetches the #sumnerlabucl social wall)"
POST_LIMIT = 9
FETCH_ATTEMPTS = 8
RETRY_SECONDS = 4

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
OUT_PATH = os.path.join(REPO_ROOT, "_data", "social_wall.json")

BSKY_HANDLE = os.environ.get("BSKY_HANDLE", "")
BSKY_APP_PASSWORD = os.environ.get("BSKY_APP_PASSWORD", "")

API_BASE = PUBLIC_API_BASE
access_token = None


def create_session():
    body = json.dumps({"identifier": BSKY_HANDLE, "password": BSKY_APP_PASSWORD}).encode()
    req = urllib.request.Request(
        f"{AUTH_API_BASE}/com.atproto.server.createSession",
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())["accessJwt"]


if BSKY_HANDLE and BSKY_APP_PASSWORD:
    try:
        access_token = create_session()
        API_BASE = AUTH_API_BASE
        print(f"Authenticated to Bluesky as {BSKY_HANDLE}.")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"Couldn't create a Bluesky session ({e}) -- falling back to the "
              f"public unauthenticated API.")
else:
    print("BSKY_HANDLE / BSKY_APP_PASSWORD not set -- using the public "
          "unauthenticated API (less reliable from cloud IPs).")


def fetch_json(url):
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def fetch_json_with_retries(url, attempts=FETCH_ATTEMPTS):
    last_err = None
    for i in range(attempts):
        try:
            return fetch_json(url)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last_err = e
            if i < attempts - 1:
                time.sleep(RETRY_SECONDS)
    raise last_err


def get_thumb(embed):
    """Pulls a preview image out of any embed shape Bluesky returns,
    including a quote post -- where the picture belongs to the *quoted*
    post, nested under embed.record.embeds, not the top-level embed."""
    if not embed:
        return None
    t = embed.get("$type")
    if t == "app.bsky.embed.images#view":
        images = embed.get("images") or []
        return images[0]["thumb"] if images else None
    if t == "app.bsky.embed.gallery#view":
        items = embed.get("items") or []
        return items[0]["thumbnail"] if items else None
    if t == "app.bsky.embed.video#view":
        return embed.get("thumbnail")
    if t == "app.bsky.embed.external#view":
        external = embed.get("external") or {}
        return external.get("thumb")
    if t == "app.bsky.embed.record#view":
        record = embed.get("record") or {}
        embeds = record.get("embeds") or []
        return get_thumb(embeds[0]) if embeds else None
    if t == "app.bsky.embed.recordWithMedia#view":
        media_thumb = get_thumb(embed.get("media"))
        if media_thumb:
            return media_thumb
        record = (embed.get("record") or {}).get("record") or {}
        embeds = record.get("embeds") or []
        return get_thumb(embeds[0]) if embeds else None
    return None


def fetch_posts_by_uri(uris):
    """Batch-fetches full post views for the given at:// URIs, chunked to
    the API's 25-per-request cap. Returns {uri: postView}. Best-effort: if
    this fails, callers just fall back to having no borrowed image."""
    result = {}
    uris = [u for u in uris if u]
    for i in range(0, len(uris), 25):
        chunk = uris[i : i + 25]
        qs = urllib.parse.urlencode({"uris": chunk}, doseq=True)
        try:
            data = fetch_json(f"{API_BASE}/app.bsky.feed.getPosts?{qs}")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            print(f"Note: couldn't fetch parent/root posts for image lookup ({e}); "
                  f"affected posts will render without a borrowed image.")
            continue
        for post in data.get("posts", []):
            result[post["uri"]] = post
    return result


search_url = (
    f"{API_BASE}/app.bsky.feed.searchPosts?"
    f"q={urllib.parse.quote('#' + HASHTAG, safe='')}&sort=latest&limit={POST_LIMIT}"
)

try:
    search_data = fetch_json_with_retries(search_url)
except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
    print(f"Bluesky search API didn't succeed after {FETCH_ATTEMPTS} attempts ({e}). "
          f"Leaving existing {OUT_PATH} untouched -- the site keeps showing the last "
          f"good fetch.")
    sys.exit(0)

raw_posts = search_data.get("posts", [])

# A reply that quotes/mentions the hashtag often doesn't carry its own photo
# -- the photo is on an earlier post in the same thread (the reply's parent,
# or the thread root). Batch-fetch those so we can borrow the image instead
# of showing a text-only card when a picture exists just one hop away.
needed_uris = set()
for post in raw_posts:
    if get_thumb(post.get("embed")):
        continue
    reply = (post.get("record") or {}).get("reply")
    if reply:
        needed_uris.add((reply.get("parent") or {}).get("uri"))
        needed_uris.add((reply.get("root") or {}).get("uri"))

related_posts = fetch_posts_by_uri(needed_uris) if needed_uris else {}

out_posts = []
for post in raw_posts:
    author = post.get("author") or {}
    record = post.get("record") or {}
    handle = author.get("handle")
    if not handle:
        continue

    thumb = get_thumb(post.get("embed"))
    if not thumb:
        reply = record.get("reply")
        if reply:
            parent_uri = (reply.get("parent") or {}).get("uri")
            root_uri = (reply.get("root") or {}).get("uri")
            # Prefer the thread's opening post over the immediate parent --
            # the first post is usually the one carrying the photo the rest
            # of the thread is talking about, even several replies deep.
            root_post = related_posts.get(root_uri)
            if root_post:
                thumb = get_thumb(root_post.get("embed"))
            if not thumb and parent_uri != root_uri:
                parent_post = related_posts.get(parent_uri)
                if parent_post:
                    thumb = get_thumb(parent_post.get("embed"))

    embed = post.get("embed") or {}
    quoting_handle = None
    if embed.get("$type") == "app.bsky.embed.record#view":
        quoting_handle = ((embed.get("record") or {}).get("author") or {}).get("handle")

    rkey = post["uri"].rstrip("/").split("/")[-1]
    out_posts.append(
        {
            "url": f"https://bsky.app/profile/{handle}/post/{rkey}",
            "handle": f"@{handle}",
            "text": record.get("text", ""),
            "date": record.get("createdAt"),
            "image": thumb,
            "quoting": quoting_handle,
        }
    )

existing_posts = None
if os.path.exists(OUT_PATH):
    with open(OUT_PATH) as f:
        existing_posts = json.load(f).get("posts")

if out_posts == existing_posts:
    print("No change in social wall posts -- leaving the data file (and its "
          "'updated' timestamp) as-is.")
    sys.exit(0)

data = {
    "hashtag": HASHTAG,
    "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "posts": out_posts,
}

os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
with open(OUT_PATH, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")

with_image = sum(1 for p in out_posts if p["image"])
print(f"Wrote {OUT_PATH}: {len(out_posts)} posts ({with_image} with an image)")
