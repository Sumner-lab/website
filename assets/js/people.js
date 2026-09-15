// Profile tabs (_layouts/person.html) and People page filters
// (_layouts/people-index.html). Both pages are complete without this
// script: every profile section and every person simply shows.
document.addEventListener("DOMContentLoaded", function () {
  var book = document.querySelector("[data-nb-tabs]");
  if (book) {
    var tablist = book.querySelector("[role=tablist]");
    var tabs = Array.prototype.slice.call(book.querySelectorAll("[role=tab]"));
    if (tabs.length > 1) {
      var select = function (tab, focus) {
        tabs.forEach(function (t) {
          var on = t === tab;
          t.setAttribute("aria-selected", on ? "true" : "false");
          t.tabIndex = on ? 0 : -1;
          document.getElementById(t.getAttribute("aria-controls")).classList.toggle("is-active", on);
        });
        if (focus) tab.focus();
      };
      tablist.hidden = false;
      book.classList.add("nb-tabbed");
      var fromHash = tabs.filter(function (t) { return "#" + t.getAttribute("aria-controls") === window.location.hash; })[0];
      select(fromHash || tabs[0], false);
      tabs.forEach(function (tab, i) {
        tab.addEventListener("click", function () {
          select(tab, false);
          history.replaceState(null, "", "#" + tab.getAttribute("aria-controls"));
        });
        tab.addEventListener("keydown", function (e) {
          var next = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : null;
          if (next === null) return;
          e.preventDefault();
          select(tabs[(next + tabs.length) % tabs.length], true);
        });
      });
    }
  }

  var filters = document.querySelector("[data-people-filters]");
  if (filters) {
    var status = "all";
    var theme = null;
    var buttons = Array.prototype.slice.call(filters.querySelectorAll("button"));
    var apply = function () {
      buttons.forEach(function (b) {
        var on = b.dataset.status ? b.dataset.status === status : b.dataset.theme === theme;
        b.setAttribute("aria-pressed", on ? "true" : "false");
      });
      document.querySelectorAll("[data-people-group]").forEach(function (group) {
        var visible = 0;
        group.querySelectorAll(".people-card").forEach(function (card) {
          var themes = (card.dataset.themes || "").split("|");
          var show = !theme || themes.indexOf(theme) !== -1;
          card.hidden = !show;
          if (show) visible++;
        });
        group.hidden = (status !== "all" && group.dataset.peopleGroup !== status) || visible === 0;
      });
    };
    filters.hidden = false;
    filters.addEventListener("click", function (e) {
      var b = e.target.closest("button");
      if (!b) return;
      if (b.dataset.status) status = b.dataset.status;
      else theme = theme === b.dataset.theme ? null : b.dataset.theme;
      apply();
    });
  }
});
