#!/usr/bin/env python3
"""Grows publications.md and writes _data/wider_publications.json from
ORCID + Crossref data.

publications.md lists every paper co-authored by Seirian Sumner (ORCID
0000-0003-0213-2018) -- this script fetches her ORCID works, finds any
whose DOI isn't already present anywhere in the file, and appends a new
citation line under the right "## YEAR" heading. It NEVER rewrites,
reflows or removes an existing line -- see assert_additive() below, which
refuses to write if that ever stops being true.

_data/wider_publications.json feeds _includes/latest-publications.html on
publications/wider.md: the 20 most recent papers found across every
CURRENT lab member's ORCID record (from the `links:` entry labeled ORCID
in their _people/*.md front matter) that AREN'T already covered by
publications.md -- i.e. work published without Sumner as a co-author,
which is the whole point of that page.

ORCID's public API requires an OAuth2 client-credentials token even for
public records (ORCID_CLIENT_ID / ORCID_CLIENT_SECRET env vars, from a
free "Public API" client registered at orcid.org/developer-tools).
ORCID's /works summary endpoint doesn't reliably include full author
lists, so each candidate DOI is enriched via Crossref (unauthenticated,
identified via CROSSREF_MAILTO for their "polite pool").

This never touches git -- the calling workflow does the diff/PR. Unlike
update_analytics.py / update_social_wall.py (which push straight to main
and so always exit 0 to avoid ever breaking the live site on a bad run),
this one exits 1 on a failure that would prevent it from doing its job at
all (no ORCID token, publications.md not in the expected shape) --
nothing here reaches main without a human merging the PR, so a loud
failed Action run is just useful signal, not risk. A single person's
ORCID fetch failing, or a single DOI's Crossref lookup failing, is
logged and skipped rather than aborting the whole run.
"""
import glob
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
PUBLICATIONS_PATH = os.path.join(REPO_ROOT, "publications.md")
PEOPLE_DIR = os.path.join(REPO_ROOT, "_people")
OUT_PATH = os.path.join(REPO_ROOT, "_data", "wider_publications.json")

ORCID_TOKEN_URL = "https://orcid.org/oauth/token"
ORCID_API_BASE = "https://pub.orcid.org/v3.0"
CROSSREF_API_BASE = "https://api.crossref.org/works"
CROSSREF_MAILTO = "s.sumner@ucl.ac.uk"
USER_AGENT = f"SumnerLabWebsiteBot/1.0 (mailto:{CROSSREF_MAILTO}; +https://sumner-lab.github.io/website/)"

SEIRIAN_ORCID = "0000-0003-0213-2018"
# publications.md has never listed a preprint, even historically (it's
# framed as peer-reviewed papers/book chapters/etc.) -- keep excluding
# them there. The wider-lab digest has no such "peer-reviewed only"
# framing and exists to showcase current members' work, so it allows
# preprints through; both still exclude non-paper record types.
NON_PAPER_TYPES = {"dataset", "data_set", "working_paper", "other", "annotation"}
MAIN_LIST_EXCLUDED_TYPES = NON_PAPER_TYPES | {"preprint"}
WIDER_LIST_EXCLUDED_TYPES = NON_PAPER_TYPES
MIN_CANDIDATE_YEAR = datetime.now(timezone.utc).year - 2
WIDER_LIST_SIZE = 20
CROSSREF_SLEEP_SECONDS = 0.3

ORCID_CLIENT_ID = os.environ.get("ORCID_CLIENT_ID", "")
ORCID_CLIENT_SECRET = os.environ.get("ORCID_CLIENT_SECRET", "")


# ---------------------------------------------------------------------------
# _people/*.md front matter -- a minimal hand-rolled parser, not a general
# YAML parser. Deliberately narrow to the shapes actually used in this
# repo (flat scalars, plus `links:` as a list of {label, url} dicts) so we
# don't need a PyYAML dependency, matching the stdlib-only convention of
# update_analytics.py / update_social_wall.py.
# ---------------------------------------------------------------------------

