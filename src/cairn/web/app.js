/* Cairn's front end. No framework, no build step - one file you can read.

   Two things here are load-bearing rather than cosmetic.

   ESCAPING. Search snippets arrive with <mark> around the matched words and
   the rest is raw text out of your documents. A document containing a stray
   angle bracket (every HTML file you own, for a start) would otherwise inject
   markup into this page. Everything is escaped first and only <mark> put back.

   THE NAVIGATION IS BUILT FROM STATE. A feature the user did not switch on
   has no button, and no working endpoint behind it either. The buttons are
   not the security boundary - the server is - but a screen that offers
   something the server will refuse is a screen that lies to you. */

const TOKEN = window.CAIRN_TOKEN;
const $ = (id) => document.getElementById(id);

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const marked = (s) => esc(s).replace(/&lt;mark&gt;/g, "<mark>").replace(/&lt;\/mark&gt;/g, "</mark>");

async function api(path, options = {}) {
  const headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
  if (options.method && options.method !== "GET") headers["X-Cairn-Token"] = TOKEN;
  const response = await fetch(path, Object.assign({}, options, { headers }));
  const text = await response.text();
  let body = {};
  try { body = text ? JSON.parse(text) : {}; } catch (e) { body = { detail: text }; }
  if (!response.ok) {
    const error = new Error(body.detail || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return body;
}

let toastTimer;
function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
}

const state = { view: "today", query: "", data: {}, draft: null };

/* ------------------------------------------------------------- formatting */

function whenText(due) {
  if (!due) return "";
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const then = new Date(due + "T00:00:00");
  const days = Math.round((then - today) / 86400000);
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days === -1) return "yesterday";
  if (days < 0) return `${-days} days overdue`;
  if (days < 7) return `in ${days} days`;
  // The year matters once it is not this one: "Apr 13" for a date that rolled
  // into next year reads as a date already gone.
  const sameYear = then.getFullYear() === today.getFullYear();
  return then.toLocaleDateString(undefined,
    sameYear ? { day: "numeric", month: "short" } : { day: "numeric", month: "short", year: "numeric" });
}

const isLate = (due) => due && new Date(due + "T00:00:00") < new Date(new Date().toDateString());

function shortLabel(path, siblings) {
  // Documents and OneDrive\Documents both end in "Documents", and two chips
  // reading "+ Documents" tell you nothing about which one you are adding.
  const parts = path.split(/[\\/]/).filter(Boolean);
  const last = parts[parts.length - 1];
  const clashes = siblings.filter((s) => s.split(/[\\/]/).filter(Boolean).pop() === last).length > 1;
  return clashes && parts.length > 1 ? `${parts[parts.length - 2]}\\${last}` : last;
}

function sourceLabel(ref) {
  if (!ref) return "";
  if (ref.startsWith("note:")) return "a note";
  if (ref.startsWith("gmail:")) return "an email";
  if (ref.startsWith("manual:")) return "added by hand";
  return ref.split(/[\\/]/).pop();
}

function itemRow(item) {
  const late = isLate(item.due);
  const when = whenText(item.due);
  const openable = item.source === "document";
  return `<div class="item" data-id="${item.id}">
    <button class="tick" title="Done"></button>
    <div class="item-body">
      <div class="item-text">${esc(item.text)}</div>
      <div class="item-meta">
        ${when ? `<span class="${late ? "late" : ""}">${esc(when)}</span>` : `<span>no date</span>`}
        ${openable
          ? `<a data-open="${esc(item.source_ref)}">${esc(sourceLabel(item.source_ref))}</a>`
          : `<span>${esc(sourceLabel(item.source_ref))}</span>`}
      </div>
    </div>
    <button class="x" title="Not a commitment">&times;</button>
  </div>`;
}

function itemList(items, emptyText) {
  if (!items || !items.length) return `<div class="empty">${esc(emptyText)}</div>`;
  return `<div class="card">${items.map(itemRow).join("")}</div>`;
}

const featureOn = (key) => (state.data.features || []).some((f) => f.key === key && f.enabled);
const permit = (key) => (state.data.permissions || []).find((p) => p.key === key) || {};

/* ------------------------------------------------------- first run: setup */

