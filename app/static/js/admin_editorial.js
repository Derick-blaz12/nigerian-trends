(function () {
  "use strict";

  var content = document.getElementById("content");
  var csrfToken = "";
  var CATEGORIES = [["news", "News"], ["release", "Release"], ["interview", "Interview"], ["event", "Event"]];
  var STATUS_TABS = [["all", "All"], ["draft", "Drafts"], ["published", "Published"], ["archived", "Archived"]];

  // Builds elements with textContent only, never innerHTML.
  function el(tag, props, children) {
    var node = document.createElement(tag);
    props = props || {};
    Object.keys(props).forEach(function (key) {
      var value = props[key];
      if (value === undefined || value === null) return;
      if (key === "text") node.textContent = value;
      else if (key === "className") node.className = value;
      else if (key === "onclick") node.addEventListener("click", value);
      else if (key === "onsubmit") node.addEventListener("submit", value);
      else if (key === "onchange") node.addEventListener("change", value);
      else node.setAttribute(key, value);
    });
    (children || []).forEach(function (child) {
      if (child) node.appendChild(child);
    });
    return node;
  }

  function clear(node) {
    node.textContent = "";
  }

  function api(method, path, body) {
    var options = { method: method, headers: { Accept: "application/json" }, credentials: "same-origin" };
    if (method !== "GET") options.headers["X-CSRFToken"] = csrfToken;
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    return fetch("/api/v1" + path, options).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (payload) {
        if (!response.ok) {
          var error = new Error((payload.error && payload.error.message) || "Request failed.");
          error.status = response.status;
          error.details = payload.error && payload.error.details;
          throw error;
        }
        return payload;
      });
    });
  }

  function describeError(error) {
    var text = error.message || "Something went wrong.";
    if (error.details) {
      var parts = Object.keys(error.details).map(function (key) {
        return key + ": " + error.details[key];
      });
      if (parts.length) text += " (" + parts.join("; ") + ")";
    }
    return text;
  }

  function fetchCsrf() {
    return fetch("/api/v1/auth/csrf", { credentials: "same-origin" })
      .then(function (response) { return response.json(); })
      .then(function (body) { csrfToken = body.data.csrf_token; });
  }

  function showMessage(text) {
    clear(content);
    content.appendChild(el("p", { className: "message", text: text }));
  }

  // ---------- login ----------

  function showLogin(message) {
    var note = el("p", { className: "error", role: "alert", text: message || "" });
    var identifier = el("input", { type: "text", name: "identifier", autocomplete: "username", required: "", maxlength: 255 });
    var password = el("input", { type: "password", name: "password", autocomplete: "current-password", required: "", maxlength: 128 });
    var form = el("form", {
      className: "stack",
      onsubmit: function (event) {
        event.preventDefault();
        api("POST", "/auth/login", { identifier: identifier.value, password: password.value })
          .then(boot)
          .catch(function (error) { note.textContent = describeError(error); });
      },
    }, [
      el("label", { text: "Email or username" }, [identifier]),
      el("label", { text: "Password" }, [password]),
      el("button", { type: "submit", className: "btn primary", text: "Log in" }),
      note,
    ]);
    clear(content);
    content.appendChild(el("h1", { text: "Editorial dashboard" }));
    content.appendChild(form);
  }

  // ---------- dashboard ----------

  function showDashboard(user) {
    var state = { status: "all", page: 1 };
    var artistsCache = null;

    var flashNode = el("p", { className: "flash", role: "status" });
    var countsNode = el("p", { className: "muted" });
    var tabsNode = el("div", { className: "tabs" });
    var listNode = el("div");
    var editorNode = el("div");

    function flash(text, isError) {
      flashNode.textContent = text || "";
      flashNode.className = "flash" + (isError ? " error" : "");
    }

    function fail(error) {
      if (error.status === 401 || error.status === 403) {
        boot();
        return;
      }
      flash(describeError(error), true);
    }

    function loadArtists() {
      if (artistsCache) return Promise.resolve(artistsCache);
      return api("GET", "/admin/artists?per_page=100").then(function (body) {
        artistsCache = body.data;
        return artistsCache;
      });
    }

    function renderTabs() {
      clear(tabsNode);
      STATUS_TABS.forEach(function (tab) {
        tabsNode.appendChild(el("button", {
          type: "button",
          className: "btn" + (state.status === tab[0] ? " primary" : ""),
          text: tab[1],
          onclick: function () { state.status = tab[0]; state.page = 1; refresh(); },
        }));
      });
    }

    function actionButton(label, path, message) {
      return el("button", {
        type: "button",
        className: "btn",
        text: label,
        onclick: function () {
          api("POST", path).then(function () { flash(message); refresh(); }).catch(fail);
        },
      });
    }

    function renderList(items, meta) {
      clear(listNode);
      if (!items.length) {
        listNode.appendChild(el("p", { className: "message", text: "Nothing here yet." }));
      } else {
        listNode.appendChild(el("ul", { className: "items" }, items.map(function (u) {
          var info = [u.artist.name, u.category, u.status, "updated " + (u.updated_at || "").slice(0, 10)].join(" | ");
          var base = "/admin/updates/" + u.id;
          var actions;
          if (u.status === "archived") {
            actions = [actionButton("Restore", base + "/restore", "Restored as a draft.")];
          } else {
            actions = [el("button", { type: "button", className: "btn", text: "Edit", onclick: function () { edit(u.id); } })];
            if (u.status === "draft") actions.push(actionButton("Publish", base + "/publish", "Published."));
            if (u.status === "published") actions.push(actionButton("Unpublish", base + "/unpublish", "Moved back to drafts."));
            actions.push(actionButton("Archive", base + "/archive", "Archived."));
          }
          return el("li", {}, [
            el("strong", { text: u.title }),
            el("p", { className: "muted", text: info }),
            el("div", { className: "row-actions" }, actions),
          ]);
        })));
      }
      var pager = [];
      if (state.page > 1) {
        pager.push(el("button", { type: "button", className: "btn", text: "Previous", onclick: function () { state.page -= 1; refresh(); } }));
      }
      if (meta.total > state.page * meta.per_page) {
        pager.push(el("button", { type: "button", className: "btn", text: "Next", onclick: function () { state.page += 1; refresh(); } }));
      }
      if (pager.length) listNode.appendChild(el("div", { className: "row-actions" }, pager));
    }

    function refresh() {
      renderTabs();
      api("GET", "/admin/editorial/summary").then(function (body) {
        var c = body.data;
        countsNode.textContent = c.draft + " drafts | " + c.published + " published | " + c.archived + " archived";
      }).catch(fail);
      api("GET", "/admin/updates?per_page=20&page=" + state.page + "&status=" + state.status)
        .then(function (body) { renderList(body.data, body.meta); })
        .catch(fail);
    }

    function edit(id) {
      api("GET", "/admin/updates/" + id).then(function (body) { openEditor(body.data); }).catch(fail);
    }

    function openEditor(update) {
      var isNew = !update;
      clear(editorNode);

      var artistSelect = el("select", { name: "artist", required: "" });
      var songSelect = el("select", { name: "song" });
      var albumSelect = el("select", { name: "album" });
      var categorySelect = el("select", { name: "category" }, CATEGORIES.map(function (c) {
        return el("option", { value: c[0], text: c[1] });
      }));
      var titleInput = el("input", { type: "text", name: "title", required: "", minlength: 3, maxlength: 200 });
      var summaryInput = el("textarea", { name: "summary", rows: 2, maxlength: 300 });
      var bodyInput = el("textarea", { name: "body", rows: 12, maxlength: 20000 });
      var sourceNameInput = el("input", { type: "text", name: "source_name", maxlength: 150 });
      var sourceUrlInput = el("input", { type: "url", name: "source_url", maxlength: 500, placeholder: "https://" });

      function fillOptions(select, items, emptyLabel, current) {
        clear(select);
        select.appendChild(el("option", { value: "", text: emptyLabel }));
        var all = items.slice();
        var known = items.some(function (item) { return current && item.id === current.id; });
        if (current && !known) all.push(current);
        all.forEach(function (item) {
          select.appendChild(el("option", { value: String(item.id), text: item.title || item.name }));
        });
        select.value = current ? String(current.id) : "";
      }

      function loadRelated(artistId, currentSong, currentAlbum) {
        var artist = (artistsCache || []).filter(function (a) { return a.id === artistId; })[0];
        if (!artist) {
          fillOptions(songSelect, [], "No related song", null);
          fillOptions(albumSelect, [], "No related album", null);
          return;
        }
        Promise.all([
          api("GET", "/admin/songs?per_page=100&artist=" + encodeURIComponent(artist.slug)),
          api("GET", "/admin/albums?per_page=100&artist_id=" + artist.id),
        ]).then(function (results) {
          fillOptions(songSelect, results[0].data, "No related song", currentSong);
          fillOptions(albumSelect, results[1].data, "No related album", currentAlbum);
        }).catch(fail);
      }

      artistSelect.addEventListener("change", function () {
        loadRelated(parseInt(artistSelect.value, 10) || null, null, null);
      });

      function field(label, control, hint) {
        return el("label", {}, [
          document.createTextNode(label),
          control,
          hint ? el("small", { className: "muted", text: hint }) : null,
        ]);
      }

      function save() {
        var payload = {
          title: titleInput.value,
          summary: summaryInput.value,
          body: bodyInput.value,
          category: categorySelect.value,
          source_name: sourceNameInput.value,
          source_url: sourceUrlInput.value,
          song_id: songSelect.value ? parseInt(songSelect.value, 10) : null,
          album_id: albumSelect.value ? parseInt(albumSelect.value, 10) : null,
        };
        var request;
        if (isNew) {
          payload.artist_id = parseInt(artistSelect.value, 10);
          request = api("POST", "/admin/updates", payload);
        } else {
          request = api("PATCH", "/admin/updates/" + update.id, payload);
        }
        request.then(function () {
          flash(isNew ? "Draft created." : "Saved.");
          clear(editorNode);
          refresh();
        }).catch(fail);
      }

      editorNode.appendChild(el("h2", {
        text: isNew ? "New update (saved as a draft)" : "Edit update #" + update.id + " (" + update.status + ")",
      }));
      editorNode.appendChild(el("form", {
        className: "stack",
        onsubmit: function (event) { event.preventDefault(); save(); },
      }, [
        field("Artist", artistSelect, isNew ? "" : "The artist cannot be changed after creation."),
        field("Category", categorySelect),
        field("Title", titleInput),
        field("Summary (shown on news cards, up to 300 characters)", summaryInput),
        field("Body (plain text; at least 20 characters to publish)", bodyInput),
        field("Source name", sourceNameInput, "Required if you add a source link."),
        field("Source link", sourceUrlInput),
        field("Related song", songSelect),
        field("Related album", albumSelect),
        el("div", { className: "row-actions" }, [
          el("button", { type: "submit", className: "btn primary", text: "Save" }),
          el("button", { type: "button", className: "btn", text: "Cancel", onclick: function () { clear(editorNode); } }),
        ]),
      ]));

      loadArtists().then(function (artists) {
        if (update && !artists.some(function (a) { return a.id === update.artist.id; })) {
          artists.push(update.artist);
        }
        clear(artistSelect);
        artistSelect.appendChild(el("option", { value: "", text: "Choose an artist" }));
        artists.forEach(function (a) {
          artistSelect.appendChild(el("option", { value: String(a.id), text: a.name }));
        });
        if (update) {
          artistSelect.value = String(update.artist.id);
          artistSelect.disabled = true;
          categorySelect.value = update.category;
          titleInput.value = update.title;
          summaryInput.value = update.summary || "";
          bodyInput.value = update.body || "";
          sourceNameInput.value = update.source ? update.source.name : "";
          sourceUrlInput.value = update.source && update.source.url ? update.source.url : "";
        }
        loadRelated(update ? update.artist.id : null, update ? update.song : null, update ? update.album : null);
        editorNode.scrollIntoView({ behavior: "smooth", block: "start" });
      }).catch(fail);
    }

    clear(content);
    content.appendChild(el("div", { className: "bar" }, [
      el("h1", { text: "Editorial dashboard" }),
      el("button", {
        type: "button",
        className: "btn",
        text: "Log out (" + user.username + ")",
        onclick: function () { api("POST", "/auth/logout").then(boot).catch(fail); },
      }),
    ]));
    content.appendChild(flashNode);
    content.appendChild(countsNode);
    content.appendChild(el("button", { type: "button", className: "btn primary", text: "New update", onclick: function () { openEditor(null); } }));
    content.appendChild(tabsNode);
    content.appendChild(listNode);
    content.appendChild(editorNode);
    refresh();
  }

  // ---------- start ----------

  function boot() {
    return fetchCsrf()
      .then(function () { return api("GET", "/auth/me"); })
      .then(function (body) {
        if (body.data.role !== "admin") {
          showMessage("This page is for administrators.");
          return;
        }
        showDashboard(body.data);
      })
      .catch(function (error) {
        if (error.status === 401) showLogin("");
        else showMessage("Could not load the dashboard. " + describeError(error));
      });
  }

  boot();
})();