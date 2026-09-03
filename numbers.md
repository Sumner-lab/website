---
title: Numbers
permalink: /numbers/
hidden: true
sitemap: false
---
{% assign snap = site.data.analytics %}
{% assign ledger = site.data.analytics_totals %}

{% comment %}
  All-time figures come straight from the cumulative ledger
  (analytics_totals.json) -- accurate totals summed from unsampled
  per-day Cloudflare figures, nothing else. They used to be clamped up
  to the live 7-day snapshot whenever that read higher, on the theory
  that the two data files could drift apart by a few random moments --
  but both files are written by the same script run, so they're never
  actually out of sync with each other. The only real gap is that the
  ledger only ingests whole *finished* days (never today, which isn't
  over yet), so "all time" is always current as of yesterday, not this
  second -- a real, permanent, up-to-a-day lag, not a race condition,
  and not something a shorter, more recent window should paper over by
  standing in for it.
{% endcomment %}
{% assign total_views = ledger.pageviews | default: 0 %}
{% assign total_visits = ledger.visits | default: 0 %}
{% assign total_countries = ledger.countries_count | default: 0 %}

<p class="numbers-updated">
{% if snap.connected %}
  Powered by Cloudflare Web Analytics &middot; tracking since {{ snap.since | date: "%-d %B %Y" }} &middot; last updated {{ snap.updated | date: "%-d %B %Y" }}
{% else %}
  Analytics not yet connected &mdash; see setup notes at the bottom of this page.
{% endif %}
</p>

<div class="numbers-stats">
  <div class="numbers-stat">
    <div class="numbers-stat-value">{{ total_views }}</div>
    <div class="numbers-stat-label">Page views (all time)</div>
  </div>
  <div class="numbers-stat">
    <div class="numbers-stat-value">{{ total_visits }}</div>
    <div class="numbers-stat-label">Visits (all time)</div>
  </div>
  <div class="numbers-stat">
    <div class="numbers-stat-value">{{ total_countries }}</div>
    <div class="numbers-stat-label">Countries reached (all time)</div>
  </div>
  <div class="numbers-stat">
    <div class="numbers-stat-value">{{ snap.last7days.views }}</div>
    <div class="numbers-stat-label">Views (last 7 days)</div>
  </div>
  <div class="numbers-stat">
    <div class="numbers-stat-value">{{ snap.last7days.visits }}</div>
    <div class="numbers-stat-label">Visits (last 7 days)</div>
  </div>
</div>
<p class="numbers-caption">A "visit" groups a run of page views from the same person into one session; a "view" counts every page load. All-time figures are exact &mdash; summed one calendar day at a time since tracking began, not a sampled estimate &mdash; and current as of yesterday, since a day only gets counted once it's finished.</p>

## Where visits come from

### All time

<div class="numbers-map-wrap" id="map-alltime">
  {% include world-map.svg %}
</div>

{% assign countries = ledger.top_countries | sort: "visits" | reverse %}
{% assign max_visits = 0 %}
{% for c in countries %}{% if c.visits > max_visits %}{% assign max_visits = c.visits %}{% endif %}{% endfor %}

{% if countries.size > 0 %}
{% if max_visits > 0 %}
<style>
{% for c in countries %}
  {% assign ratio = c.visits | times: 1.0 | divided_by: max_visits %}
  {% assign opacity = ratio | times: 0.8 | plus: 0.15 %}
  #map-alltime .world-map-svg .country[data-iso="{{ c.iso }}"] { fill: var(--color-accent); fill-opacity: {{ opacity }}; }
{% endfor %}
</style>
{% endif %}

<p class="numbers-caption">Every country that's ever sent a visit, shaded darker for more visits. {{ total_countries }} so far.</p>

<table class="numbers-table">
  <tr><th>Country</th><th class="num">Visits</th></tr>
  {% for c in countries %}
  <tr><td>{{ c.name }}</td><td class="num">{{ c.visits }}</td></tr>
  {% endfor %}
</table>
{% else %}
<div class="numbers-empty">
  <h3>No visit data yet</h3>
  {% if snap.connected %}
  <p>Analytics tracking is connected, but no traffic has been recorded yet. There's no way to retroactively recover historical visits &mdash; data only starts from the moment tracking goes live.</p>
  {% else %}
  <p>This page is ready to go, but no traffic has been recorded because analytics tracking isn't connected yet. There's no way to retroactively recover historical visits &mdash; data only starts from the moment tracking goes live.</p>
  {% endif %}
</div>
{% endif %}

### Last 7 days

