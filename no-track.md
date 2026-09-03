---
title: Analytics Opt-Out
permalink: /no-track/
hidden: true
sitemap: false
---
This site uses [Cloudflare Web Analytics](https://www.cloudflare.com/en-gb/web-analytics/) to count anonymous visits (see [Numbers]({{ site.baseurl }}/numbers/)) &mdash; no cookies, no IP storage, no cross-site tracking. If you'd still rather your own visits weren't counted &mdash; useful for lab members testing or browsing the site &mdash; turn it off here.

**This only affects this browser, on this device, on this site.** It won't follow you to another device or browser, and it has no effect on any other website.

<div id="track-status" class="numbers-empty"></div>

<p>
  <button id="opt-out-btn" class="person-link-btn">Turn tracking off</button>
  <button id="opt-in-btn" class="person-link-btn">Turn tracking back on</button>
</p>

<script>
(function () {
  var KEY = "sumnerlab-no-track";
  var status = document.getElementById("track-status");
  var outBtn = document.getElementById("opt-out-btn");
  var inBtn = document.getElementById("opt-in-btn");

  function render() {
    var off = false;
    try { off = localStorage.getItem(KEY) === "1"; } catch (e) {}
    status.innerHTML = off
      ? "<h3>Tracking is off</h3><p>Your visits in this browser aren’t being counted.</p>"
      : "<h3>Tracking is on</h3><p>Visits in this browser are counted like any other visitor’s.</p>";
    outBtn.style.display = off ? "none" : "inline-flex";
    inBtn.style.display = off ? "inline-flex" : "none";
  }

  outBtn.addEventListener("click", function () {
    try { localStorage.setItem(KEY, "1"); } catch (e) {}
    render();
  });
  inBtn.addEventListener("click", function () {
    try { localStorage.removeItem(KEY); } catch (e) {}
    render();
  });

  render();
})();
</script>

A couple of things worth knowing:

- This can't remove any visits already counted &mdash; same as everywhere else on this site, there's no way to retroactively undo historical data.
- If you clear this browser's site data, use a private/incognito window, or switch devices or browsers, tracking is back on by default until you opt out here again.
- To opt the whole lab out at once rather than browser-by-browser, share this page's link (`{{ site.url }}/no-track/`) and ask everyone to click through it once.