async function viewWelcome() {
  const data = state.data;
  // A fresh install has nothing enabled, so the ticks come from the suggested
  // defaults rather than from current state - otherwise the first thing a new
  // user sees is an empty form asking them to guess.
  const chosen = state.draft || {
    preset: "",
    features: data.setup_complete
      ? (data.features || []).filter((f) => f.enabled).map((f) => f.key)
      : [...(data.default_features || [])],
    permissions: {},
  };
  state.draft = chosen;

  const presetCards = (data.presets || []).map((preset) => `
    <button class="preset ${chosen.preset === preset.key ? "on" : ""}" data-preset="${esc(preset.key)}">
      <strong>${esc(preset.title)}</strong>
      <span>${esc(preset.who)}</span>
    </button>`).join("");

  const featureRows = (data.features || []).map((feature) => `
    <label class="pick">
      <input type="checkbox" data-feature="${esc(feature.key)}" ${chosen.features.includes(feature.key) ? "checked" : ""}>
      <span><strong>${esc(feature.title)}</strong><br><span class="muted">${esc(feature.pitch)}</span></span>
    </label>`).join("");

  $("main").innerHTML = `
    <h1>Welcome to Cairn</h1>
    <p class="sub">Cairn does nothing until you say what it may do. Pick what you
      want, allow only what that needs, and change your mind whenever you like.</p>

    <h2>1 &middot; What is this for?</h2>
    <div class="presets">${presetCards}</div>

    <h2>2 &middot; What should it do?</h2>
    <div class="card">${featureRows}</div>

    <h2>3 &middot; What may it do to get there?</h2>
    <p class="muted" style="margin:-4px 0 10px">Only the permissions your choices
      actually need are listed. Nothing is on until you switch it on.</p>
    <div class="card" id="needed"></div>

    <div class="row" style="margin-top:22px">
      <button class="btn primary" id="finish">Start using Cairn</button>
      <span class="muted">You can revoke any of this later, and see everything it did.</span>
    </div>`;

  renderNeeded();

  $("main").querySelectorAll("[data-preset]").forEach((button) => {
    button.onclick = () => {
      const preset = data.presets.find((p) => p.key === button.dataset.preset);
      chosen.preset = preset.key;
      chosen.features = [...preset.features];
      chosen.permissions = {};
      // A preset PROPOSES; it never grants. Every box it ticks is still a box
      // the user has to leave ticked and press Start on.
      preset.proposes.forEach((key) => { chosen.permissions[key] = true; });
      render();
    };
  });

  $("main").querySelectorAll("[data-feature]").forEach((box) => {
    box.onchange = () => {
      chosen.features = chosen.features.filter((k) => k !== box.dataset.feature);
      if (box.checked) chosen.features.push(box.dataset.feature);
      chosen.preset = "";
      renderNeeded();
    };
  });

  $("finish").onclick = async () => {
    for (const permission of data.permissions) {
      const wanted = !!chosen.permissions[permission.key];
      if (wanted !== (permission.granted === true)) {
        await api("/api/permissions", {
          method: "POST",
          body: JSON.stringify({ key: permission.key, granted: wanted }),
        });
      }
    }
    await api("/api/features", {
      method: "POST",
      body: JSON.stringify({ features: chosen.features, preset: chosen.preset, complete: true }),
    });
    state.draft = null;
    state.view = chosen.features.includes("search") ? "folders" : "today";
    toast("Set up. Nothing has been read yet.");
    await refreshCounts();
    render();
  };
}

function renderNeeded() {
  const chosen = state.draft;
  const data = state.data;
  const needed = new Set();
  (data.features || []).forEach((feature) => {
    if (!chosen.features.includes(feature.key)) return;
    feature.requires.forEach((k) => needed.add(k));
    feature.improves_with.forEach((k) => needed.add(k));
  });

  if (!needed.size) {
    $("needed").innerHTML = `<div class="empty">Nothing you picked needs any permission.
      Notes and the daily brief work entirely inside Cairn.</div>`;
    return;
  }

  const rows = (data.permissions || [])
    .filter((permission) => needed.has(permission.key))
    .map((permission) => permissionRow(permission, !!chosen.permissions[permission.key], true))
    .join("");
  $("needed").innerHTML = rows;

  $("needed").querySelectorAll("[data-perm]").forEach((box) => {
    box.onchange = () => {
      chosen.permissions[box.dataset.perm] = box.checked;
      chosen.preset = "";
    };
  });
}

function permissionRow(permission, checked, asCheckbox) {
  const danger = permission.tier === "act";
  const control = asCheckbox
    ? `<input type="checkbox" data-perm="${esc(permission.key)}" ${checked ? "checked" : ""}>`
    : `<button class="btn sm ${permission.granted ? "" : "primary"}" data-toggle="${esc(permission.key)}">
         ${permission.granted ? "Revoke" : "Allow"}</button>`;
  return `<div class="perm ${danger ? "danger" : ""}">
    <div class="perm-control">${control}</div>
    <div class="perm-body">
      <div class="perm-title">${esc(permission.title)}
        ${permission.leaves_machine ? `<span class="tag">leaves this machine</span>` : ""}
        ${danger ? `<span class="tag warn">cannot be undone</span>` : ""}</div>
      <div class="muted">${esc(permission.allows)}</div>
      <div class="muted" style="margin-top:3px"><strong>It cannot:</strong> ${esc(permission.does_not)}</div>
      ${asCheckbox ? "" : `<div class="muted" style="margin-top:4px">Currently ${esc(permission.state)}.</div>`}
    </div>
  </div>`;
}