def _unquote(s):
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def parse_frontmatter(text):
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    data = {}
    current_list_key = None
    current_item = None
    for raw_line in text[4:end].splitlines():
        if not raw_line.strip():
            continue
        if raw_line.startswith("  - "):
            item_text = raw_line[4:]
            if ":" in item_text:
                current_item = {}
                data.setdefault(current_list_key, []).append(current_item)
                k, _, v = item_text.partition(":")
                current_item[k.strip()] = _unquote(v.strip())
            else:
                current_item = None
                data.setdefault(current_list_key, []).append(_unquote(item_text.strip()))
        elif raw_line.startswith("    ") and current_item is not None:
            k, _, v = raw_line.strip().partition(":")
            current_item[k.strip()] = _unquote(v.strip())
        elif not raw_line.startswith(" "):
            k, _, v = raw_line.partition(":")
            key, val = k.strip(), v.strip()
            current_item = None
            if val == "":
                current_list_key = key
                data[key] = []
            else:
                current_list_key = None
                data[key] = _unquote(val)
    return data


ORCID_ID_RE = re.compile(r"^https://orcid\.org/(\d{4}-\d{4}-\d{4}-\d{3}[\dX])/?$")


def extract_orcid_id(frontmatter):
    for link in frontmatter.get("links", []):
        if isinstance(link, dict) and link.get("label", "").strip().lower() == "orcid":
            m = ORCID_ID_RE.match(link.get("url", "").strip())
            if m:
                return m.group(1)
            print(f"  Note: {frontmatter.get('name')} has an ORCID link that doesn't "
                  f"look like a valid ORCID iD ({link.get('url')!r}) -- skipping it.")
    return None


def load_people(people_dir):
    people = []
    for path in sorted(glob.glob(os.path.join(people_dir, "*.md"))):
        with open(path, encoding="utf-8") as f:
            fm = parse_frontmatter(f.read())
        name = fm.get("name") or fm.get("title")
        if not name:
            continue
        people.append({
            "name": name, "status": fm.get("status"), "orcid": extract_orcid_id(fm),
            "joined": fm.get("joined"), "left": fm.get("left"), "stints": fm.get("stints") or [],
        })
    return people


# ---------------------------------------------------------------------------
# Membership windows -- when was this person actually in the lab? Used to
# scope the wider-lab digest to work published during their time here, not
# their whole career. `joined`/`left` (or a `stints` list of the same, for
# people with more than one non-contiguous period) are free-text front
# matter fields, e.g. "2019" or "September 2024" -- only ever year or
# "Month Year" granularity in practice.
# ---------------------------------------------------------------------------

MONTH_NAMES = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def parse_loose_date(s, end_of_period=False):
    """Parses a free-text joined/left value into a (year, month) tuple.
    Missing month defaults to the start of the year for a lower bound, or
    the end of the year for an upper bound (end_of_period=True) -- these
    fields don't carry day-level precision, so comparisons are done at
    (year, month) granularity throughout."""
    if not s:
        return None
    year_m = re.search(r"\b(\d{4})\b", s)
    if not year_m:
        return None
    year = int(year_m.group(1))
    month = None
    for name, num in MONTH_NAMES.items():
        if re.search(rf"\b{name}\b", s, re.IGNORECASE):
            month = num
            break
    if month is None:
        month = 12 if end_of_period else 1
    return (year, month)


def membership_windows(person):
    """Returns [(start, end), ...] (year, month) tuples this person was
    actually in the lab -- `end` is None for a still-ongoing stint.
    Returns an empty list if there's no joined date recorded at all (via
    `stints` or a plain `joined` field): callers should treat that as
    "can't verify this person's dates" and exclude them, not assume
    unrestricted access to their whole publication record."""
    windows = []
    for stint in person.get("stints") or []:
        start = parse_loose_date(stint.get("joined"))
        if not start:
            continue
        end = parse_loose_date(stint.get("left"), end_of_period=True) if stint.get("left") else None
        windows.append((start, end))
    if windows:
        return windows
    start = parse_loose_date(person.get("joined"))
    if not start:
        return []
    end = parse_loose_date(person.get("left"), end_of_period=True) if person.get("left") else None
    return [(start, end)]


def in_membership_window(date_str, windows):
    year, month = int(date_str[:4]), int(date_str[5:7])
    for start, end in windows:
        if (year, month) < start:
            continue
        if end is not None and (year, month) > end:
            continue
        return True
    return False


# ---------------------------------------------------------------------------
# Lab-member name matching, for bolding co-authors who are (or were) in the
# lab. Best-effort: this only affects bold styling, never which papers get
# listed, so it's fine if it's occasionally wrong -- easy to eyeball-correct
# in the PR.
# ---------------------------------------------------------------------------

