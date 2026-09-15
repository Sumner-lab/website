#!/usr/bin/env python3
"""Refresh Scopus publication list.

Scopus author pages require a login, so the scheduled workflow uses the
Elsevier Scopus API instead. The API key is supplied as a GitHub Actions
secret and is never written to the repository.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PEOPLE_DIR = os.path.join(REPO_ROOT, "_people")
DATA_DIR = os.path.join(REPO_ROOT, "_data", "people")
API_URL = "https://api.elsevier.com/content/search/scopus"
PAGE_SIZE = 25
SCOPUS_ID_RE = r"\d+"


def fetch_page(api_key, author_id, start):
    query = urllib.parse.urlencode({
        "query": f"AU-ID({author_id})",
        "start": start,
        "count": PAGE_SIZE,
        "view": "COMPLETE",
    })
    request = urllib.request.Request(
        f"{API_URL}?{query}",
        headers={
            "Accept": "application/json",
            "X-ELS-APIKey": api_key,
            "User-Agent": "SumnerLabWebsiteBot/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def configured_people():
    people = []
    for filename in sorted(os.listdir(PEOPLE_DIR)):
        if not filename.endswith(".md"):
            continue
        path = os.path.join(PEOPLE_DIR, filename)
        with open(path, encoding="utf-8") as source:
            frontmatter = source.read().split("\n---", 1)[0]
        match = re.search(r"^scopus_author_id:\s*[\"']?(" + SCOPUS_ID_RE + r")[\"']?\s*$", frontmatter, re.MULTILINE)
        if match:
            people.append({
                "slug": filename[:-3],
                "name": re.search(r"^name:\s*(.+)$", frontmatter, re.MULTILINE).group(1).strip('"\''),
                "author_id": match.group(1),
            })
    return people


def value(entry, key, default=""):
    raw = entry.get(key, default)
    return raw if isinstance(raw, (str, int, float)) else default


def is_article_or_preprint(entry):
    subtype = str(value(entry, "subtypeDescription")).lower()
    publication = str(value(entry, "prism:publicationName")).lower()
    preprint_server = any(server in publication for server in ("biorxiv", "medrxiv", "arxiv"))
    return subtype == "article" or preprint_server


def normalise_entry(entry):
    doi = str(value(entry, "prism:doi")).strip()
    scopus_id = str(value(entry, "dc:identifier")).replace("SCOPUS_ID:", "").strip()
    link = f"https://doi.org/{doi}" if doi else f"https://www.scopus.com/record/display.uri?eid=2-s2.0-{scopus_id}"
    cover_date = str(value(entry, "prism:coverDate"))
    return {
        "title": str(value(entry, "dc:title")).strip(),
        "authors": str(value(entry, "dc:creator")).strip(),
        "journal": str(value(entry, "prism:publicationName")).strip(),
        "year": int(cover_date[:4]) if cover_date[:4].isdigit() else None,
        "date": cover_date,
        "doi": doi,
        "url": link,
        "document_type": str(value(entry, "subtypeDescription")).strip() or "Article",
        "citations": int(value(entry, "citedby-count", "0") or 0),
    }


def main():
    api_key = os.environ.get("SCOPUS_API_KEY", "").strip()
    if not api_key:
        print("SCOPUS_API_KEY is not set; leaving the Scopus data unchanged.")
        return 0

    people = configured_people()
    if not people:
        print("No people have a scopus_author_id in their front matter.")
        return 0

    os.makedirs(DATA_DIR, exist_ok=True)
    failures = 0
    for person in people:
        entries = []
        start = 0
        total = None
        try:
            while total is None or start < total:
                feed = fetch_page(api_key, person["author_id"], start).get("search-results", {})
                total = int(feed.get("opensearch:totalResults", 0))
                page = [entry for entry in feed.get("entry", []) if is_article_or_preprint(entry)]
                entries.extend(normalise_entry(entry) for entry in page)
                start += PAGE_SIZE
                if not page and not feed.get("entry"):
                    break
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as error:
            print(f"Could not refresh Scopus publications for {person['name']}: {error}", file=sys.stderr)
            failures += 1
            continue

        entries.sort(key=lambda item: item["date"], reverse=True)
        data = {
            "updated": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "name": person["name"],
            "author_id": person["author_id"],
            "profile_url": f"https://www.scopus.com/authid/detail.uri?authorId={person['author_id']}",
            "publications": entries,
        }
        output_path = os.path.join(DATA_DIR, f"scopus_{person['slug']}.json")
        with open(output_path, "w", encoding="utf-8") as output:
            json.dump(data, output, indent=2, ensure_ascii=False)
            output.write("\n")
        print(f"Wrote {len(entries)} Scopus articles/preprints for {person['name']} to {output_path}.")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())