/* ------------------------------------------------------------- permissions */

async function viewPermissions() {
  const data = state.data;
  const groups = [
    ["On this computer", (p) => p.tier === "local"],
    ["Reading connected services", (p) => p.tier === "read"],
    ["Changing things for you", (p) => p.tier === "write"],
    ["Acting as you", (p) => p.tier === "act"],
  ];
  const activity = await api("/api/activity");

  $("main").innerHTML = `
    <h1>Permissions</h1>
    <p class="sub">Everything Cairn may do, and a record of what it did. Revoking
      takes effect on the next action, not the next restart.</p>
    ${groups.map(([title, match]) => {
      const rows = (data.permissions || []).filter(match);
      if (!rows.length) return "";
      return `<h2>${esc(title)}</h2><div class="card">${rows.map((p) => permissionRow(p, p.granted, false)).join("")}</div>`;
    }).join("")}

    <h2>What Cairn has done</h2>
    <div class="card">
      ${activity.events.length ? `<table class="log">${activity.events.slice(0, 60).map((event) => `
        <tr><td class="muted">${esc(event.when)}</td>
            <td>${esc(event.permission)}</td>
            <td><strong>${esc(event.action)}</strong></td>
            <td class="muted">${esc(event.detail)}</td></tr>`).join("")}</table>`
        : `<div class="empty">Nothing yet.</div>`}
      <p class="muted" style="margin-top:12px">Full log: ${esc(activity.path)}</p>
    </div>`;

  $("main").querySelectorAll("[data-toggle]").forEach((button) => {
    button.onclick = async () => {
      const key = button.dataset.toggle;
      const permission = permit(key);
      if (!permission.granted && permission.tier === "act") {
        // The one class of permission where a mistake reaches another person.
        // A second, typed confirmation is not friction for its own sake.
        if (!(await confirmDanger(permission))) return;
      }
      await api("/api/permissions", {
        method: "POST",
        body: JSON.stringify({ key, granted: !permission.granted }),
      });
      toast(permission.granted ? "Revoked" : "Allowed");
      await refreshCounts();
      render();
    };
  });
}

function confirmDanger(permission) {
  // The artifact viewer refuses window.confirm, and a product should not
  // depend on a browser dialog for its most serious decision anyway.
  return new Promise((resolve) => {
    const shade = document.createElement("div");
    shade.className = "shade";
    shade.innerHTML = `<div class="dialog">
      <h3>${esc(permission.title)}</h3>
      <p>${esc(permission.does_not)}</p>
      <p class="muted">Type <strong>allow</strong> to confirm.</p>
      <input class="text" id="confirm-word" autocomplete="off">
      <div class="row" style="margin-top:14px;justify-content:flex-end">
        <button class="btn" id="confirm-no">Cancel</button>
        <button class="btn primary" id="confirm-yes" disabled>Allow this</button>
      </div>
    </div>`;
    document.body.appendChild(shade);
    const word = shade.querySelector("#confirm-word");
    const yes = shade.querySelector("#confirm-yes");
    word.focus();
    word.oninput = () => { yes.disabled = word.value.trim().toLowerCase() !== "allow"; };
    const close = (answer) => { shade.remove(); resolve(answer); };
    yes.onclick = () => close(true);
    shade.querySelector("#confirm-no").onclick = () => close(false);
    shade.onclick = (e) => { if (e.target === shade) close(false); };
  });
}

/* ------------------------------------------------------------- connections */

async function viewConnections() {
  const { connectors } = await api("/api/connectors");
  $("main").innerHTML = `
    <h1>Connections</h1>
    <p class="sub">Services Cairn can read for you. It asks each service for
      exactly the permissions you granted here and nothing more &mdash; so if you
      never allowed sending, the access it holds cannot send.</p>
    ${connectors.map(connectorCard).join("")}`;

  $("main").querySelectorAll("[data-conn]").forEach((button) => {
    button.onclick = async () => {
      const [key, action] = button.dataset.conn.split(":");
      button.disabled = true;
      button.textContent = action === "connect" ? "Waiting for your browser..." : "Working...";
      try {
        const result = await api(`/api/connectors/${key}/${action}`, { method: "POST" });
        toast(result.messages !== undefined
          ? `Read ${result.messages} message(s), ${result.commitments} commitment(s)`
          : result.removed !== undefined
            ? `Removed ${result.removed} message(s) from the index`
            : "Done");
      } catch (error) {
        toast(error.message);
      }
      await refreshCounts();
      render();
    };
  });
}

