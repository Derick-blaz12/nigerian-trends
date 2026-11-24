(function () {
  "use strict";

  var content = document.getElementById("content");
  var page = document.body.dataset.page;
  var csrfToken = "";
  var currentUser = null;

  var REPORT_REASONS = [
    ["spam", "Spam"], ["abuse", "Abuse or harassment"], ["hate", "Hate speech"],
    ["sexual", "Sexual content"], ["misinformation", "Misinformation"], ["other", "Something else"],
  ];

  // ---------- helpers ----------

  function safeHref(url) {
    return typeof url === "string" && url.charAt(0) === "/" && url.charAt(1) !== "/";
  }

  // Builds elements with textContent only, never innerHTML, so user text cannot inject markup.
  function el(tag, props, children) {
    var node = document.createElement(tag);
    props = props || {};
    Object.keys(props).forEach(function (key) {
      var value = props[key];
      if (value === undefined || value === null || value === false) return;
      if (key === "text") node.textContent = value;
      else if (key === "className") node.className = value;
      else if (key === "onclick") node.addEventListener("click", value);
      else if (key === "onsubmit") node.addEventListener("submit", value);
      else if (key === "href") { if (safeHref(value)) node.setAttribute("href", value); }
      else node.setAttribute(key, value);
    });
    (children || []).forEach(function (child) {
      if (child) node.appendChild(child);
    });
    return node;
  }

  function text(value) {
    return document.createTextNode(value);
  }

  function clear(node) {
    node.textContent = "";
  }

  function show(nodes) {
    clear(content);
    nodes.forEach(function (node) {
      if (node) content.appendChild(node);
    });
  }

  function showMessage(message) {
    show([el("p", { className: "message", text: message })]);
  }

  function setFlash(node, message, isError) {
    node.textContent = "";
    if (message) node.appendChild(text(message));
    node.className = isError ? "flash error" : "flash";
  }

  function formatWhen(iso) {
    if (!iso) return "";
    var date = new Date(iso);
    if (isNaN(date.getTime())) return "";
    return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  }

  function loginUrl() {
    return "/login?next=" + encodeURIComponent(window.location.pathname + window.location.search);
  }

  function promptLogin(node, message) {
    node.textContent = "";
    node.className = "flash";
    node.appendChild(text(message + " "));
    node.appendChild(el("a", { href: loginUrl(), text: "Log in" }));
    node.appendChild(text(" or "));
    node.appendChild(el("a", { href: "/register", text: "sign up" }));
    node.appendChild(text("."));
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
          var error = new Error((payload.error && payload.error.message) || "Something went wrong.");
          error.status = response.status;
          error.details = payload.error && payload.error.details;
          throw error;
        }
        return payload;
      });
    });
  }

  function describe(error) {
    if (error.status === 429) return "You're going a little fast. Please wait a moment and try again.";
    if (error.status === 401) return "Please log in first.";
    var message = error.message || "Something went wrong.";
    if (error.details) {
      var parts = Object.keys(error.details).map(function (key) { return error.details[key]; });
      if (parts.length) message += " " + parts.join(" ");
    }
    return message;
  }

  function refreshCsrf() {
    return fetch("/api/v1/auth/csrf", { credentials: "same-origin" })
      .then(function (response) { return response.json(); })
      .then(function (body) { csrfToken = body.data.csrf_token; });
  }

  // ---------- session and the header ----------

  var ready = refreshCsrf()
    .then(function () { return api("GET", "/auth/session"); })
    .then(function (body) { currentUser = body.data; })
    .catch(function (error) { console.error(error); currentUser = null; });

  function logout() {
    api("POST", "/auth/logout")
      .catch(function (error) { console.error(error); })
      .then(function () { window.location.reload(); });
  }

  function renderAccount() {
    var box = document.getElementById("account");
    if (!box) return;
    clear(box);
    if (currentUser) {
      box.appendChild(el("span", { className: "muted", text: "@" + currentUser.username }));
      box.appendChild(el("button", { type: "button", className: "btn", text: "Log out", onclick: logout }));
    } else {
      box.appendChild(el("a", { href: loginUrl(), text: "Log in" }));
      box.appendChild(el("a", { href: "/register", text: "Sign up" }));
    }
  }

  ready.then(renderAccount);

  // ---------- log in and sign up ----------

  function nextUrl() {
    var next = new URLSearchParams(window.location.search).get("next") || "";
    var safe = next.charAt(0) === "/" && next.charAt(1) !== "/" && next.indexOf("\\") === -1;
    if (!safe || next.indexOf("/login") === 0 || next.indexOf("/register") === 0) return "/radar";
    return next;
  }

  function authForm(kind) {
    var isRegister = kind === "register";
    var note = el("p", { className: "error", role: "alert" });
    var inputs = {};

    function field(label, name, type, attrs) {
      var attributes = { type: type, name: name, required: "" };
      Object.keys(attrs || {}).forEach(function (key) { attributes[key] = attrs[key]; });
      inputs[name] = el("input", attributes);
      return el("label", {}, [text(label), inputs[name]]);
    }

    var fields = isRegister
      ? [
          field("Email", "email", "email", { autocomplete: "email", maxlength: 255 }),
          field("Username (3 to 30 letters, numbers or underscores)", "username", "text",
            { autocomplete: "username", minlength: 3, maxlength: 30 }),
          field("Password (at least 8 characters)", "password", "password",
            { autocomplete: "new-password", minlength: 8, maxlength: 128 }),
        ]
      : [
          field("Email or username", "identifier", "text", { autocomplete: "username", maxlength: 255 }),
          field("Password", "password", "password", { autocomplete: "current-password", maxlength: 128 }),
        ];

    var button = el("button", { type: "submit", className: "btn primary", text: isRegister ? "Create account" : "Log in" });
    var form = el("form", {
      className: "stack",
      onsubmit: function (event) {
        event.preventDefault();
        setFlash(note, "", true);
        button.setAttribute("disabled", "");
        var request = isRegister
          ? api("POST", "/auth/register", {
              email: inputs.email.value, username: inputs.username.value, password: inputs.password.value,
            })
          : api("POST", "/auth/login", { identifier: inputs.identifier.value, password: inputs.password.value });
        request
          .then(refreshCsrf)
          .then(function () { window.location.assign(nextUrl()); })
          .catch(function (error) {
            setFlash(note, describe(error), true);
            button.removeAttribute("disabled");
          });
      },
    }, fields.concat([button, note]));

    var otherHref = (isRegister ? "/login" : "/register") + window.location.search;
    show([
      el("h1", { text: isRegister ? "Create your account" : "Log in" }),
      form,
      el("p", { className: "muted" }, [
        text(isRegister ? "Already have an account? " : "New here? "),
        el("a", { href: otherHref, text: isRegister ? "Log in" : "Sign up" }),
      ]),
      isRegister
        ? el("p", { className: "muted", text: "Please be respectful. Comments that break our community rules can be hidden or removed." })
        : null,
    ]);
  }

  function initAuthPage(kind) {
    ready.then(function () {
      if (currentUser) {
        show([
          el("h1", { text: "You're signed in" }),
          el("p", {}, [text("Signed in as @" + currentUser.username + ". "), el("a", { href: "/radar", text: "Go to the Radar" })]),
        ]);
        return;
      }
      authForm(kind);
    });
  }

  // ---------- comments and reactions on a song page ----------

  function commentForm(options) {
    var note = el("p", { className: "error", role: "alert" });
    var box = el("textarea", { name: "body", rows: options.rows || 3, maxlength: 2000, required: "", "aria-label": options.label });
    box.value = options.initial || "";
    var send = el("button", { type: "submit", className: "btn primary", text: options.submitLabel });
    var actions = [send];
    if (options.onCancel) {
      actions.push(el("button", { type: "button", className: "btn", text: "Cancel", onclick: options.onCancel }));
    }
    return el("form", {
      className: "stack",
      onsubmit: function (event) {
        event.preventDefault();
        setFlash(note, "", true);
        send.setAttribute("disabled", "");
        options.onSubmit(box.value)
          .then(function () { box.value = ""; })
          .catch(function (error) { setFlash(note, describe(error), true); })
          .then(function () { send.removeAttribute("disabled"); });
      },
    }, [
      el("label", {}, [text(options.label), box]),
      el("div", { className: "row-actions" }, actions),
      note,
    ]);
  }

  function mountSongPanel(songId, container) {
    var state = { page: 1, perPage: 10 };
    var stats = { likes: 0, recommends: 0, comments: 0, me: null };
    var flash = el("p", { className: "flash", role: "status" });
    var statsLine = el("p", { className: "muted" });
    var likeBtn = el("button", { type: "button", className: "btn", onclick: function () { toggle("like"); } });
    var recBtn = el("button", { type: "button", className: "btn", onclick: function () { toggle("recommend"); } });
    var composer = el("div");
    var list = el("div", { className: "comments" });
    var moreBtn = el("button", {
      type: "button", className: "btn", text: "Load more comments",
      onclick: function () { state.page += 1; loadComments(false); },
    });
    moreBtn.hidden = true;

    function renderStats() {
      var liked = !!(stats.me && stats.me.liked);
      var recommended = !!(stats.me && stats.me.recommended);
      statsLine.textContent = stats.likes + " likes | " + stats.recommends + " recommendations | " + stats.comments + " comments";
      likeBtn.textContent = liked ? "Liked" : "Like";
      likeBtn.className = liked ? "btn primary" : "btn";
      likeBtn.setAttribute("aria-pressed", liked ? "true" : "false");
      recBtn.textContent = recommended ? "Recommended" : "Recommend";
      recBtn.className = recommended ? "btn primary" : "btn";
      recBtn.setAttribute("aria-pressed", recommended ? "true" : "false");
    }

    function loadStats() {
      return api("GET", "/songs/" + songId + "/community")
        .then(function (body) { stats = body.data; renderStats(); })
        .catch(function (error) { console.error(error); });
    }

    function toggle(kind) {
      if (!currentUser) { promptLogin(flash, "Log in to like or recommend songs."); return; }
      var active = stats.me && (kind === "like" ? stats.me.liked : stats.me.recommended);
      api(active ? "DELETE" : "PUT", "/songs/" + songId + "/reactions/" + kind)
        .then(function () { setFlash(flash, ""); return loadStats(); })
        .catch(function (error) { setFlash(flash, describe(error), true); });
    }

    function refreshAll() {
      return Promise.all([loadComments(true), loadStats()]);
    }

    function renderComment(c, isReply) {
      var node = el("div", { className: "comment" });
      if (c.state !== "visible") {
        node.appendChild(el("p", { className: "muted", text: c.placeholder }));
        return node;
      }
      var mine = !!(currentUser && c.author && c.author.id === currentUser.id);
      var meta = c.author.username + " | " + formatWhen(c.created_at) + (c.edited_at ? " | edited" : "");
      var actions = el("div", { className: "row-actions" });
      var area = el("div");
      node.appendChild(el("p", { className: "muted", text: meta }));
      node.appendChild(el("div", { className: "comment-body", text: c.body }));
      node.appendChild(actions);
      node.appendChild(area);

      function addAction(label, handler) {
        actions.appendChild(el("button", { type: "button", className: "btn", text: label, onclick: handler }));
      }

      function openReply() {
        if (!currentUser) { promptLogin(flash, "Log in to reply."); return; }
        clear(area);
        area.appendChild(commentForm({
          label: "Your reply", submitLabel: "Reply", rows: 2,
          onSubmit: function (body) {
            return api("POST", "/songs/" + songId + "/comments", { body: body, parent_id: c.id }).then(refreshAll);
          },
          onCancel: function () { clear(area); },
        }));
      }

      function openEdit() {
        clear(area);
        area.appendChild(commentForm({
          label: "Edit your comment", initial: c.body, submitLabel: "Save",
          onSubmit: function (body) {
            return api("PATCH", "/comments/" + c.id, { body: body }).then(refreshAll);
          },
          onCancel: function () { clear(area); },
        }));
      }

      function doDelete() {
        if (!window.confirm("Delete this comment? This cannot be undone.")) return;
        api("DELETE", "/comments/" + c.id)
          .then(refreshAll)
          .catch(function (error) { setFlash(flash, describe(error), true); });
      }

      function openReport() {
        if (!currentUser) { promptLogin(flash, "Log in to report a comment."); return; }
        clear(area);
        var reason = el("select", { name: "reason" }, REPORT_REASONS.map(function (r) {
          return el("option", { value: r[0], text: r[1] });
        }));
        var details = el("input", { type: "text", name: "details", maxlength: 400, placeholder: "Anything we should know? (optional)" });
        var note = el("p", { className: "error", role: "alert" });
        area.appendChild(el("form", {
          className: "stack",
          onsubmit: function (event) {
            event.preventDefault();
            var payload = { reason: reason.value };
            if (details.value.trim()) payload.details = details.value.trim();
            api("POST", "/comments/" + c.id + "/report", payload)
              .then(function () {
                clear(area);
                setFlash(flash, "Thank you. A moderator will take a look.", false);
                return refreshAll();
              })
              .catch(function (error) { setFlash(note, describe(error), true); });
          },
        }, [
          el("label", {}, [text("Why are you reporting this?"), reason]),
          el("label", {}, [text("Details"), details]),
          el("div", { className: "row-actions" }, [
            el("button", { type: "submit", className: "btn primary", text: "Send report" }),
            el("button", { type: "button", className: "btn", text: "Cancel", onclick: function () { clear(area); } }),
          ]),
          note,
        ]));
      }

      if (!isReply) addAction("Reply", openReply);
      if (mine) {
        addAction("Edit", openEdit);
        addAction("Delete", doDelete);
      } else {
        addAction("Report", openReport);
      }
      return node;
    }

    function renderThread(thread) {
      var node = renderComment(thread, false);
      var replies = el("div", { className: "replies" });
      (thread.replies || []).forEach(function (reply) {
        replies.appendChild(renderComment(reply, true));
      });
      if (replies.childNodes.length) node.appendChild(replies);
      return node;
    }

    function loadComments(reset) {
      if (reset) state.page = 1;
      var requested = state.page;
      return api("GET", "/songs/" + songId + "/comments?per_page=" + state.perPage + "&page=" + requested)
        .then(function (body) {
          if (reset) clear(list);
          body.data.forEach(function (thread) { list.appendChild(renderThread(thread)); });
          if (!list.childNodes.length) {
            list.appendChild(el("p", { className: "muted", text: "No comments yet. Start the conversation." }));
          }
          moreBtn.hidden = !(body.meta.total > requested * body.meta.per_page);
        })
        .catch(function (error) {
          console.error(error);
          setFlash(flash, "Could not load the comments. Please try again.", true);
        });
    }

    function buildComposer() {
      clear(composer);
      if (!currentUser) {
        var prompt = el("p", { className: "muted" });
        promptLogin(prompt, "Log in to join the conversation.");
        composer.appendChild(prompt);
        return;
      }
      composer.appendChild(commentForm({
        label: "Add a comment", submitLabel: "Post",
        onSubmit: function (body) {
          return api("POST", "/songs/" + songId + "/comments", { body: body }).then(refreshAll);
        },
      }));
    }

    var panel = el("section", { className: "community" }, [
      el("h2", { text: "Community" }),
      statsLine,
      el("div", { className: "row-actions" }, [likeBtn, recBtn]),
      flash,
      el("h2", { text: "Comments" }),
      composer,
      list,
      moreBtn,
    ]);
    container.appendChild(panel);
    renderStats();
    buildComposer();
    refreshAll();
  }

  window.TrendsCommunity = {
    mountSongPanel: function (songId, container) {
      ready.then(function () { mountSongPanel(songId, container); });
    },
  };

  // ---------- charts ----------

  function initCharts() {
    var period = new URLSearchParams(window.location.search).get("period") === "all_time" ? "all_time" : "trending";
    api("GET", "/rankings/songs?limit=20&period=" + period).then(function (body) {
      var tabs = el("div", { className: "tabs" }, [
        el("a", { href: "/charts?period=trending", className: period === "trending" ? "btn primary" : "btn", text: "Trending this week" }),
        el("a", { href: "/charts?period=all_time", className: period === "all_time" ? "btn primary" : "btn", text: "All time" }),
      ]);
      var nodes = [el("h1", { text: "Community charts" }), tabs];
      if (!body.data.length) {
        nodes.push(el("p", { className: "message", text: "Nothing here yet. A song appears once at least 3 different people have liked, recommended or commented on it." }));
      } else {
        nodes.push(el("ul", { className: "items" }, body.data.map(function (item) {
          var s = item.song;
          var c = item.community;
          var artists = s.artists.map(function (a) { return a.name; }).join(", ");
          return el("li", {}, [
            el("a", { href: "/songs/" + s.id, text: "#" + item.rank + " " + s.title }),
            el("span", { className: "badge", text: artists }),
            el("p", { className: "muted", text: "Score " + c.score + " | " + c.recommends + " recommended | " + c.likes + " likes | " + c.engaged_users + " people" }),
          ]);
        })));
      }
      nodes.push(el("p", { className: "muted", text: body.meta.note }));
      show(nodes);
    }).catch(function (error) {
      console.error(error);
      showMessage("Could not load the charts. Please try again.");
    });
  }

  // ---------- discussions ----------

  function initDiscussions() {
    var pageNumber = parseInt(new URLSearchParams(window.location.search).get("page"), 10);
    if (!(pageNumber >= 1)) pageNumber = 1;
    var perPage = 15;
    api("GET", "/discussions/recent?per_page=" + perPage + "&page=" + pageNumber).then(function (body) {
      var nodes = [el("h1", { text: "Latest discussions" })];
      if (!body.data.length) {
        nodes.push(el("p", { className: "message", text: "No discussions yet. Open a song and start one." }));
      } else {
        nodes.push(el("ul", { className: "items" }, body.data.map(function (item) {
          var c = item.comment;
          var s = item.song;
          return el("li", {}, [
            el("p", { className: "muted" }, [
              text(c.author.username + " on "),
              el("a", { href: "/songs/" + s.id, text: s.title }),
              text(" | " + formatWhen(c.created_at)),
            ]),
            el("div", { className: "comment-body", text: c.body }),
          ]);
        })));
      }
      var pager = [];
      if (pageNumber > 1) pager.push(el("a", { href: "/discussions?page=" + (pageNumber - 1), text: "Newer" }));
      if (body.meta.total > pageNumber * perPage) pager.push(el("a", { href: "/discussions?page=" + (pageNumber + 1), text: "Older" }));
      if (pager.length) nodes.push(el("p", { className: "pager" }, pager));
      show(nodes);
    }).catch(function (error) {
      console.error(error);
      showMessage("Could not load the discussions. Please try again.");
    });
  }

  // ---------- start ----------

  if (page === "login" || page === "register") initAuthPage(page);
  else if (page === "charts") initCharts();
  else if (page === "discussions") initDiscussions();
})();