{% assign countries_7d = "" | split: "" %}
{% if snap.top_countries_7d %}{% assign countries_7d = snap.top_countries_7d | sort: "visits" | reverse %}{% endif %}
{% assign max_visits_7d = 0 %}
{% for c in countries_7d %}{% if c.visits > max_visits_7d %}{% assign max_visits_7d = c.visits %}{% endif %}{% endfor %}

{% if countries_7d.size > 0 %}
<div class="numbers-map-wrap" id="map-7d">
  {% include world-map.svg %}
</div>

{% if max_visits_7d > 0 %}
<style>
{% for c in countries_7d %}
  {% assign ratio = c.visits | times: 1.0 | divided_by: max_visits_7d %}
  {% assign opacity = ratio | times: 0.8 | plus: 0.15 %}
  #map-7d .world-map-svg .country[data-iso="{{ c.iso }}"] { fill: var(--color-accent); fill-opacity: {{ opacity }}; }
{% endfor %}
</style>
{% endif %}

<p class="numbers-caption">Just the last week &mdash; a truer read on where interest is <em>right now</em>. Can include a country the all-time map above hasn't caught up to yet, since that one only ingests whole finished days.</p>

<table class="numbers-table">
  <tr><th>Country</th><th class="num">Visits</th></tr>
  {% for c in countries_7d %}
  <tr><td>{{ c.name }}</td><td class="num">{{ c.visits }}</td></tr>
  {% endfor %}
</table>
{% else %}
<p class="numbers-caption">No visits recorded in the last 7 days.</p>
{% endif %}

{% assign top_pages = ledger.top_pages %}
{% if top_pages.size > 0 %}
## Top pages

<p class="numbers-caption">All time, by page views.</p>

<table class="numbers-table">
  <tr><th>Page</th><th class="num">Views</th></tr>
  {% for p in top_pages limit: 10 %}
  <tr><td>{{ p.path }}</td><td class="num">{{ p.views }}</td></tr>
  {% endfor %}
</table>
{% endif %}

---

### Setup notes (for lab members)

This page reads from two auto-generated files, refreshed by a GitHub Action (`.github/workflows/update-analytics.yml`, `.github/scripts/update_analytics.py`) that pulls from Cloudflare Web Analytics:

- `_data/analytics.json` &mdash; a live snapshot: accurate figures for the last 7 days, including a per-country breakdown (`top_countries_7d`) used for the "last 7 days" map above.
- `_data/analytics_totals.json` &mdash; a cumulative ledger of true all-time totals, built by summing accurate, unsampled *per-day* Cloudflare figures. Cloudflare's Analytics API caps any single query at 13 weeks 2 days and samples wider windows, so a real all-time total isn't obtainable any other way. Each day is counted exactly once, tracked in `counted_dates`, so the job self-heals after any gap without double-counting. (Same approach used on the [Eco-Flow site](https://github.com/Eco-Flow/Eco-Flow.github.io/blob/publish/scripts/fetch_cloudflare_stats.py).)

To connect it:

1. Create a free [Cloudflare](https://www.cloudflare.com/en-gb/web-analytics/) account if you don't have one, and add this site under **Web Analytics** &mdash; no DNS changes needed, it works fine alongside GitHub Pages.
2. Cloudflare gives you a JS snippet with a site token in it. Add that token to `_config.yml` as `cloudflare_analytics_token` (this value is public/safe to commit &mdash; it's just an identifier, not a secret).
3. Create an API Token in Cloudflare with **Account Analytics: Read** permission, then add it as a GitHub repository secret named `CLOUDFLARE_API_TOKEN` (Settings &rarr; Secrets and variables &rarr; Actions). This one **is** secret &mdash; never commit it. Also add the account ID (visible in the Cloudflare dashboard's URL, `dash.cloudflare.com/<ACCOUNT_ID>/...`) as a secret named `CLOUDFLARE_ACCOUNT_ID`.
4. The workflow queries Cloudflare's GraphQL Analytics API and commits updated data files daily, on every push to `main`, and on manual dispatch.

Note: the public beacon token from step 2 is a *different* value from the internal "site tag" the GraphQL API actually filters on &mdash; the script resolves the real one automatically from Cloudflare's Web Analytics site list, so there's no need to look it up by hand.

Want your own visits (or the whole lab's, while testing) left out of these numbers? See [Analytics Opt-Out]({{ site.baseurl }}/no-track/).

This page is intentionally not linked from the site navigation, excluded from the sitemap and search results, and marked `noindex` &mdash; it's for lab members who know the URL, not public visitors.