function connectorCard(connector) {
  const status = connector.status || {};
  const granted = connector.granted || [];
  const scopes = status.requested_scopes || [];

  let body;
  if (!granted.length) {
    body = `<p class="muted">You have not allowed anything for this service yet.
      Grant what you want on the <a data-go="permissions">Permissions</a> screen and
      Cairn will ask ${esc(connector.title.split(" ")[0])} for exactly that.</p>`;
  } else if (!status.has_client_secret) {
    body = `<p class="muted">${esc(connector.setup_note)}</p>
      <p class="muted">Cairn is looking for the file at:<br>
      <code>${esc((status.client_secret_path || "") || "the Cairn folder")}</code></p>`;
  } else if (!status.connected) {
    body = `<p class="muted">Ready to sign in. Cairn will ask for:</p>
      <ul class="scopes">${scopes.map((s) => `<li>${esc(s.split("/").pop())}</li>`).join("")}</ul>
      <button class="btn primary" data-conn="${esc(connector.key)}:connect">Sign in</button>`;
  } else {
    body = `<p><strong>Connected</strong>${status.account ? ` as ${esc(status.account)}` : ""}</p>
      ${status.needs_reconsent
        ? `<p class="muted">You have allowed something new since signing in, so the
             access Cairn holds cannot do it yet. Sign in again to include it.</p>
           <button class="btn primary" data-conn="${esc(connector.key)}:connect">Sign in again</button>`
        : ""}
      <ul class="scopes">${(status.token_scopes || []).map((s) => `<li>${esc(s.split("/").pop())}</li>`).join("")}</ul>
      <div class="row">
        ${featureOn("email") ? `<button class="btn" data-conn="${esc(connector.key)}:sync">Read my recent mail</button>` : ""}
        <button class="btn" data-conn="${esc(connector.key)}:disconnect">Disconnect</button>
        <button class="btn" data-conn="${esc(connector.key)}:forget">Remove indexed mail</button>
      </div>
      <p class="muted" style="margin-top:8px">Disconnecting forgets the account but
        keeps what was already read. Removing is the separate button, because they
        are different things to want.</p>`;
  }

  return `<div class="card">
    <h3 style="margin:0 0 4px">${esc(connector.title)}</h3>
    <p class="muted" style="margin:0 0 12px">${esc(connector.blurb)}</p>
    ${body}
  </div>`;
}

/* ------------------------------------------------------------------ views */

async function viewToday() {
  const brief = await api("/api/brief");
  state.data.brief = brief;
  const sections = [
    ["Past their date", brief.overdue],
    ["Due today", brief.due_today],
    ["This week", brief.due_soon],
    ["Later", brief.due_later],
    ["Waiting on someone else", brief.waiting_on],
    ["No date on them", brief.undated],
  ].filter(([, items]) => items && items.length);

  const changed = brief.changed_files.length
    ? `<h2>Changed in the last few days</h2><div class="card">${brief.changed_files.map((f) =>
        `<div class="item"><div class="item-body">
           <div class="item-text">${f.path.startsWith("gmail:") || f.path.startsWith("note:")
             ? esc(f.name) : `<a data-open="${esc(f.path)}">${esc(f.name)}</a>`}</div>
           <div class="item-meta"><span>${esc(f.folder)}</span></div>
         </div></div>`).join("")}</div>`
    : "";

  const body = sections.length
    ? sections.map(([title, items]) => `<h2>${title}</h2>${itemList(items, "")}`).join("")
    : `<div class="empty">Nothing on your plate. Notes and documents you add will show up here.</div>`;

  $("main").innerHTML = `
    <h1>Today</h1>
    <p class="sub">${new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}</p>
    <div class="headline">${esc(brief.headline)}</div>
    ${body}
    ${changed}`;
}

async function runSearch() {
  const query = $("q").value.trim();
  state.query = query;
  const results = $("results");
  if (!query) { results.innerHTML = ""; return; }
  results.innerHTML = `<div class="empty">Searching...</div>`;
  const data = await api("/api/search?q=" + encodeURIComponent(query));
  if (!data.hits.length) {
    results.innerHTML = `<div class="empty">Nothing matches "${esc(query)}".<br>
      <span class="muted">If you expected something, check the folder is listed under Folders.</span></div>`;
    return;
  }
  results.innerHTML = `<p class="muted" style="margin:16px 0 10px">${data.count} result(s)</p>` +
    data.hits.map((hit) => {
      const onDisk = !hit.path.startsWith("gmail:") && !hit.path.startsWith("note:");
      return `<div class="hit" data-path="${esc(hit.path)}">
        <div class="hit-top"><span class="hit-name">${esc(hit.name)}</span>
          <span class="hit-kind">${esc(hit.kind)}</span></div>
        <div class="hit-folder">${esc(hit.folder)}</div>
        <div class="hit-snip">${marked(hit.snippet)}</div>
        <div class="hit-actions">
          ${onDisk ? `<button class="btn sm" data-act="open">Open</button>
                      <button class="btn sm" data-act="reveal">Show in folder</button>` : ""}
          <button class="btn sm" data-act="peek">Read here</button>
        </div>
        <div class="peek"></div>
      </div>`;
    }).join("");
}

