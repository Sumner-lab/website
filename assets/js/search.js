document.addEventListener("DOMContentLoaded", function () {
  var toggle = document.querySelector(".search-toggle");
  var box = document.querySelector(".search-box");
  var input = document.querySelector(".search-input");
  var results = document.querySelector(".search-results");
  if (!toggle || !box || !input || !results) return;

  var indexUrl = toggle.getAttribute("data-search-index");
  var data = null;

  function openSearch() {
    box.classList.add("is-open");
    toggle.setAttribute("aria-expanded", "true");
    input.focus();
    if (!data) {
      fetch(indexUrl)
        .then(function (r) { return r.json(); })
        .then(function (json) { data = json; });
    }
  }

  function closeSearch() {
    box.classList.remove("is-open");
    toggle.setAttribute("aria-expanded", "false");
    results.innerHTML = "";
    input.value = "";
  }

  toggle.addEventListener("click", function () {
    box.classList.contains("is-open") ? closeSearch() : openSearch();
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeSearch();
  });

  document.addEventListener("click", function (e) {
    if (box.classList.contains("is-open") && !box.contains(e.target) && e.target !== toggle) {
      closeSearch();
    }
  });

  input.addEventListener("input", function () {
    var q = input.value.trim().toLowerCase();
    results.innerHTML = "";
    if (!data || q.length < 2) return;

    var matches = data
      .map(function (item) {
        var titleIdx = item.title.toLowerCase().indexOf(q);
        var excerptIdx = (item.excerpt || "").toLowerCase().indexOf(q);
        if (titleIdx === -1 && excerptIdx === -1) return null;
        return { item: item, score: titleIdx !== -1 ? titleIdx : 100 + excerptIdx };
      })
      .filter(Boolean)
      .sort(function (a, b) { return a.score - b.score; })
      .slice(0, 8)
      .map(function (m) { return m.item; });

    if (matches.length === 0) {
      results.innerHTML = '<li class="search-empty">No matches for &ldquo;' + escapeHtml(input.value) + '&rdquo;</li>';
      return;
    }

    matches.forEach(function (item) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = item.url;
      var typeLabel = item.type === "post" ? (item.date || "Update") : item.type === "person" ? "Person" : "Page";
      a.innerHTML =
        '<span class="search-result-title">' + escapeHtml(item.title) + "</span>" +
        '<span class="search-result-meta">' + escapeHtml(typeLabel) + "</span>";
      li.appendChild(a);
      results.appendChild(li);
    });
  });

  function escapeHtml(s) {
    var div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }
});
