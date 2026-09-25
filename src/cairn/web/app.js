/* Cairn's front end. No framework, no build step - one file you can read.

   The only subtle thing here is escaping. Search snippets arrive with
   <mark> tags around the matched words, and the rest of the snippet is raw
   text out of your documents. A document containing a stray angle bracket
   (every HTML file you own, for a start) would otherwise inject markup into
   this page. So everything is escaped first and only <mark> is put back. */

const TOKEN = window.CAIRN_TOKEN;
const $ = (id) => document.getElementById(id);

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const marked = (s) => esc(s).replace(/&lt;mark&gt;/g, "<mark>").replace(/&lt;\/mark&gt;/g, "</mark>");

async function api(path, options = {}) {
  const headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
  if (options.method && options.method !== "GET") headers["X-Cairn-Token"] = TOKEN;
  const response = await fetch(path, Object.assign({}, options, { headers }));
  if (!response.ok) throw new Error((await response.text()).slice(0, 200));
  return response.json();
}

let toastTimer;
function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2200);
}

const state = { view: "today", query: "", data: {} };

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
           <div class="item-text"><a data-open="${esc(f.path)}">${esc(f.name)}</a></div>
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
  results.innerHTML = `<p class="muted" style="margin:16px 0 10px">${data.count} file(s)</p>` +
    data.hits.map((hit) => `<div class="hit" data-path="${esc(hit.path)}">
      <div class="hit-top"><span class="hit-name">${esc(hit.name)}</span>
        <span class="hit-kind">${esc(hit.kind)}</span></div>
      <div class="hit-folder">${esc(hit.folder)}</div>
      <div class="hit-snip">${marked(hit.snippet)}</div>
      <div class="hit-actions">
        <button class="btn sm" data-act="open">Open</button>
        <button class="btn sm" data-act="reveal">Show in folder</button>
        <button class="btn sm" data-act="peek">Read here</button>
      </div>
      <div class="peek"></div>
    </div>`).join("");
}

