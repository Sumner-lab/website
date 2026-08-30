---
title: Numbers
permalink: /numbers/
hidden: true
sitemap: false
---
<p class="numbers-updated">
{% if site.data.analytics.connected %}
  Powered by Cloudflare Web Analytics &middot; last updated {{ site.data.analytics.updated | date: "%-d %B %Y" }}
{% else %}
  Analytics not yet connected &mdash; see setup notes at the bottom of this page.
{% endif %}
</p>

<div class="numbers-stats">
  <div class="numbers-stat">
    <div class="numbers-stat-value">{{ site.data.analytics.totals.views }}</div>
    <div class="numbers-stat-label">Page views (last 90 days)</div>
  </div>
  <div class="numbers-stat">
    <div class="numbers-stat-value">{{ site.data.analytics.totals.visits }}</div>
    <div class="numbers-stat-label">Visits (last 90 days)</div>
  </div>
  <div class="numbers-stat">
    <div class="numbers-stat-value">{{ site.data.analytics.countries | size }}</div>
    <div class="numbers-stat-label">Countries reached</div>
  </div>
  <div class="numbers-stat">
    <div class="numbers-stat-value">{{ site.data.analytics.last7days.views }}</div>
    <div class="numbers-stat-label">Views (last 7 days)</div>
  </div>
  <div class="numbers-stat">
    <div class="numbers-stat-value">{{ site.data.analytics.last7days.visits }}</div>
    <div class="numbers-stat-label">Visits (last 7 days)</div>
  </div>
</div>

<div class="numbers-map-wrap">
  {% include world-map.svg %}
</div>

{% assign countries = site.data.analytics.countries | sort: "visits" | reverse %}
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
  <p>This page is ready to go, but no traffic has been recorded because analytics tracking isn't connected yet. There's no way to retroactively recover historical visits &mdash; data only starts from the moment tracking goes live.</p>
</div>
{% endif %}

{% assign top_pages = site.data.analytics.top_pages %}
{% if top_pages.size > 0 %}
<h2>Top pages</h2>
<table class="numbers-table">
  <tr><th>Page</th><th class="num">Views</th></tr>
  {% for p in top_pages %}
  <tr><td>{{ p.path }}</td><td class="num">{{ p.views }}</td></tr>
  {% endfor %}
</table>
{% endif %}

---

### Setup notes (for lab members)

This page reads from `_data/analytics.json`, refreshed by a scheduled GitHub Action (`.github/workflows/update-analytics.yml`) that pulls from Cloudflare Web Analytics. To connect it:

1. Create a free [Cloudflare](https://www.cloudflare.com/en-gb/web-analytics/) account if you don't have one, and add this site under **Web Analytics** &mdash; no DNS changes needed, it works fine alongside GitHub Pages.
2. Cloudflare gives you a JS snippet with a site token in it. Add that token to `_config.yml` as `cloudflare_analytics_token` (this value is public/safe to commit &mdash; it's just an identifier, not a secret).
3. Create an API Token in Cloudflare with **Account Analytics: Read** permission, then add it as a GitHub repository secret named `CLOUDFLARE_API_TOKEN` (Settings &rarr; Secrets and variables &rarr; Actions). This one **is** secret &mdash; never commit it.
4. The scheduled workflow queries Cloudflare's GraphQL Analytics API and commits an updated `_data/analytics.json` daily.

This page is intentionally not linked from the site navigation, excluded from the sitemap and search results, and marked `noindex` &mdash; it's for lab members who know the URL, not public visitors.