function viewSearch() {
  $("main").innerHTML = `
    <h1>Search</h1>
    <p class="sub">Every word inside everything Cairn has read - not just the file names.</p>
    <div class="searchbar">
      <input id="q" placeholder='Try: invoice march   or  "exact phrase"  or  budg*' value="${esc(state.query)}">
      <kbd>/</kbd>
    </div>
    <div id="results"></div>`;
  const box = $("q");
  box.focus();
  box.selectionStart = box.value.length;
  let timer;
  box.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(runSearch, 220); });
  box.addEventListener("keydown", (e) => { if (e.key === "Enter") { clearTimeout(timer); runSearch(); } });
  if (state.query) runSearch();
}

async function viewTodo() {
  const [mine, theirs] = await Promise.all([
    api("/api/commitments?who=me"),
    api("/api/commitments?who=them"),
  ]);
  $("main").innerHTML = `
    <h1>Commitments</h1>
    <p class="sub">Pulled out of your notes, documents and mail, sentence by sentence.
      Tick what is done, cross out what was never a commitment.</p>
    <div class="card">
      <div class="row">
        <input class="text grow" id="new-todo" placeholder="Add one by hand - write the date in, like 'send the quote on Friday'">
        <button class="btn primary" id="add-todo">Add</button>
      </div>
    </div>
    <h2>Yours (${mine.items.length})</h2>
    ${itemList(mine.items, "Nothing open.")}
    <h2>Waiting on others (${theirs.items.length})</h2>
    ${itemList(theirs.items, "Nothing outstanding from anyone else.")}`;

  const add = async () => {
    const box = $("new-todo");
    const text = box.value.trim();
    if (!text) return;
    const result = await api("/api/commitments", { method: "POST", body: JSON.stringify({ text }) });
    box.value = "";
    toast(result.due ? `Added, due ${result.due}` : "Added");
    render();
  };
  $("add-todo").onclick = add;
  $("new-todo").addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
}

async function viewNotes() {
  const data = await api("/api/notes");
  $("main").innerHTML = `
    <h1>Notes</h1>
    <p class="sub">Type it here and forget it. Anything that reads like a promise
      becomes a commitment, with its date worked out.</p>
    <div class="card">
      <textarea id="note-body" rows="4" placeholder="Called the supplier. I'll send the revised figures on Thursday and Anita will confirm the shipping date."></textarea>
      <div class="row" style="margin-top:10px">
        <button class="btn primary" id="save-note">Save</button>
        <span class="muted">Ctrl+Enter</span>
      </div>
    </div>
    ${data.items.length ? data.items.map((note) => `
      <div class="card">
        <div style="white-space:pre-wrap">${esc(note.body)}</div>
        <div class="row" style="margin-top:10px">
          <span class="muted">${new Date(note.created_at * 1000).toLocaleString()}</span>
          <button class="btn sm" data-del="${note.id}" style="margin-left:auto">Delete</button>
        </div>
      </div>`).join("") : `<div class="empty">No notes yet.</div>`}`;

  const save = async () => {
    const box = $("note-body");
    const body = box.value.trim();
    if (!body) return;
    const result = await api("/api/notes", { method: "POST", body: JSON.stringify({ body }) });
    box.value = "";
    toast(result.duplicate
      ? "You already saved that one"
      : result.commitments_found === 1
        ? "Saved - 1 commitment picked up"
        : result.commitments_found
          ? `Saved - ${result.commitments_found} commitments picked up`
          : "Saved");
    render();
  };
  $("save-note").onclick = save;
  $("note-body").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) save();
  });
  $("main").querySelectorAll("[data-del]").forEach((button) => {
    button.onclick = async () => {
      await api("/api/notes/" + button.dataset.del, { method: "DELETE" });
      toast("Deleted");
      render();
    };
  });
}

