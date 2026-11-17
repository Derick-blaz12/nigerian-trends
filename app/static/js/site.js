(function () {
  "use strict";

  var content = document.getElementById("content");
  var page = document.body.dataset.page;

  var PLATFORM_LABELS = {
    spotify: "Spotify", apple_music: "Apple Music", youtube: "YouTube",
    audiomack: "Audiomack", boomplay: "Boomplay", deezer: "Deezer",
    soundcloud: "SoundCloud", tidal: "Tidal", website: "Website",
  };

  // Only same-site paths and https links are ever put into href/src.
  function safeUrl(url) {
    if (typeof url !== "string") return null;
    if (/^https:\/\//i.test(url)) return url;
    if (url.charAt(0) === "/" && url.charAt(1) !== "/") return url;
    return null;
  }

  // Everything from the API is untrusted text: we only ever set textContent,
  // never innerHTML, so a hostile song title cannot inject markup or scripts.
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

  // ---------- pages ----------

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

  var parts = window.location.pathname.split("/").filter(Boolean);
  if (page === "artist") load("/api/v1/artists/" + (parts[1] || ""), renderArtist, "Artist not found.");
  else if (page === "song") load("/api/v1/songs/" + (parts[1] || ""), renderSong, "Song not found.");
  else if (page === "search") initSearch();
})();