PARTICLES = {"de", "da", "do", "dos", "das", "van", "von", "der", "den", "di", "la", "le", "el", "al", "bin", "ibn"}


def split_name(full_name):
    parts = full_name.split()
    if not parts:
        return "", ""
    i = len(parts) - 1
    family_parts = [parts[i]]
    i -= 1
    while i > 0 and parts[i].lower() in PARTICLES:
        family_parts.insert(0, parts[i])
        i -= 1
    return parts[0], " ".join(family_parts)


def build_lab_member_index(people):
    orcid_index, family_index = {}, {}
    for p in people:
        given, family = split_name(p["name"])
        entry = {"name": p["name"], "given": given, "family": family}
        if p.get("orcid"):
            orcid_index[p["orcid"]] = entry
        family_index.setdefault(family.lower(), []).append(entry)
    return orcid_index, family_index


def _names_loosely_overlap(a, b):
    """Very loose sanity check -- does any (>1 char) token of `a` appear
    as a substring of any token of `b`, or vice versa? Not a real
    name-matching algorithm; only used to guard the ORCID-based match
    below against a mismatched publisher/Crossref record (observed in
    practice: a journal submitted the wrong author ORCID, which would
    otherwise make this script confidently bold a completely unrelated
    author's name as if they were a lab member)."""
    a_tokens = [t.lower() for t in re.split(r"[\s\-]+", a or "") if len(t) > 1]
    b_tokens = [t.lower() for t in re.split(r"[\s\-]+", b or "") if len(t) > 1]
    return any(t in bt or bt in t for t in a_tokens for bt in b_tokens)


def is_lab_member_author(author, orcid_index, family_index):
    if author.get("orcid") and author["orcid"] in orcid_index:
        member = orcid_index[author["orcid"]]
        author_name = f"{author.get('given', '')} {author.get('family', '')}".strip()
        if _names_loosely_overlap(author_name, member["name"]):
            return True
        print(f"    Note: Crossref lists ORCID {author['orcid']} for author "
              f"'{author_name}', but that ORCID belongs to '{member['name']}' "
              f"in _people -- the names don't overlap at all, so NOT treating "
              f"this as a lab-member match (likely a publisher metadata error).")
        # Falls through to name-based matching below rather than trusting
        # a clearly-mismatched ORCID.
    candidates = family_index.get((author.get("family") or "").lower())
    if not candidates:
        return False
    if len(candidates) == 1:
        return True
    # Multiple lab members share this surname (e.g. two people named
    # "Taylor") -- require a given-name initial match too. Reduces, but
    # can't fully eliminate, false positives from a coincidentally
    # matching initial belonging to someone else entirely.
    author_initial = (author.get("given") or "")[:1].lower()
    return any(c["given"][:1].lower() == author_initial for c in candidates if c["given"])


# ---------------------------------------------------------------------------
# Text cleanup -- Crossref (and occasionally ORCID) titles/journal names can
# carry embedded JATS/XML inline markup (e.g. "<scp>UK</scp>" for small
# caps, or <i>/<sub>/<sup>), including literal newlines and indentation
# from the source XML. This strips tags and collapses whitespace rather
# than trying to convert them to markdown -- simple and robust beats
# faithfully preserving inline formatting for a plain-text citation line.
# ---------------------------------------------------------------------------

TAG_RE = re.compile(r"<[^>]+>")


def clean_text(s):
    return re.sub(r"\s+", " ", TAG_RE.sub("", s or "")).strip()


# ---------------------------------------------------------------------------
# DOI helpers
# ---------------------------------------------------------------------------

DOI_RE = re.compile(r'10\.\d{4,9}/[^\s<>"\')\]]+')
TRAILING_JUNK = ".,;:)]}>*'\"’”"


def normalize_doi(raw):
    d = (raw or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if d.lower().startswith(prefix):
            d = d[len(prefix):]
            break
    while d and d[-1] in TRAILING_JUNK:
        d = d[:-1]
    return d.lower()


def extract_known_dois(text):
    return {normalize_doi(m.group(0)) for m in DOI_RE.finditer(text)}


# ---------------------------------------------------------------------------
# ORCID API
# ---------------------------------------------------------------------------

def get_orcid_token(client_id, client_secret):
    body = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
        "scope": "/read-public",
    }).encode()
    req = urllib.request.Request(
        ORCID_TOKEN_URL, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())["access_token"]