function viewAsk() {
  const providers = state.data.ai_available || [];
  const allowed = permit("send_to_ai").granted;
  $("main").innerHTML = `
    <h1>Ask</h1>
    <p class="sub">A question answered from your own documents, with the files it came from named.</p>
    ${allowed ? "" : `<div class="card"><strong>Not allowed yet.</strong>
      <p class="muted" style="margin:6px 0 0">Asking sends your question and the
      matched paragraphs to an AI provider. Allow it under
      <a data-go="permissions">Permissions</a> if you want that.</p></div>`}
    ${providers.length || !allowed ? "" : `<div class="card"><strong>No model configured.</strong>
      <p class="muted" style="margin:6px 0 0">Set <code>ANTHROPIC_API_KEY</code>, <code>OPENAI_API_KEY</code> or
      <code>GEMINI_API_KEY</code> in your environment and restart Cairn, or run Ollama locally and set
      <code>OLLAMA_HOST</code>.</p></div>`}
    <div class="searchbar">
      <input id="question" placeholder="What did we agree on the delivery terms?" ${allowed ? "" : "disabled"}>
      <button class="btn primary" id="ask-go" ${allowed ? "" : "disabled"}>Ask</button>
    </div>
    <div id="answer"></div>`;

  if (!allowed) return;
  const go = async () => {
    const question = $("question").value.trim();
    if (!question) return;
    $("answer").innerHTML = `<div class="empty">Reading your files...</div>`;
    let result;
    try {
      result = await api("/api/ask", { method: "POST", body: JSON.stringify({ question }) });
    } catch (error) {
      $("answer").innerHTML = `<div class="card"><strong>Cannot answer</strong>
        <p class="muted" style="margin:6px 0 0">${esc(error.message)}</p></div>`;
      return;
    }
    if (result.error) {
      $("answer").innerHTML = `<div class="card"><strong>Cannot answer</strong>
        <p class="muted" style="margin:6px 0 0">${esc(result.error)}</p></div>`;
      return;
    }
    $("answer").innerHTML = `
      <div class="card"><div class="answer">${esc(result.answer)}</div></div>
      ${result.sources.length ? `<h2>From</h2><div class="card">${result.sources.map((s) =>
        `<div class="item"><div class="item-body"><div class="item-text">
          <a data-open="${esc(s.path)}">${esc(s.name)}</a></div></div></div>`).join("")}</div>` : ""}
      ${result.provider ? `<p class="muted">answered by ${esc(result.provider)}</p>` : ""}`;
  };
  $("ask-go").onclick = go;
  $("question").addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  $("question").focus();
}

async function viewFolders() {
  const data = state.data;
  const settings = data.settings;
  const running = data.indexing;
  const progress = data.progress || {};
  const allowed = permit("read_folders").granted;

  $("main").innerHTML = `
    <h1>Folders</h1>
    <p class="sub">Cairn reads these folders and nothing else. It never changes a
      file, and nothing read here leaves this machine.</p>

    ${allowed ? "" : `<div class="card"><strong>Not allowed to read anything yet.</strong>
      <p class="muted" style="margin:6px 0 0">Allow "Read the folders you choose"
      under <a data-go="permissions">Permissions</a> and this will work.</p></div>`}

    <div class="card">
      ${settings.folders.length ? settings.folders.map((folder) => `
        <div class="folder-row">
          <span class="path">${esc(folder)}</span>
          <button class="btn sm" data-drop="${esc(folder)}">Remove</button>
        </div>`).join("") : `<div class="empty">Nothing yet. Cairn reads only what you put here.</div>`}
      ${(data.suggested_folders || []).length ? `
        <p class="muted" style="margin:14px 0 6px">Suggestions:</p>
        <div>${data.suggested_folders.map((folder) =>
          `<button class="btn sm" data-take="${esc(folder)}" title="${esc(folder)}" style="margin:0 6px 6px 0">+ ${esc(shortLabel(folder, data.suggested_folders))}</button>`).join("")}</div>` : ""}
      <div class="row" style="margin-top:12px">
        <button class="btn" id="browse">Add a folder...</button>
        <button class="btn primary" id="do-index" ${running || !allowed ? "disabled" : ""}>
          ${running ? "Reading..." : "Read them now"}</button>
        ${running ? `<button class="btn" id="stop-index">Stop</button>` : ""}
      </div>
      <div id="picker"></div>
      <div id="progress">${running ? progressHtml(progress) : ""}</div>
    </div>

    <h2>What is indexed</h2>
    <div class="card">
      <p style="margin:0 0 10px"><strong>${(data.stats.files || 0).toLocaleString()}</strong> items,
        <strong>${(data.stats.passages || 0).toLocaleString()}</strong> passages
        ${data.stats.last_index ? `&middot; last read ${esc(data.stats.last_index)}` : ""}</p>
      <div>${Object.entries(data.stats.by_kind || {}).map(([kind, n]) =>
        `<span class="chip">${esc(kind)} ${n.toLocaleString()}</span>`).join("") || `<span class="muted">nothing yet</span>`}</div>
    </div>

    <h2>Settings</h2>
    <div class="card">
      <div class="row" style="margin-bottom:12px">
        <label class="grow">Skip files larger than</label>
        <input class="text" style="width:90px" id="maxmb" type="number" min="1" max="500" value="${settings.max_file_mb}"> MB
      </div>
      <div class="row">
        <label class="grow"><input type="checkbox" id="scan-docs" ${settings.scan_documents_for_commitments ? "checked" : ""}>
          Look for commitments inside documents, not just notes</label>
      </div>
      <div class="row" style="margin-top:14px">
        <button class="btn primary" id="save-settings">Save</button>
        <span class="muted">Data lives in ${esc(data.data_dir)}</span>
      </div>
    </div>`;

  $("main").querySelectorAll("[data-drop]").forEach((button) => {
    button.onclick = async () => {
      const folders = settings.folders.filter((f) => f !== button.dataset.drop);
      await api("/api/settings", { method: "POST", body: JSON.stringify({ folders }) });
      await refreshCounts();
      render();
    };
  });
  $("main").querySelectorAll("[data-take]").forEach((button) => {
    button.onclick = async () => {
      const folders = settings.folders.concat([button.dataset.take]);
      await api("/api/settings", { method: "POST", body: JSON.stringify({ folders: [...new Set(folders)] }) });
      await refreshCounts();
      render();
    };
  });

  $("browse").onclick = () => showPicker("");

  $("do-index").onclick = async () => {
    try {
      await api("/api/index/start", { method: "POST", body: JSON.stringify({}) });
      toast("Reading your folders");
      pollIndex();
    } catch (error) { toast(error.message); }
  };
  if ($("stop-index")) {
    $("stop-index").onclick = async () => {
      await api("/api/index/stop", { method: "POST", body: "{}" });
      toast("Stopping after this file");
    };
  }

  $("save-settings").onclick = async () => {
    await api("/api/settings", {
      method: "POST",
      body: JSON.stringify({
        max_file_mb: parseInt($("maxmb").value, 10) || 40,
        scan_documents_for_commitments: $("scan-docs").checked,
      }),
    });
    toast("Saved");
  };

  if (running) pollIndex();
}

