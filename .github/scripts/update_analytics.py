#!/usr/bin/env python3
"""Pulls Cloudflare Web Analytics (RUM) data into two Jekyll data files for
the /numbers/ page:

- _data/analytics.json        : live snapshot -- accurate figures for the
                                 last 7 days.
- _data/analytics_totals.json : a persisted, cumulative ledger of true
                                 all-time totals (page views, visits,
                                 per-page and per-country counts), built by
                                 summing accurate *per-day* Cloudflare
                                 figures.

WHY A LEDGER, NOT ONE QUERY: Cloudflare's Analytics GraphQL API hard-caps
any single query's date span at 13 weeks 2 days, so a genuine "since launch"
query isn't possible once the site has more history than that. Wider
queries are also *sampled* -- counts come back as lumpy multiples of a
sample rate and rare events (a country with one visit) can get dropped. So
for true all-time totals we query **one calendar day at a time** (always
unsampled, always within the cap) and add each day into the ledger exactly
once, tracked in `counted_dates`. This mirrors the approach already proven
on the Eco-Flow site (github.com/Eco-Flow/Eco-Flow.github.io,
scripts/fetch_cloudflare_stats.py) -- port it there if this needs updating.

Idempotent: only whole days up to *yesterday* are ingested (today is still
in progress), and a day already in `counted_dates` is never re-added -- so
the daily schedule, a push-triggered run, and manual dispatches can all
fire without double-counting, and a gap (Actions down for days) self-heals
on the next run. LAUNCH_DATE below is recent enough that a full backfill
completes within a single run, so unlike Eco-Flow this doesn't bother with
a wider sampled headline as an interim fallback before the ledger warms up.

SITE TAG vs SITE TOKEN: the public beacon snippet (cloudflare_analytics_token
in _config.yml) embeds a *site token* -- a DIFFERENT value from the *site
tag* the GraphQL Analytics API filters on. Confirmed by inspecting
Eco-Flow's own working setup, where the two are demonstrably different
strings. This script resolves the real site tag via Cloudflare's REST API
(GET /accounts/{account}/rum/site_info/list, matching site_token to the
config value) rather than assuming they're the same value.

Requires env vars: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID. The token
needs "Account Analytics: Read" for the GraphQL queries; if it also can't
list Web Analytics sites (a different permission), site-tag discovery falls
back to using the beacon token directly, which is often wrong -- check the
logs if totals stay at zero after real traffic arrives.
"""
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request

API_URL = "https://api.cloudflare.com/client/v4/graphql"
REST_BASE = "https://api.cloudflare.com/client/v4"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
SNAPSHOT_PATH = os.path.join(REPO_ROOT, "_data", "analytics.json")
LEDGER_PATH = os.path.join(REPO_ROOT, "_data", "analytics_totals.json")

LAUNCH_DATE = "2026-08-14"  # day cloudflare_analytics_token first went live in _config.yml
LEDGER_METHOD = "per-day-unsampled-v3"  # bump to force a clean ledger rebuild


def get_beacon_token():
    with open(os.path.join(REPO_ROOT, "_config.yml")) as f:
        for line in f:
            m = re.match(r'^cloudflare_analytics_token:\s*"?([^"\s]*)"?\s*$', line)
            if m:
                return m.group(1)
    return ""


BEACON_TOKEN = get_beacon_token()
if not BEACON_TOKEN:
    print("cloudflare_analytics_token is empty in _config.yml -- nothing to fetch yet, skipping.")
    sys.exit(0)

# Only require the secret once we know there's actually something to fetch,
# so this script doesn't hard-fail before Cloudflare is set up.
API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")
ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
if not API_TOKEN:
    print("cloudflare_analytics_token is set, but CLOUDFLARE_API_TOKEN secret is missing "
          "-- add it as a repo secret to enable this.")
    sys.exit(1)

with open(os.path.join(SCRIPT_DIR, "country_lookup.json")) as f:
    COUNTRY_NAME_TO_ISO = json.load(f)