def fetch_orcid_works(orcid_id, token):
    req = urllib.request.Request(
        f"{ORCID_API_BASE}/{orcid_id}/works",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read()).get("group", [])


def summarize_group(group):
    """Pulls {doi, title, journal, type, year, date} out of one ORCID
    `group` entry. Returns None if it has no DOI, a title, or a usable
    year -- can't dedupe/enrich/place a work without those."""
    doi = None
    for ext in (group.get("external-ids") or {}).get("external-id") or []:
        if (ext.get("external-id-type") or "").lower() == "doi":
            doi = normalize_doi(ext.get("external-id-value"))
            break
    if not doi:
        return None
    summaries = group.get("work-summary") or []
    if not summaries:
        return None
    ws = summaries[0]
    title = clean_text((((ws.get("title") or {}).get("title") or {}).get("value")))
    journal = clean_text((ws.get("journal-title") or {}).get("value"))
    work_type = (ws.get("type") or "").strip().lower().replace("-", "_")
    pub_date = ws.get("publication-date") or {}
    year_raw = (pub_date.get("year") or {}).get("value")
    month_raw = (pub_date.get("month") or {}).get("value") or "1"
    day_raw = (pub_date.get("day") or {}).get("value") or "1"
    try:
        year, month, day = int(year_raw), int(month_raw), int(day_raw)
    except (TypeError, ValueError):
        return None
    return {"doi": doi, "title": title, "journal": journal, "type": work_type,
            "year": year, "date": f"{year:04d}-{month:02d}-{day:02d}"}


# ---------------------------------------------------------------------------
# Crossref API
# ---------------------------------------------------------------------------

def _orcid_id_from_url(url):
    m = re.search(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dX])", url or "")
    return m.group(1) if m else None


def _resolve_crossref_date(msg):
    for key in ("published-print", "published-online", "issued", "published"):
        parts = ((msg.get(key) or {}).get("date-parts") or [[]])[0]
        if parts:
            try:
                year = int(parts[0])
            except (TypeError, ValueError):
                continue
            month = int(parts[1]) if len(parts) > 1 and parts[1] else 1
            day = int(parts[2]) if len(parts) > 2 and parts[2] else 1
            return year, month, day
    return None, None, None


def fetch_crossref_work(doi):
    url = f"{CROSSREF_API_BASE}/{urllib.parse.quote(doi, safe='/')}?mailto={urllib.parse.quote(CROSSREF_MAILTO)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"    Crossref lookup failed for {doi}: {e} -- skipping this paper.")
        return None

    msg = data.get("message") or {}
    authors = []
    for a in msg.get("author") or []:
        family = (a.get("family") or "").strip()
        if not family:
            continue
        authors.append({"given": (a.get("given") or "").strip(), "family": family,
                         "orcid": _orcid_id_from_url(a.get("ORCID"))})
    if not authors:
        print(f"    Crossref record for {doi} has no author list -- skipping this paper.")
        return None

    year, month, day = _resolve_crossref_date(msg)
    if year is None:
        print(f"    Crossref record for {doi} has no usable publication date -- skipping this paper.")
        return None

    titles = msg.get("title") or []
    containers = msg.get("container-title") or []
    # Preprints have no container-title (no journal) -- Crossref instead
    # names the preprint server (bioRxiv, medRxiv, ...) under `institution`.
    # Fall back to that so a preprint doesn't render with a blank venue.
    institutions = msg.get("institution") or []
    journal = containers[0] if containers else (institutions[0].get("name") if institutions else "")
    return {
        "doi": doi,
        "title": clean_text(titles[0]) if titles else "",
        "journal": clean_text(journal),
        "authors": authors,
        "volume": msg.get("volume"),
        "issue": msg.get("issue"),
        "pages": msg.get("page"),
        "year": year,
        "date": f"{year:04d}-{month:02d}-{day:02d}",
    }


# ---------------------------------------------------------------------------
# Citation formatting for new publications.md lines
# ---------------------------------------------------------------------------

def given_name_initials(given):
    return "".join(p[0] for p in re.split(r"[\s\-]+", given or "") if p).upper()