function progressHtml(p) {
  if (!p || !Object.keys(p).length) return `<p class="muted" style="margin-top:12px">Starting...</p>`;
  if (p.error) return `<p class="muted" style="margin-top:12px">${esc(p.error)}</p>`;
  const done = p.finished;
  return `<p class="muted" style="margin-top:12px">
      ${(p.scanned || 0).toLocaleString()} looked at &middot;
      ${(p.added || 0).toLocaleString()} new &middot;
      ${(p.updated || 0).toLocaleString()} updated &middot;
      ${(p.unreadable || 0).toLocaleString()} skipped
      ${p.current ? `&middot; ${esc(p.current)}` : ""}
      ${done ? ` &middot; finished in ${p.elapsed}s` : ""}
    </p>
    <div class="bar"><div style="width:${done ? 100 : Math.min(95, (p.scanned || 0) % 100)}%"></div></div>`;
}

let pollTimer;
async function pollIndex() {
  clearTimeout(pollTimer);
  const status = await api("/api/index/status");
  const box = $("progress");
  if (box) box.innerHTML = progressHtml(status.progress);
  await refreshCounts();
  if (status.running) {
    pollTimer = setTimeout(pollIndex, 900);
  } else if (state.view === "folders") {
    toast("Finished reading");
    setTimeout(render, 400);
  }
}

async function showPicker(path) {
  const data = await api("/api/folders?path=" + encodeURIComponent(path));
  $("picker").innerHTML = `
    <div class="row" style="margin-top:12px">
      <span class="muted grow">${esc(data.current)}</span>
      <button class="btn sm" id="pick-this">Add this folder</button>
    </div>
    <div class="picker">
      ${data.parent ? `<button data-go-folder="${esc(data.parent)}">.. up one level</button>` : ""}
      ${data.children.map((child) => `<button data-go-folder="${esc(child.path)}">${esc(child.name)}</button>`).join("")}
    </div>`;
  $("picker").querySelectorAll("[data-go-folder]").forEach((button) => {
    button.onclick = () => showPicker(button.dataset.goFolder);
  });
  $("pick-this").onclick = async () => {
    const folders = (state.data.settings.folders || []).concat([data.current]);
    await api("/api/settings", { method: "POST", body: JSON.stringify({ folders: [...new Set(folders)] }) });
    toast("Added");
    await refreshCounts();
    render();
  };
}

/* ------------------------------------------------------------ interaction */