function viewSearch() {
  $("main").innerHTML = `
    <h1>Search</h1>
    <p class="sub">Every word inside every file Cairn has read - not just the file names.</p>
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
    <p class="sub">Pulled out of your notes and documents, sentence by sentence. Tick what is done, cross out what was never a commitment.</p>
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
    <p class="sub">Type it here and forget it. Anything that reads like a promise becomes a commitment, with its date worked out.</p>
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
  $("main").innerHTML = `
    <h1>Ask</h1>
    <p class="sub">A question answered from your own documents, with the files it came from named.</p>
    ${providers.length ? "" : `<div class="card"><strong>No model configured.</strong>
      <p class="muted" style="margin:6px 0 0">Set <code>ANTHROPIC_API_KEY</code>, <code>OPENAI_API_KEY</code> or
      <code>GEMINI_API_KEY</code> in your environment and restart Cairn, or run Ollama locally and set
      <code>OLLAMA_HOST</code>. Everything else in Cairn works without this.</p></div>`}
    <div class="searchbar">
      <input id="question" placeholder="What did we agree on the delivery terms?">
      <button class="btn primary" id="ask-go">Ask</button>
    </div>
    <div id="answer"></div>`;

  const go = async () => {
    const question = $("question").value.trim();
    if (!question) return;
    $("answer").innerHTML = `<div class="empty">Reading your files...</div>`;
    const result = await api("/api/ask", { method: "POST", body: JSON.stringify({ question }) });
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

async function viewSetup() {
  const data = await api("/api/state");
  state.data = Object.assign(state.data, data);
  const settings = data.settings;
  const running = data.indexing;
  const progress = data.progress || {};

  $("main").innerHTML = `
    <h1>Folders</h1>
    <p class="sub">Cairn reads these folders and nothing else. It never changes a file, and nothing leaves this machine.</p>

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
        <button class="btn primary" id="do-index" ${running ? "disabled" : ""}>
          ${running ? "Reading..." : "Read them now"}</button>
        ${running ? `<button class="btn" id="stop-index">Stop</button>` : ""}
      </div>
      <div id="picker"></div>
      <div id="progress">${running ? progressHtml(progress) : ""}</div>
    </div>

    <h2>What is indexed</h2>
    <div class="card">
      <p style="margin:0 0 10px"><strong>${(data.stats.files || 0).toLocaleString()}</strong> files,
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
      render();
    };
  });

  $("main").querySelectorAll("[data-take]").forEach((button) => {
    button.onclick = async () => {
      const folders = settings.folders.concat([button.dataset.take]);
      await api("/api/settings", { method: "POST", body: JSON.stringify({ folders: [...new Set(folders)] }) });
      render();
    };
  });

  $("browse").onclick = () => showPicker("");

  $("do-index").onclick = async () => {
    await api("/api/index/start", { method: "POST", body: JSON.stringify({}) });
    toast("Reading your folders");
    pollIndex();
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
  } else if (state.view === "setup") {
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
      ${data.parent ? `<button data-go="${esc(data.parent)}">.. up one level</button>` : ""}
      ${data.children.map((child) => `<button data-go="${esc(child.path)}">${esc(child.name)}</button>`).join("")}
    </div>`;
  $("picker").querySelectorAll("[data-go]").forEach((button) => {
    button.onclick = () => showPicker(button.dataset.go);
  });
  $("pick-this").onclick = async () => {
    const folders = (state.data.settings.folders || []).concat([data.current]);
    await api("/api/settings", { method: "POST", body: JSON.stringify({ folders: [...new Set(folders)] }) });
    toast("Added");
    render();
  };
}

/* ------------------------------------------------------------ interaction */

document.addEventListener("click", async (event) => {
  const nav = event.target.closest(".nav");
  if (nav) {
    state.view = nav.dataset.view;
    document.querySelectorAll(".nav").forEach((n) => n.classList.toggle("on", n === nav));
    render();
    return;
  }

  const opener = event.target.closest("[data-open]");
  if (opener) {
    try {
      await api("/api/open", { method: "POST", body: JSON.stringify({ path: opener.dataset.open }) });
    } catch (e) { toast("Could not open it - it may have moved"); }
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
      } catch (e) { toast("Could not open it - it may have moved"); }
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

document.addEventListener("keydown", (event) => {
  const typing = /^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName);
  if (event.key === "/" && !typing) {
    event.preventDefault();
    if (state.view !== "search") {
      state.view = "search";
      document.querySelectorAll(".nav").forEach((n) => n.classList.toggle("on", n.dataset.view === "search"));
      render();
    } else { $("q").focus(); }
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

/* ------------------------------------------------------------------ boot */

async function refreshCounts() {
  try {
    const data = await api("/api/state");
    state.data = Object.assign(state.data, data);
    $("c-todo").textContent = data.stats.open_commitments || "";
    $("c-notes").textContent = data.stats.notes || "";
    $("c-files").textContent = data.stats.files ? data.stats.files.toLocaleString() : "";
    $("foot-status").textContent = data.stats.files
      ? `${data.stats.files.toLocaleString()} files indexed`
      : "nothing indexed yet";
    const brief = state.data.brief;
    $("c-today").textContent = brief ? (brief.overdue.length + brief.due_today.length) || "" : "";
  } catch (e) { /* server restarting */ }
}

const VIEWS = { today: viewToday, search: viewSearch, todo: viewTodo, notes: viewNotes, ask: viewAsk, setup: viewSetup };

async function render() {
  try {
    await VIEWS[state.view]();
  } catch (e) {
    $("main").innerHTML = `<h1>Something went wrong</h1><p class="sub">${esc(e.message)}</p>`;
  }
  refreshCounts();
}

(async function boot() {
  await refreshCounts();
  // A brand new install has nothing to show on Today, so start where the
  // one useful action is: choosing what to read.
  if (!state.data.stats || !state.data.stats.files) {
    state.view = "setup";
    document.querySelectorAll(".nav").forEach((n) => n.classList.toggle("on", n.dataset.view === "setup"));
  }
  render();
})();
