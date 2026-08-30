#!/usr/bin/env python3
"""Pulls Cloudflare Web Analytics (RUM) data and writes _data/analytics.json
for the /numbers/ page.

Requires env vars: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID.
Reads the (non-secret) site token straight out of _config.yml so it doesn't
need to be duplicated as a separate GitHub secret.

The query shape (viewer -> accounts -> rumPageloadEventsAdaptiveGroups,
filtered by siteTag/datetime, an account-scoped dataset needing "Account
Analytics: Read") and its dimension field names are confirmed working
against a real account/token.
"""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

API_URL = "https://api.cloudflare.com/client/v4/graphql"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))


def get_site_tag():
    with open(os.path.join(REPO_ROOT, "_config.yml")) as f:
        for line in f:
            m = re.match(r'^cloudflare_analytics_token:\s*"?([^"\s]*)"?\s*$', line)
            if m:
                return m.group(1)
    return ""


SITE_TAG = get_site_tag()
if not SITE_TAG:
    print("cloudflare_analytics_token is empty in _config.yml -- nothing to fetch yet, skipping.")
    sys.exit(0)

# Only require the secrets once we know there's actually something to fetch,
# so this script doesn't hard-fail before Cloudflare is set up.
API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")
ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
if not API_TOKEN or not ACCOUNT_ID:
    print("cloudflare_analytics_token is set, but CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID "
          "secrets are missing -- add them as repo secrets to enable this.")
    sys.exit(1)

with open(os.path.join(SCRIPT_DIR, "country_lookup.json")) as f:
    COUNTRY_NAME_TO_ISO = json.load(f)

QUERY = """
query GetAnalytics($accountTag: string!, $siteTag: string!, $since: Time!, $until: Time!) {
  viewer {
    accounts(filter: {accountTag: $accountTag}) {
      overview: rumPageloadEventsAdaptiveGroups(
        filter: {siteTag: $siteTag, datetime_geq: $since, datetime_leq: $until}
        limit: 1
      ) {
        count
      }
      byCountry: rumPageloadEventsAdaptiveGroups(
        filter: {siteTag: $siteTag, datetime_geq: $since, datetime_leq: $until}
        limit: 250
        orderBy: [count_DESC]
      ) {
        count
        dimensions { countryName }
      }
      byPath: rumPageloadEventsAdaptiveGroups(
        filter: {siteTag: $siteTag, datetime_geq: $since, datetime_leq: $until}
        limit: 10
        orderBy: [count_DESC]
      ) {
        count
        dimensions { requestPath }
      }
    }
  }
}
"""


def query(since, until):
    body = json.dumps(
        {
            "query": QUERY,
            "variables": {
                "accountTag": ACCOUNT_ID,
                "siteTag": SITE_TAG,
                "since": since,
                "until": until,
            },
        }
    ).encode()
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {API_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        result = json.loads(r.read())
    if result.get("errors"):
        print("Cloudflare GraphQL API returned errors:")
        print(json.dumps(result["errors"], indent=2))
        sys.exit(1)
    accounts = result["data"]["viewer"]["accounts"]
    if not accounts:
        print("No account matched CLOUDFLARE_ACCOUNT_ID -- check the secret value.")
        sys.exit(1)
    return accounts[0]


now = datetime.now(timezone.utc)
now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
# Cloudflare's Analytics GraphQL API hard-caps any single query at 13 weeks
# 2 days (93 days) -- confirmed directly from its own error message
# ("account ... cannot request a time range wider than 13w2d"). There's no
# true "all time" available from this endpoint without paginating across
# multiple 90-day windows and merging results, which isn't worth the
# complexity for this internal stats page -- so "all time" here really
# means "the last 90 days", and numbers.md's labels say so.
window_start_iso = (now - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
week_ago_iso = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

all_time = query(window_start_iso, now_iso)
last_7 = query(week_ago_iso, now_iso)

countries = []
unmatched = []
for group in all_time["byCountry"]:
    name = group["dimensions"]["countryName"]
    iso = COUNTRY_NAME_TO_ISO.get(name)
    if iso:
        countries.append({"iso": iso, "name": name, "visits": group["count"]})
    else:
        unmatched.append(name)

if unmatched:
    print(f"Note: {len(unmatched)} country name(s) had no ISO match and were dropped from the map "
          f"(they still count toward totals): {', '.join(unmatched)}")

top_pages = [
    {"path": g["dimensions"]["requestPath"], "views": g["count"]}
    for g in all_time["byPath"]
]

# "Visits" (deduplicated sessions) needs a different dimension/metric than a
# plain pageload count, which isn't confirmed here -- using page views as a
# stand-in for both until that's wired up properly, rather than fabricate a
# separate number that looks precise but isn't.
total_views = all_time["overview"][0]["count"] if all_time["overview"] else 0
last7_views = last_7["overview"][0]["count"] if last_7["overview"] else 0

data = {
    "connected": True,
    "updated": now_iso,
    "totals": {"views": total_views, "visits": total_views},
    "last7days": {"views": last7_views, "visits": last7_views},
    "top_pages": top_pages,
    "countries": sorted(countries, key=lambda c: -c["visits"]),
}

out_path = os.path.join(REPO_ROOT, "_data", "analytics.json")
with open(out_path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")

print(f"Wrote {out_path}: {data['totals']['views']} views, {len(countries)} countries")