document.addEventListener("click", async (event) => {
  const nav = event.target.closest(".nav");
  if (nav) { go(nav.dataset.view); return; }

  const link = event.target.closest("[data-go]");
  if (link) { go(link.dataset.go); return; }

  const opener = event.target.closest("[data-open]");
  if (opener) {
    try {
      await api("/api/open", { method: "POST", body: JSON.stringify({ path: opener.dataset.open }) });
    } catch (error) { toast(error.message); }
    return;
  }

  const action = event.target.closest("[data-act]");
  if (action) {
    const hit = action.closest(".hit");
    const path = hit.dataset.path;
    if (action.dataset.act === "peek") {
      const box = hit.querySelector(".peek");
      if (box.innerHTML) { box.innerHTML = ""; return; }
      const data = await api(`/api/passages?path=${encodeURIComponent(path)}&q=${encodeURIComponent(state.query)}`);
      box.innerHTML = data.passages.map((p) => `<div class="passage">${esc(p)}</div>`).join("");
    } else {
      try {
        await api("/api/open", {
          method: "POST",
          body: JSON.stringify({ path, reveal: action.dataset.act === "reveal" }),
        });
      } catch (error) { toast(error.message); }
    }
    return;
  }

  const item = event.target.closest(".item[data-id]");
  if (item) {
    if (event.target.classList.contains("tick")) {
      await api(`/api/commitments/${item.dataset.id}/done`, { method: "POST" });
      item.style.opacity = "0.35";
      toast("Done");
      refreshCounts();
      setTimeout(render, 500);
    } else if (event.target.classList.contains("x")) {
      await api(`/api/commitments/${item.dataset.id}/dismiss`, { method: "POST" });
      item.remove();
      toast("Dismissed");
      refreshCounts();
    }
  }
});

function go(view) {
  state.view = view;
  renderNav();
  render();
}

document.addEventListener("keydown", (event) => {
  const typing = /^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName);
  if (event.key === "/" && !typing && featureOn("search")) {
    event.preventDefault();
    if (state.view !== "search") go("search"); else $("q").focus();
  }
});

$("theme-toggle").onclick = () => {
  const now = document.documentElement.getAttribute("data-theme");
  const next = now === "dark" ? "light" : now === "light" ? "" : "dark";
  if (next) document.documentElement.setAttribute("data-theme", next);
  else document.documentElement.removeAttribute("data-theme");
  try { localStorage.setItem("cairn-theme", next); } catch (e) { /* private window */ }
};

try {
  const saved = localStorage.getItem("cairn-theme");
  if (saved) document.documentElement.setAttribute("data-theme", saved);
} catch (e) { /* ignore */ }

/* ------------------------------------------------------------------ shell */

function renderNav() {
  const data = state.data;
  if (!data.setup_complete) { $("nav").innerHTML = ""; return; }

  const counts = data.stats || {};
  const brief = data.brief;
  const entries = [
    ["today", "Today", brief ? (brief.overdue.length + brief.due_today.length) || "" : "", featureOn("brief")],
    ["search", "Search", "", featureOn("search")],
    ["todo", "Commitments", counts.open_commitments || "", featureOn("commitments")],
    ["notes", "Notes", counts.notes || "", featureOn("notes")],
    ["ask", "Ask", "", featureOn("ask")],
  ].filter(([, , , on]) => on);

  entries.push(["folders", "Folders", counts.files ? counts.files.toLocaleString() : "", true]);
  if ((data.connectors || []).length) entries.push(["connections", "Connections", "", true]);
  entries.push(["permissions", "Permissions", "", true]);

  // If the current view has just been switched off, fall back to one that exists.
  if (!entries.some(([key]) => key === state.view)) state.view = entries[0][0];

  $("nav").innerHTML = entries.map(([key, label, count]) => `
    <button class="nav ${state.view === key ? "on" : ""}" data-view="${key}">
      ${esc(label)} <span class="count">${esc(String(count))}</span>
    </button>`).join("");
}

async function refreshCounts() {
  try {
    const data = await api("/api/state");
    state.data = Object.assign(state.data, data);
    $("foot-status").textContent = data.stats.files
      ? `${data.stats.files.toLocaleString()} items indexed`
      : "nothing indexed yet";
    renderNav();
  } catch (e) { /* server restarting */ }
}

const VIEWS = {
  welcome: viewWelcome, today: viewToday, search: viewSearch, todo: viewTodo,
  notes: viewNotes, ask: viewAsk, folders: viewFolders,
  permissions: viewPermissions, connections: viewConnections,
};

async function render() {
  if (!state.data.setup_complete) state.view = "welcome";
  try {
    await (VIEWS[state.view] || viewToday)();
  } catch (e) {
    $("main").innerHTML = `<h1>Something went wrong</h1><p class="sub">${esc(e.message)}</p>`;
  }
  renderNav();
}

(async function boot() {
  await refreshCounts();
  render();
})();
