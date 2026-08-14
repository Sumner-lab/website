document.addEventListener("DOMContentLoaded", function () {
  var walls = document.querySelectorAll(".social-wall");
  if (!walls.length) return;

  walls.forEach(function (wall) {
    var tag = wall.getAttribute("data-hashtag");
    var grid = wall.querySelector(".social-wall-grid");
    if (!tag || !grid) return;
    loadPosts(tag, grid);
  });

  function loadPosts(tag, grid) {
    var url =
      "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=" +
      encodeURIComponent("#" + tag) +
      "&sort=latest&limit=9";

    fetch(url)
      .then(function (r) {
        if (!r.ok) throw new Error("status " + r.status);
        return r.json();
      })
      .then(function (data) {
        render(grid, tag, data.posts || []);
      })
      .catch(function () {
        grid.innerHTML =
          '<p class="social-wall-status">Couldn&rsquo;t load posts right now &mdash; <a href="https://bsky.app/hashtag/' +
          tag +
          '" target="_blank" rel="noopener">see them directly on Bluesky</a>.</p>';
      });
  }

  function render(grid, tag, posts) {
    if (!posts.length) {
      grid.innerHTML =
        '<p class="social-wall-status">No posts tagged #' +
        tag +
        " yet &mdash; be the first!</p>";
      return;
    }

    grid.innerHTML = "";
    posts.forEach(function (post) {
      var author = post.author || {};
      var record = post.record || {};
      var name = author.displayName || author.handle || "Someone";
      var handle = author.handle ? "@" + author.handle : "";
      var text = record.text || "";
      var postUrl =
        "https://bsky.app/profile/" +
        author.handle +
        "/post/" +
        post.uri.split("/").pop();
      var date = record.createdAt
        ? new Date(record.createdAt).toLocaleDateString(undefined, {
            day: "numeric",
            month: "short",
            year: "numeric",
          })
        : "";

      var thumb = getThumb(post.embed);
      var img = thumb
        ? '<img class="social-post-image" src="' + escapeAttr(thumb) + '" alt="" loading="lazy">'
        : "";

      var quoting = "";
      if (
        post.embed &&
        post.embed.$type === "app.bsky.embed.record#view" &&
        post.embed.record &&
        post.embed.record.author
      ) {
        quoting =
          '<span class="social-post-quoting">quoting @' +
          escapeHtml(post.embed.record.author.handle || "") +
          "</span>";
      }

      var el = document.createElement("a");
      el.className = "social-post";
      el.href = postUrl;
      el.target = "_blank";
      el.rel = "noopener";
      el.innerHTML =
        img +
        '<div class="social-post-body">' +
        '<div class="social-post-author">' +
        (author.avatar
          ? '<img class="social-post-avatar" src="' + escapeAttr(author.avatar) + '" alt="">'
          : "") +
        '<span><span class="social-post-name">' +
        escapeHtml(name) +
        "</span> <span class=\"social-post-handle\">" +
        escapeHtml(handle) +
        "</span></span>" +
        "</div>" +
        '<p class="social-post-text">' +
        escapeHtml(text) +
        "</p>" +
        '<span class="social-post-date">' +
        escapeHtml(date) +
        "</span>" +
        quoting +
        "</div>";
      grid.appendChild(el);
    });
  }

  // Pulls a preview image out of any embed shape Bluesky returns, including
  // a quote post -- where the picture belongs to the *quoted* post, nested
  // under embed.record.embeds, not the top-level embed itself.
  function getThumb(embed) {
    if (!embed) return null;
    switch (embed.$type) {
      case "app.bsky.embed.images#view":
        return embed.images && embed.images[0] ? embed.images[0].thumb : null;
      case "app.bsky.embed.gallery#view":
        return embed.items && embed.items[0] ? embed.items[0].thumbnail : null;
      case "app.bsky.embed.video#view":
        return embed.thumbnail || null;
      case "app.bsky.embed.external#view":
        return embed.external ? embed.external.thumb : null;
      case "app.bsky.embed.record#view":
        return embed.record && embed.record.embeds && embed.record.embeds[0]
          ? getThumb(embed.record.embeds[0])
          : null;
      case "app.bsky.embed.recordWithMedia#view":
        return (
          getThumb(embed.media) ||
          (embed.record &&
            embed.record.record &&
            embed.record.record.embeds &&
            getThumb(embed.record.record.embeds[0])) ||
          null
        );
      default:
        return null;
    }
  }

  function escapeHtml(s) {
    var div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }
  function escapeAttr(s) {
    return String(s).replace(/"/g, "&quot;");
  }
});