def format_author(author, is_member):
    s = f"{author['family']} {given_name_initials(author.get('given'))}".strip()
    return f"**{s}**" if is_member else s


def format_citation_line(work, orcid_index, family_index):
    rendered = [format_author(a, is_lab_member_author(a, orcid_index, family_index)) for a in work["authors"]]
    author_str = rendered[0] if len(rendered) == 1 else ", ".join(rendered[:-1]) + " & " + rendered[-1]

    vol_issue = ""
    if work.get("volume"):
        vol_issue = str(work["volume"]) + (f"({work['issue']})" if work.get("issue") else "")
    tail = f"***{work['journal']}***" if work.get("journal") else "***[journal unknown]***"
    extra = ", ".join(p for p in (vol_issue, work.get("pages")) if p)
    tail += f", {extra}." if extra else "."

    doi_url = f"https://doi.org/{work['doi']}"
    title = work["title"] or "[title unknown]"
    return (f"- {author_str} {work['year']}. {title}. {tail} "
            f'<a href="{doi_url}" target="_blank" rel="noreferrer noopener">{doi_url}</a>')


# ---------------------------------------------------------------------------
# publications.md editing -- strictly additive
# ---------------------------------------------------------------------------

YEAR_HEADING_RE = re.compile(r'^## +(\d{4}) *$', re.MULTILINE)
BULLET_RE = re.compile(r'^- ')


def split_into_sections(text):
    matches = list(YEAR_HEADING_RE.finditer(text))
    if not matches:
        return text, {}
    preamble = text[:matches[0].start()]
    sections = {}
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        heading_end = text.find("\n", start) + 1
        sections[m.group(1)] = [text[start:heading_end], text[heading_end:end]]
    return preamble, sections


def append_to_section(body, new_lines):
    lines = body.splitlines(keepends=True)
    bullet_idxs = [i for i, l in enumerate(lines) if BULLET_RE.match(l)]
    if not bullet_idxs:
        raise ValueError("section has no existing bullet lines -- refusing to guess an insertion point")
    insert_at = bullet_idxs[-1] + 1
    normalized = [l if l.endswith("\n") else l + "\n" for l in new_lines]
    return "".join(lines[:insert_at] + normalized + lines[insert_at:])


def insert_entries(text, new_by_year):
    preamble, sections = split_into_sections(text)
    if not sections:
        raise ValueError("no '## YEAR' headings found in publications.md -- refusing to edit it")
    for year, bullets in new_by_year.items():
        if year in sections:
            sections[year][1] = append_to_section(sections[year][1], bullets)
        else:
            body = "\n" + "".join((b if b.endswith("\n") else b + "\n") for b in bullets) + "\n"
            sections[year] = [f"## {year}\n", body]
    ordered_years = sorted(sections, key=int, reverse=True)
    return preamble + "".join(sections[y][0] + sections[y][1] for y in ordered_years)


