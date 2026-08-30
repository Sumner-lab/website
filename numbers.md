---
title: Numbers
permalink: /numbers/
hidden: true
sitemap: false
---
{% assign snap = site.data.analytics %}
{% assign ledger = site.data.analytics_totals %}

{% comment %}
  "All time" headline figures come from the cumulative ledger
  (analytics_totals.json): accurate totals summed from unsampled per-day
  Cloudflare figures. As belt-and-braces, each total is still clamped up to
  the live 7-day snapshot, so a "total" can never read lower than "7 days"
  if the two data files land moments apart.
{% endcomment %}
{% assign total_views = ledger.pageviews | default: 0 %}
{% assign total_visits = ledger.visits | default: 0 %}
{% assign total_countries = ledger.countries_count | default: 0 %}
{% if snap.last7days.views > total_views %}{% assign total_views = snap.last7days.views %}{% endif %}
{% if snap.last7days.visits > total_visits %}{% assign total_visits = snap.last7days.visits %}{% endif %}
{% if snap.countries_7d > total_countries %}{% assign total_countries = snap.countries_7d %}{% endif %}

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
    <div class="numbers-stat-label">Countries reached</div>
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

<div class="numbers-map-wrap">
  {% include world-map.svg %}
</div>

{% assign countries = ledger.top_countries | sort: "visits" | reverse %}
{% assign max_visits = 0 %}
{% for c in countries %}{% if c.visits > max_visits %}{% assign max_visits = c.visits %}{% endif %}{% endfor %}

{% if countries.size > 0 %}
<style>
{% for c in countries %}
  {% assign ratio = c.visits | times: 1.0 | divided_by: max_visits %}
  {% assign opacity = ratio | times: 0.8 | plus: 0.15 %}
  .world-map-svg .country[data-iso="{{ c.iso }}"] { fill: var(--color-accent); fill-opacity: {{ opacity }}; }
{% endfor %}
</style>

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

{% assign top_pages = ledger.top_pages %}
{% if top_pages.size > 0 %}
<h2>Top pages</h2>
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

- `_data/analytics.json` &mdash; a live snapshot: accurate figures for the last 7 days.
- `_data/analytics_totals.json` &mdash; a cumulative ledger of true all-time totals, built by summing accurate, unsampled *per-day* Cloudflare figures one day at a time. Cloudflare's Analytics API caps any single query at 13 weeks 2 days and samples wider windows, so a real all-time total isn't obtainable any other way. Each day is counted exactly once, tracked in `counted_dates`, so the job self-heals after any gap without double-counting. (Same approach used on the [Eco-Flow site](https://github.com/Eco-Flow/Eco-Flow.github.io/blob/publish/scripts/fetch_cloudflare_stats.py).)

To connect it:

1. Create a free [Cloudflare](https://www.cloudflare.com/en-gb/web-analytics/) account if you don't have one, and add this site under **Web Analytics** &mdash; no DNS changes needed, it works fine alongside GitHub Pages.
2. Cloudflare gives you a JS snippet with a site token in it. Add that token to `_config.yml` as `cloudflare_analytics_token` (this value is public/safe to commit &mdash; it's just an identifier, not a secret).
3. Create an API Token in Cloudflare with **Account Analytics: Read** permission, then add it as a GitHub repository secret named `CLOUDFLARE_API_TOKEN` (Settings &rarr; Secrets and variables &rarr; Actions). This one **is** secret &mdash; never commit it. Also add the account ID (visible in the Cloudflare dashboard's URL, `dash.cloudflare.com/<ACCOUNT_ID>/...`) as a secret named `CLOUDFLARE_ACCOUNT_ID`.
4. The workflow queries Cloudflare's GraphQL Analytics API and commits updated data files daily, on every push to `main`, and on manual dispatch.

Note: the public beacon token from step 2 is a *different* value from the internal "site tag" the GraphQL API actually filters on &mdash; the script resolves the real one automatically from Cloudflare's Web Analytics site list, so there's no need to look it up by hand.

This page is intentionally not linked from the site navigation, excluded from the sitemap and search results, and marked `noindex` &mdash; it's for lab members who know the URL, not public visitors.
