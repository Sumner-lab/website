---
title: Wider Sumner Lab Papers
permalink: /publications/wider/
---
Lab members also publish work that doesn't include Seirian Sumner as a co-author — from before, alongside, or after their time in the lab. The list below is generated automatically each week from current members' ORCID records; for the full picture, including work from before or after their time here, each person's ORCID iD links to their own publication list, kept current by ORCID itself.

{% include latest-publications.html %}

{% assign current = site.people | where: "status", "current" | sort: "order" %}
{% assign alumni = site.people | where: "status", "alumni" | sort: "name" %}

## Current group

<ul>
{% for person in current %}
  {% assign orcid_link = nil %}
  {% for link in person.links %}{% if link.url contains "orcid.org" %}{% assign orcid_link = link.url %}{% endif %}{% endfor %}
  <li><a href="{{ person.url | relative_url }}">{{ person.name | default: person.title }}</a>{% if person.stints %} ({% for stint in person.stints %}{{ stint.joined }}{% if stint.left %}–{{ stint.left }}{% else %}–present{% endif %}{% unless forloop.last %}, {% endunless %}{% endfor %}){% elsif person.joined %} ({{ person.joined }}{% if person.left %}–{{ person.left }}{% else %}–present{% endif %}){% endif %}{% if orcid_link %} — <a href="{{ orcid_link }}" target="_blank" rel="noopener">ORCID</a>{% endif %}</li>
{% endfor %}
</ul>

{% if alumni.size > 0 %}
## Left the nest

<ul>
{% for person in alumni %}
  {% assign orcid_link = nil %}
  {% for link in person.links %}{% if link.url contains "orcid.org" %}{% assign orcid_link = link.url %}{% endif %}{% endfor %}
  <li><a href="{{ person.url | relative_url }}">{{ person.name | default: person.title }}</a>{% if person.stints %} ({% for stint in person.stints %}{{ stint.joined }}{% if stint.left %}–{{ stint.left }}{% endif %}{% unless forloop.last %}, {% endunless %}{% endfor %}){% elsif person.joined %} ({{ person.joined }}{% if person.left %}–{{ person.left }}{% endif %}){% endif %}{% if orcid_link %} — <a href="{{ orcid_link }}" target="_blank" rel="noopener">ORCID</a>{% endif %}</li>
{% endfor %}
</ul>
{% endif %}