def assert_additive(old_text, new_text):
    """Last-line-of-defense: every line in the old file must still appear,
    in the same relative order, in the new one. Raises if not -- this
    should be structurally impossible given insert_entries() only ever
    appends, but it costs nothing to check before writing to a real,
    human-maintained public page."""
    old_lines, new_lines = old_text.splitlines(), new_text.splitlines()
    it = iter(new_lines)
    for old_line in old_lines:
        for candidate in it:
            if candidate == old_line:
                break
        else:
            raise AssertionError(
                "Refusing to write publications.md: the edit would remove or "
                "reorder existing content, which should never happen.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not ORCID_CLIENT_ID or not ORCID_CLIENT_SECRET:
        print("ORCID_CLIENT_ID / ORCID_CLIENT_SECRET are not set -- can't authenticate "
              "to the ORCID API. See the ORCID Public API setup instructions.")
        sys.exit(1)

    try:
        token = get_orcid_token(ORCID_CLIENT_ID, ORCID_CLIENT_SECRET)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"Couldn't get an ORCID access token: {e}")
        sys.exit(1)

    people = load_people(PEOPLE_DIR)
    orcid_index, family_index = build_lab_member_index(people)

    with open(PUBLICATIONS_PATH, encoding="utf-8") as f:
        original_text = f.read()
    known_dois = extract_known_dois(original_text)

    # --- Part A: grow publications.md from Seirian's ORCID record ---
    print(f"Fetching Seirian Sumner's ORCID works ({SEIRIAN_ORCID})...")
    try:
        sumner_groups = fetch_orcid_works(SEIRIAN_ORCID, token)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"Couldn't fetch Seirian Sumner's ORCID works: {e}")
        sys.exit(1)

    new_by_year = {}
    added, skipped = [], []
    for group in sumner_groups:
        summary = summarize_group(group)
        if not summary:
            continue
        if summary["doi"] in known_dois:
            continue
        if summary["type"] in MAIN_LIST_EXCLUDED_TYPES:
            continue
        if summary["year"] < MIN_CANDIDATE_YEAR:
            continue
        work = fetch_crossref_work(summary["doi"])
        time.sleep(CROSSREF_SLEEP_SECONDS)
        if not work:
            skipped.append(summary["doi"])
            continue
        line = format_citation_line(work, orcid_index, family_index)
        new_by_year.setdefault(str(work["year"]), []).append(line)
        known_dois.add(work["doi"])
        added.append(work["doi"])

    if new_by_year:
        new_text = insert_entries(original_text, new_by_year)
        assert_additive(original_text, new_text)
        with open(PUBLICATIONS_PATH, "w", encoding="utf-8") as f:
            f.write(new_text)
        print(f"Added {len(added)} new entr{'y' if len(added) == 1 else 'ies'} to publications.md: {added}")
    else:
        print("No new Sumner-authored publications found.")
    if skipped:
        print(f"Skipped {len(skipped)} candidate DOI(s) that couldn't be enriched via Crossref: {skipped}")

    # --- Part B: latest-20 digest for publications/wider.md ---
    current_with_orcid = []
    for p in people:
        if p.get("status") != "current" or not p.get("orcid"):
            continue
        windows = membership_windows(p)
        if not windows:
            print(f"  Note: {p['name']} has no joined/stints date on record -- can't tell "
                  f"which of their papers were published during their time in the lab, "
                  f"so excluding them from the wider digest until that's added.")
            continue
        p["windows"] = windows
        current_with_orcid.append(p)
    print(f"Fetching ORCID works for {len(current_with_orcid)} current member(s) with an ORCID iD "
          f"and known lab dates...")

    candidates = {}  # doi -> set of contributing ORCID ids
    for person in current_with_orcid:
        try:
            groups = fetch_orcid_works(person["orcid"], token)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            print(f"  Couldn't fetch ORCID works for {person['name']}: {e} -- skipping them.")
            continue
        for group in groups:
            summary = summarize_group(group)
            if not summary or summary["type"] in WIDER_LIST_EXCLUDED_TYPES:
                continue
            if summary["doi"] in known_dois:
                continue  # already on the main Sumner-authored list
            if not in_membership_window(summary["date"], person["windows"]):
                continue  # published outside their time in the lab
            candidates.setdefault(summary["doi"], set()).add(person["orcid"])

    enriched = []
    for doi, source_orcids in candidates.items():
        work = fetch_crossref_work(doi)
        time.sleep(CROSSREF_SLEEP_SECONDS)
        if not work:
            continue
        enriched.append({
            "doi": work["doi"],
            "url": f"https://doi.org/{work['doi']}",
            "title": work["title"],
            "journal": work["journal"],
            "year": work["year"],
            "date": work["date"],
            "volume": work.get("volume"),
            "issue": work.get("issue"),
            "pages": work.get("pages"),
            "authors": [
                {"name": f"{a['family']} {given_name_initials(a.get('given'))}".strip(),
                 "lab_member": is_lab_member_author(a, orcid_index, family_index)}
                for a in work["authors"]
            ],
            "source_orcid": sorted(source_orcids),
        })
    enriched.sort(key=lambda w: w["date"], reverse=True)
    wider_publications = enriched[:WIDER_LIST_SIZE]

    existing_publications = None
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, encoding="utf-8") as f:
            existing_publications = json.load(f).get("publications")

    # Compare ignoring source_orcid/order-of-discovery churn wouldn't be
    # meaningfully different from a plain equality check here since the
    # list is freshly sorted each run -- a straight comparison is fine.
    if wider_publications == existing_publications:
        print("No change in the wider-lab publications digest -- leaving the data file as-is.")
    else:
        data = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "publications": wider_publications}
        os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        print(f"Wrote {OUT_PATH}: {len(wider_publications)} publication(s).")


if __name__ == "__main__":
    main()
