(function () {
  "use strict";

  var content = document.getElementById("content");
  var page = document.body.dataset.page;

  var PLATFORM_LABELS = {
    spotify: "Spotify", apple_music: "Apple Music", youtube: "YouTube",
    audiomack: "Audiomack", boomplay: "Boomplay", deezer: "Deezer",
    soundcloud: "SoundCloud", tidal: "Tidal", website: "Website",
  };
  var CATEGORY_LABELS = { news: "News", release: "Release", interview: "Interview", event: "Event" };

  // Only same-site paths and https links are ever put into href/src.
  function safeUrl(url) {
    if (typeof url !== "string") return null;
    if (/^https:\/\//i.test(url)) return url;
    if (url.charAt(0) === "/" && url.charAt(1) !== "/") return url;
    return null;
  }

  // Everything from the API is untrusted text: we only ever set textContent,
  // never innerHTML, so a hostile title cannot inject markup or scripts.
  function el(tag, props, children) {
    var node = document.createElement(tag);
    props = props || {};
    if (props.className) node.className = props.className;
    if (props.text !== undefined && props.text !== null) node.textContent = props.text;
    if (props.href && safeUrl(props.href)) {
      node.setAttribute("href", props.href);
      if (/^https:/i.test(props.href)) {
        node.setAttribute("target", "_blank");
        node.setAttribute("rel", "noopener noreferrer");
      }
    }
    if (props.src && safeUrl(props.src)) node.setAttribute("src", props.src);
    if (props.alt !== undefined) node.setAttribute("alt", props.alt);
    (children || []).forEach(function (child) {
      if (child) node.appendChild(child);
    });
    return node;
  }

  function show(nodes) {
    content.textContent = "";
    nodes.forEach(function (node) {
      if (node) content.appendChild(node);
    });
  }

  function showMessage(text) {
    show([el("p", { className: "message", text: text })]);
  }

  function getJSON(url) {
    return fetch(url, { headers: { Accept: "application/json" } }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        if (!response.ok) {
          var error = new Error((body.error && body.error.message) || "Request failed.");
          error.status = response.status;
          throw error;
        }
        return body;
      });
    });
  }

  function formatDuration(seconds) {
    if (!seconds) return "";
    return Math.floor(seconds / 60) + ":" + String(seconds % 60).padStart(2, "0");
  }

  function formatDate(iso) {
    if (!iso) return "";
    var p = iso.split("-");
    return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2])).toLocaleDateString("en-GB", {
      day: "numeric", month: "long", year: "numeric", timeZone: "UTC",
    });
  }

  function formatPublished(iso) {
    return iso ? formatDate(iso.slice(0, 10)) : "";
  }

  function section(title, node) {
    return el("section", {}, [el("h2", { text: title }), node]);
  }

  function chips(genres) {
    if (!genres || !genres.length) return null;
    return el("ul", { className: "chips" }, genres.map(function (g) {
      return el("li", { text: g.name });
    }));
  }

  function linkList(links) {
    return el("ul", { className: "links" }, links.map(function (link) {
      return el("li", {}, [el("a", { href: link.url, text: PLATFORM_LABELS[link.platform] || link.platform })]);
    }));
  }

  function creditLine(label, artists, role) {
    var matching = artists.filter(function (a) { return a.role === role; });
    if (!matching.length) return null;
    var parts = [document.createTextNode(label + " ")];
    matching.forEach(function (a, index) {
      if (index > 0) parts.push(document.createTextNode(", "));
      parts.push(el("a", { href: "/artists/" + encodeURIComponent(a.slug), text: a.name }));
    });
    return el("p", { className: "credits" }, parts);
  }

  function artistNames(artists) {
    return artists.map(function (a) { return a.name; }).join(", ");
  }

  // ---------- news ----------

  function updateList(items) {
    return el("ul", { className: "items" }, items.map(function (u) {
      var meta = [u.artist.name, CATEGORY_LABELS[u.category] || u.category, formatPublished(u.published_at)]
        .filter(Boolean).join(" | ");
      return el("li", {}, [
        el("a", { href: "/news/" + u.id, text: u.title }),
        el("p", { className: "muted", text: meta }),
        u.summary ? el("p", { text: u.summary }) : null,
      ]);
    }));
  }

  // Adds a news section under the page content. Failures are silent: the page works without it.
  function appendUpdates(url, title) {
    getJSON(url).then(function (body) {
      if (body.data.length) content.appendChild(section(title, updateList(body.data)));
    }).catch(function (error) {
      console.error(error);
    });
  }

  function renderNewsItem(u) {
    document.title = u.title + " | Nigerian Trends";
    var meta = [CATEGORY_LABELS[u.category] || u.category, formatPublished(u.published_at)]
      .filter(Boolean).join(" | ");
    var about = [
      document.createTextNode("About "),
      el("a", { href: "/artists/" + encodeURIComponent(u.artist.slug), text: u.artist.name }),
    ];
    if (u.song) {
      about.push(document.createTextNode(" | "));
      about.push(el("a", { href: "/songs/" + u.song.id, text: u.song.title }));
    }
    if (u.album) about.push(document.createTextNode(" | Album: " + u.album.title));

    var source = null;
    if (u.source) {
      source = el("p", { className: "muted" }, [
        document.createTextNode("Source: "),
        u.source.url ? el("a", { href: u.source.url, text: u.source.name }) : document.createTextNode(u.source.name),
      ]);
    }
    show([
      el("h1", { text: u.title }),
      el("p", { className: "muted", text: meta }),
      el("p", { className: "muted" }, about),
      u.summary ? el("p", { text: u.summary }) : null,
      el("div", { className: "bio", text: u.body }),
      source,
    ]);
  }

  function initNews() {
    var params = new URLSearchParams(window.location.search);
    var category = params.get("category") || "";
    var pageNumber = parseInt(params.get("page"), 10);
    if (!(pageNumber >= 1)) pageNumber = 1;
    var perPage = 10;
    var url = "/api/v1/updates?per_page=" + perPage + "&page=" + pageNumber +
      (category ? "&category=" + encodeURIComponent(category) : "");

    getJSON(url).then(function (body) {
      var filters = [el("li", {}, [el("a", { href: "/news", text: "All" })])];
      Object.keys(CATEGORY_LABELS).forEach(function (key) {
        filters.push(el("li", {}, [el("a", { href: "/news?category=" + key, text: CATEGORY_LABELS[key] })]));
      });
      var nodes = [el("h1", { text: "News" }), el("ul", { className: "chips" }, filters)];
      if (!body.data.length) nodes.push(el("p", { className: "message", text: "No news yet." }));
      else nodes.push(updateList(body.data));

      var base = "/news?" + (category ? "category=" + encodeURIComponent(category) + "&" : "");
      var pager = [];
      if (pageNumber > 1) pager.push(el("a", { href: base + "page=" + (pageNumber - 1), text: "Newer" }));
      if (body.meta.total > pageNumber * perPage) pager.push(el("a", { href: base + "page=" + (pageNumber + 1), text: "Older" }));
      if (pager.length) nodes.push(el("p", { className: "pager" }, pager));
      show(nodes);
    }).catch(function (error) {
      console.error(error);
      showMessage(error.status === 422 ? "Nothing found." : "Could not load the news. Please try again.");
    });
  }

  // ---------- catalogue pages ----------

  function renderArtist(a) {
    document.title = a.name + " | Nigerian Trends";
    var facts = [a.origin_city, a.debut_year ? "Debut " + a.debut_year : ""].filter(Boolean).join(" | ");
    var nodes = [
      el("div", { className: "profile" }, [
        a.image_url ? el("img", { className: "portrait", src: a.image_url, alt: a.name }) : null,
        el("div", {}, [el("h1", { text: a.name }), facts ? el("p", { className: "muted", text: facts }) : null, chips(a.genres)]),
      ]),
    ];
    if (a.bio) nodes.push(el("p", { className: "bio", text: a.bio }));
    if (a.links.length) nodes.push(section("Listen", linkList(a.links)));
    if (a.songs.length) {
      nodes.push(section("Songs", el("ul", { className: "items" }, a.songs.map(function (s) {
        return el("li", {}, [
          el("a", { href: "/songs/" + s.id, text: s.title }),
          s.role !== "primary" ? el("span", { className: "badge", text: s.role }) : null,
          s.release_date ? el("span", { className: "badge", text: formatDate(s.release_date) }) : null,
        ]);
      }))));
    }
    if (a.albums.length) {
      nodes.push(section("Albums", el("ul", { className: "items" }, a.albums.map(function (album) {
        return el("li", {}, [
          el("span", { text: album.title }),
          el("span", { className: "badge", text: album.album_type }),
          album.release_date ? el("span", { className: "badge", text: formatDate(album.release_date) }) : null,
        ]);
      }))));
    }
    show(nodes);
    appendUpdates("/api/v1/updates?per_page=5&artist=" + encodeURIComponent(a.slug), "Latest news");
  }

  function renderSong(s) {
    document.title = s.title + " | Nigerian Trends";
    var facts = [formatDate(s.release_date), formatDuration(s.duration_seconds), s.album ? "From " + s.album.title : ""]
      .filter(Boolean).join(" | ");
    var nodes = [
      el("h1", { text: s.title }),
      creditLine("by", s.artists, "primary"),
      creditLine("feat.", s.artists, "featured"),
      creditLine("Produced by", s.artists, "producer"),
      creditLine("Written by", s.artists, "writer"),
      facts ? el("p", { className: "muted", text: facts }) : null,
      chips(s.genres),
    ];
    if (s.links.length) nodes.push(section("Listen", linkList(s.links)));
    show(nodes);
    appendUpdates("/api/v1/updates?per_page=5&song=" + s.id, "Related news");
  }

  function resultList(items, build) {
    return el("ul", { className: "items" }, items.map(build));
  }

  function renderSearch(query, data, totals) {
    var nodes = [el("h1", { text: 'Results for "' + query + '"' })];
    if (data.artists.length) {
      nodes.push(section("Artists (" + totals.artists + ")", resultList(data.artists, function (a) {
        return el("li", {}, [
          el("a", { href: "/artists/" + encodeURIComponent(a.slug), text: a.name }),
          a.origin_city ? el("span", { className: "badge", text: a.origin_city }) : null,
        ]);
      })));
    }
    if (data.songs.length) {
      nodes.push(section("Songs (" + totals.songs + ")", resultList(data.songs, function (s) {
        return el("li", {}, [
          el("a", { href: "/songs/" + s.id, text: s.title }),
          el("span", { className: "badge", text: artistNames(s.artists) }),
        ]);
      })));
    }
    if (data.albums.length) {
      nodes.push(section("Albums (" + totals.albums + ")", resultList(data.albums, function (a) {
        return el("li", {}, [
          el("span", { text: a.title }),
          el("span", { className: "badge", text: a.artist.name }),
        ]);
      })));
    }
    if (nodes.length === 1) nodes.push(el("p", { className: "message", text: "Nothing found. Try another spelling." }));
    show(nodes);
  }

  function load(url, render, notFoundMessage) {
    getJSON(url).then(function (body) {
      render(body.data);
    }).catch(function (error) {
      console.error(error);
      showMessage(error.status === 404 ? notFoundMessage : "Could not load this page. Please try again.");
    });
  }

  function initSearch() {
    var query = (new URLSearchParams(window.location.search).get("q") || "").trim();
    var input = document.querySelector(".search input");
    if (input) input.value = query;
    if (query.length < 2) {
      showMessage("Type at least 2 characters to search.");
      return;
    }
    getJSON("/api/v1/search?limit=10&q=" + encodeURIComponent(query)).then(function (body) {
      renderSearch(query, body.data, body.meta.totals);
    }).catch(function (error) {
      console.error(error);
      showMessage("Search is unavailable right now. Please try again.");
    });
  }

    // ---------- Next Up Radar ----------

  function renderRadar(items, meta) {
    var nodes = [
      el("h1", { text: "Next Up Radar" }),
      el("p", { className: "muted", text: "Emerging Nigerian artists, picked by open rules. Every card shows why." }),
    ];
    if (!items.length) {
      nodes.push(el("p", { className: "message", text: "The Radar is warming up. Check back soon." }));
    } else {
      nodes.push(el("ul", { className: "items" }, items.map(function (item) {
        var a = item.artist;
        var head = [el("a", { href: "/artists/" + encodeURIComponent(a.slug), text: "#" + item.rank + " " + a.name })];
        if (item.editors_pick) head.push(el("span", { className: "badge", text: "Editor's pick" }));
        var facts = [a.origin_city, a.genres.map(function (g) { return g.name; }).join(", ")]
          .filter(Boolean).join(" | ");
        return el("li", {}, [
          el("strong", {}, head),
          facts ? el("p", { className: "muted", text: facts }) : null,
          el("ul", { className: "reasons" }, item.reasons.map(function (r) {
            return el("li", { text: r.label + " (+" + r.points + ")" });
          })),
        ]);
      })));
    }
    if (meta.attribution) nodes.push(el("p", { className: "muted", text: meta.attribution }));
    show(nodes);
  }

  function initRadar() {
    getJSON("/api/v1/radar?limit=24").then(function (body) {
      renderRadar(body.data, body.meta);
    }).catch(function (error) {
      console.error(error);
      showMessage("Could not load the Radar. Please try again.");
    });
  }

  var parts = window.location.pathname.split("/").filter(Boolean);
  if (page === "artist") load("/api/v1/artists/" + (parts[1] || ""), renderArtist, "Artist not found.");
  else if (page === "song") load("/api/v1/songs/" + (parts[1] || ""), renderSong, "Song not found.");
  else if (page === "search") initSearch();
  else if (page === "news") initNews();
  else if (page === "news-item") load("/api/v1/updates/" + (parts[1] || ""), renderNewsItem, "This story was not found.");
  else if (page === "radar") initRadar();
})();