# The GraphQL `countryName` dimension actually returns ISO alpha-2 codes
# ("GB", "BR"), not full names -- confirmed against real Cloudflare data
# (the original assumption it returned names was unverified). Build the
# reverse lookup for display, preferring the longest name per code (eg.
# "United Kingdom" over "Britain") since country_lookup.json has a few
# name variants mapping to the same code.
ISO_TO_COUNTRY_NAME = {}
for _name, _iso in COUNTRY_NAME_TO_ISO.items():
    if _iso not in ISO_TO_COUNTRY_NAME or len(_name) > len(ISO_TO_COUNTRY_NAME[_iso]):
        ISO_TO_COUNTRY_NAME[_iso] = _name


def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def graphql(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={"Authorization": f"Bearer {API_TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        result = json.loads(r.read())
    if result.get("errors"):
        raise RuntimeError(json.dumps(result["errors"]))
    accounts = result["data"]["viewer"]["accounts"]
    if not accounts:
        raise RuntimeError("No Cloudflare account accessible with this token/account ID.")
    return accounts[0]


def rest_get(path):
    req = urllib.request.Request(f"{REST_BASE}{path}", headers={"Authorization": f"Bearer {API_TOKEN}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


if not ACCOUNT_ID:
    # Works for a token scoped to "All accounts"; a token scoped to one
    # account still needs CLOUDFLARE_ACCOUNT_ID set, since there's nothing
    # to discover it from.
    acct = graphql("query { viewer { accounts { accountTag } } }", {})
    ACCOUNT_ID = acct["accountTag"]
    print(f"Discovered Cloudflare account: {ACCOUNT_ID}")


def discover_site_tag():
    try:
        data = rest_get(f"/accounts/{ACCOUNT_ID}/rum/site_info/list")
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"Note: couldn't list Web Analytics sites to resolve the real site tag ({e}) "
              f"-- falling back to the beacon token, which is often NOT the same value as "
              f"the GraphQL site tag, so queries may silently match nothing.")
        return BEACON_TOKEN
    for site in data.get("result") or []:
        if site.get("site_token") == BEACON_TOKEN:
            print(f"Resolved site tag {site['site_tag']} from the beacon token.")
            return site["site_tag"]
    print(f"Note: no Web Analytics site matched beacon token {BEACON_TOKEN} -- falling back "
          f"to using it directly as the site tag, which is likely wrong.")
    return BEACON_TOKEN


# An explicit override takes priority over discovery -- useful once the
# right site tag is confirmed (eg. by comparing request paths in the
# diagnostic below against this site's actual URL structure), especially
# if the token can't list Web Analytics sites (a different permission from
# "Account Analytics: Read", so the REST discovery below may 403).
SITE_TAG = os.environ.get("CLOUDFLARE_SITE_TAG", "") or discover_site_tag()

# One calendar day, always unsampled and always within the query-span cap --
# used to accumulate the ledger.
DAY_QUERY = """
query Day($account: String!, $site: String!, $day: Date!) {
  viewer {
    accounts(filter: { accountTag: $account }) {
      totals: rumPageloadEventsAdaptiveGroups(
        filter: { siteTag: $site, date_geq: $day, date_leq: $day }
        limit: 1
      ) {
        count
        sum { visits }
      }
      pages: rumPageloadEventsAdaptiveGroups(
        filter: { siteTag: $site, date_geq: $day, date_leq: $day }
        limit: 200
        orderBy: [count_DESC]
      ) {
        count
        dimensions { requestPath }
      }
      countries: rumPageloadEventsAdaptiveGroups(
        filter: { siteTag: $site, date_geq: $day, date_leq: $day }
        limit: 250
        orderBy: [count_DESC]
      ) {
        count
        sum { visits }
        dimensions { countryName }
      }
    }
  }
}
"""

# A short (7-day) range for the live snapshot -- narrow enough to stay
# unsampled too, so no separate per-day accumulation is needed here.
RANGE_QUERY = """
query Range($account: String!, $site: String!, $start: Date!, $end: Date!) {
  viewer {
    accounts(filter: { accountTag: $account }) {
      totals: rumPageloadEventsAdaptiveGroups(
        filter: { siteTag: $site, date_geq: $start, date_leq: $end }
        limit: 1
      ) {
        count
        sum { visits }
      }
      countries: rumPageloadEventsAdaptiveGroups(
        filter: { siteTag: $site, date_geq: $start, date_leq: $end }
        limit: 250
        orderBy: [count_DESC]
      ) {
        count
        sum { visits }
        dimensions { countryName }
      }
    }
  }
}
"""

# Diagnostic for when a query comes back empty: which site tags actually
# have data in this account, so a wrong SITE_TAG is easy to spot.
SITES_QUERY = """
query Sites($account: String!, $start: Date!, $end: Date!) {
  viewer {
    accounts(filter: { accountTag: $account }) {
      sites: rumPageloadEventsAdaptiveGroups(
        filter: { date_geq: $start, date_leq: $end }
        limit: 20
        orderBy: [count_DESC]
      ) {
        count
        dimensions { siteTag }
      }
    }
  }
}
"""

# Diagnostic companion to SITES_QUERY: the request paths for one candidate
# site tag, so it can be told apart from another site sharing the account.
PATHS_QUERY = """
query Paths($account: String!, $site: String!, $start: Date!, $end: Date!) {
  viewer {
    accounts(filter: { accountTag: $account }) {
      pages: rumPageloadEventsAdaptiveGroups(
        filter: { siteTag: $site, date_geq: $start, date_leq: $end }
        limit: 5
        orderBy: [count_DESC]
      ) {
        dimensions { requestPath }
      }
    }
  }
}
"""


def build_top_countries(views_by_code, visits_by_code):
    """Turns {iso: views} / {iso: visits} maps into the sorted list shape
    both data files store, resolving each code to a display name via
    ISO_TO_COUNTRY_NAME. A code with no name match still counts toward
    totals but is flagged so it won't silently fail to shade on the map."""
    top = []
    unmatched = []
    for code, views in views_by_code.items():
        display_name = ISO_TO_COUNTRY_NAME.get(code)
        entry = {"name": display_name or code, "views": views, "visits": visits_by_code.get(code, 0)}
        if display_name:
            entry["iso"] = code
        else:
            unmatched.append(code)
        top.append(entry)
    top.sort(key=lambda c: (-c["visits"], c["name"]))
    return top, unmatched


def update_ledger(yesterday):
    """Accumulate accurate per-day figures into the cumulative ledger.

    Reads the previous ledger, queries Cloudflare for every day not yet
    counted (up to `yesterday`), and adds each whole day exactly once.
    """
    prev = load_json(LEDGER_PATH)
    if prev.get("method") != LEDGER_METHOD:
        if prev:
            print("Ledger method changed -- rebuilding all-time totals from launch.")
        prev = {}

    counted = set(prev.get("counted_dates") or [])
    pages = {p["path"]: int(p["views"]) for p in (prev.get("top_pages") or [])}
    countries = {c["iso"]: int(c["views"]) for c in (prev.get("top_countries") or []) if c.get("iso")}
    country_visits = {c["iso"]: int(c.get("visits") or 0) for c in (prev.get("top_countries") or []) if c.get("iso")}
    pv = int(prev.get("pageviews") or 0)
    vis = int(prev.get("visits") or 0)

    day = datetime.date.fromisoformat(LAUNCH_DATE)
    last = datetime.date.fromisoformat(yesterday)
    ingested = 0
    while day <= last:
        day_iso = day.isoformat()
        day += datetime.timedelta(days=1)
        if day_iso in counted:
            continue

        acct = graphql(DAY_QUERY, {"account": ACCOUNT_ID, "site": SITE_TAG, "day": day_iso})
        tgroups = acct.get("totals") or []
        if tgroups:
            pv += int(tgroups[0]["count"])
            vis += int((tgroups[0].get("sum") or {}).get("visits") or 0)
        for g in (acct.get("pages") or []):
            path = g["dimensions"]["requestPath"] or "/"
            pages[path] = pages.get(path, 0) + int(g["count"])
        for g in (acct.get("countries") or []):
            # Despite the field's name, `countryName` returns an ISO
            # alpha-2 code (eg. "GB"), not a full country name.
            code = g["dimensions"]["countryName"] or "ZZ"
            countries[code] = countries.get(code, 0) + int(g["count"])
            country_visits[code] = country_visits.get(code, 0) + int((g.get("sum") or {}).get("visits") or 0)

        counted.add(day_iso)
        ingested += 1

    print(f"Ledger: ingested {ingested} new day(s); {pv} page views / {vis} visits all-time "
          f"across {len(countries)} countries.")

    top_countries, unmatched = build_top_countries(countries, country_visits)
    if unmatched:
        print(f"Note: {len(unmatched)} country code(s) had no name match and won't shade on "
              f"the map (they still count toward totals): {', '.join(unmatched)}")

    top_pages = sorted(
        ({"path": p, "views": v} for p, v in pages.items()),
        key=lambda p: (-p["views"], p["path"]),
    )

    return {
        "updated": datetime.date.today().isoformat(),
        "method": LEDGER_METHOD,
        "counted_dates": sorted(counted),
        "pageviews": pv,
        "visits": vis,
        "countries_count": len(countries),
        "top_pages": top_pages,
        "top_countries": top_countries,
    }


today = datetime.date.today()
now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
today_iso = today.isoformat()
yesterday_iso = (today - datetime.timedelta(days=1)).isoformat()
week_ago_iso = (today - datetime.timedelta(days=7)).isoformat()

recent = graphql(RANGE_QUERY, {"account": ACCOUNT_ID, "site": SITE_TAG, "start": week_ago_iso, "end": today_iso})
recent_totals = recent.get("totals") or []
views_7d = int(recent_totals[0]["count"]) if recent_totals else 0
visits_7d = int((recent_totals[0].get("sum") or {}).get("visits") or 0) if recent_totals else 0

recent_country_groups = recent.get("countries") or []
countries_7d = len(recent_country_groups)
# Kept separately from the ledger's all-time top_countries (below) rather
# than used to inflate it: this window can and does legitimately include a
# country the day-by-day ledger hasn't ingested yet (today is still in
# progress), so treating the two as interchangeable made the "countries
# reached" headline able to claim a country neither the map nor the table
# under it could actually show.
views_7d_by_code, visits_7d_by_code = {}, {}
for g in recent_country_groups:
    code = g["dimensions"]["countryName"] or "ZZ"
    views_7d_by_code[code] = views_7d_by_code.get(code, 0) + int(g["count"])
    visits_7d_by_code[code] = visits_7d_by_code.get(code, 0) + int((g.get("sum") or {}).get("visits") or 0)
top_countries_7d, _ = build_top_countries(views_7d_by_code, visits_7d_by_code)

if views_7d == 0:
    try:
        diag = graphql(SITES_QUERY, {"account": ACCOUNT_ID, "start": week_ago_iso, "end": today_iso})
        sites = diag.get("sites") or []
        if sites:
            print("No data for our site tag. Site tags with data in this account (last 7d):")
            for s in sites:
                tag = s["dimensions"]["siteTag"]
                print(f"  {tag}: {s['count']} page views")
                # This account may track more than one site -- print each
                # candidate's actual page paths so the right one can be told
                # apart by eye (and set as CLOUDFLARE_SITE_TAG once known).
                try:
                    paths = graphql(PATHS_QUERY, {"account": ACCOUNT_ID, "site": tag,
                                                  "start": week_ago_iso, "end": today_iso})
                    top = [p["dimensions"]["requestPath"] for p in (paths.get("pages") or [])]
                    print(f"    top paths: {top}")
                except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError) as e:
                    print(f"    (couldn't fetch paths: {e})")
            print(f"(We queried siteTag={SITE_TAG})")
        else:
            print(f"No RUM data in this account yet for the last 7 days (queried "
                  f"siteTag={SITE_TAG}) -- likely just no traffic so far.")
    except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError) as e:
        print(f"Note: diagnostic sites query failed too ({e}).")

ledger = update_ledger(yesterday_iso)

snapshot = {
    "connected": True,
    "updated": now_iso,
    "since": LAUNCH_DATE,
    "last7days": {"views": views_7d, "visits": visits_7d},
    "countries_7d": countries_7d,
    "top_countries_7d": top_countries_7d,
}

os.makedirs(os.path.dirname(SNAPSHOT_PATH), exist_ok=True)
with open(SNAPSHOT_PATH, "w") as f:
    json.dump(snapshot, f, indent=2)
    f.write("\n")
with open(LEDGER_PATH, "w") as f:
    json.dump(ledger, f, indent=2)
    f.write("\n")

print(f"Wrote {SNAPSHOT_PATH} and {LEDGER_PATH}: {ledger['pageviews']} all-time views, "
      f"{views_7d} in the last 7 days.")
