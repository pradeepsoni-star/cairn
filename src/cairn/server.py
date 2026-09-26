"""The local web app.

Cairn's interface is a web page served from your own machine rather than a
native window, for one practical reason: it then looks and behaves the same
on Windows, macOS and Linux, and it installs with pip instead of with a
toolkit. Nothing is served to the network - the socket binds to the loopback
address and refuses to do otherwise.

Two protections are worth pointing out, because "it's only localhost" has
been the excuse behind a long line of unpleasant bugs.

* Any web page you have open can make requests to 127.0.0.1. So every
  endpoint that changes something, opens something or spends money requires
  a token that is minted at startup and handed only to the page this server
  itself served. A page on the internet cannot read it.

* The endpoint that opens a file will only open a path that is already in
  the index. Without that, a single crafted request turns a search tool into
  a way to launch arbitrary programs.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import Body, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from cairn import ai, brief, commitments, features, indexer, notes, search
from cairn.config import Settings, data_dir, default_watch_folders
from cairn.db import connect, stats
from cairn.permissions import Denied, Permission, Permissions, recent_activity, record

WEB_DIR = Path(__file__).parent / "web"
TOKEN = secrets.token_urlsafe(24)

app = FastAPI(title="Cairn", docs_url=None, redoc_url=None, openapi_url=None)

_conn = None
_lock = threading.Lock()
_index_state: dict = {"running": False, "progress": None, "stop": False}


def db():
    global _conn
    if _conn is None:
        _conn = connect()
    return _conn


def guard(token: str | None) -> None:
    """Reject anything that did not come from the page we served."""
    if not token or not secrets.compare_digest(token, TOKEN):
        raise HTTPException(status_code=403, detail="Bad or missing token.")


def allow(permission: Permission) -> None:
    """Refuse the request unless the user has granted this capability.

    Deliberately a 403 with the plain-English reason attached, so the page can
    say what to switch on rather than showing "something went wrong".
    """
    try:
        Permissions.load().require(permission)
    except Denied as denied:
        raise HTTPException(status_code=403, detail=str(denied)) from denied


def feature_on(key: str) -> None:
    """Refuse the request if the feature is switched off.

    A feature that is off has no working endpoint. Hiding only the button
    would leave the capability reachable by anything that knows the URL.
    """
    if not Settings.load().has(key):
        raise HTTPException(
            status_code=404, detail=f"The {key} feature is switched off."
        )


def _app_mode_browsers() -> list[list[str]]:
    """Commands that open a URL in a plain window with no browser furniture.

    Chromium's `--app=` flag gives a window with no address bar, no tabs and
    no bookmarks - its own entry in the taskbar, and to anyone looking at it,
    an application. The page is identical; only the frame around it changes.

    This matters more than it sounds. Someone who double-clicks a program and
    lands in a browser tab, beside their email and twelve other tabs, has been
    told it is a web page rather than a thing they installed - and the first
    impression is the one that decides whether they open it again tomorrow.
    """
    if sys.platform == "win32":
        program_files = [
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", ""),
        ]
        candidates = []
        for base in filter(None, program_files):
            candidates += [
                Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe",
            ]
        return [[str(c)] for c in candidates if c.exists()]

    if sys.platform == "darwin":
        return [
            ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
            ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"],
        ]

    return [[name] for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge")]


def open_as_app(url: str) -> str:
    """Show Cairn in its own window, or fall back to an ordinary tab.

    Falling back matters: a machine with only Firefox, or a locked-down build
    with the flag disabled, must still end up looking at Cairn rather than at
    nothing. Returns what actually happened, so the caller can say so.
    """
    for command in _app_mode_browsers():
        try:
            subprocess.Popen(
                [*command, f"--app={url}", "--window-size=1200,860"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return "app window"
        except (OSError, subprocess.SubprocessError):
            continue

    import webbrowser

    return "browser tab" if webbrowser.open(url) else "nothing"


# ----------------------------------------------------------------- the page

# The interface is served with caching switched off. These files change when
# Cairn is updated, and a browser holding yesterday's app.js against today's
# server produces a broken screen that no amount of restarting fixes - the
# user has to know to hard-reload, which they do not. The files are a few
# kilobytes from local disk; there is nothing to save here.
_NO_CACHE = {"Cache-Control": "no-store, must-revalidate", "Pragma": "no-cache"}


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    # Never cached: it carries this run's token, and a stale one is a page
    # whose every button silently 403s.
    return HTMLResponse(html.replace("__CAIRN_TOKEN__", TOKEN), headers=_NO_CACHE)


@app.get("/app.js")
def script() -> FileResponse:
    return FileResponse(
        WEB_DIR / "app.js", media_type="application/javascript", headers=_NO_CACHE
    )


@app.get("/style.css")
def style() -> FileResponse:
    return FileResponse(WEB_DIR / "style.css", media_type="text/css", headers=_NO_CACHE)


# ------------------------------------------------------------------- state


def connector_summary() -> list[dict]:
    """Never let a broken connector take the whole state endpoint down with it.

    The state call is what the interface needs to render anything at all, so a
    missing optional package or an unreadable token file must degrade to "not
    connected", not to a blank screen.
    """
    try:
        from cairn.connectors import describe as describe_connectors

        return describe_connectors()
    except Exception:
        return []


@app.get("/api/state")
def state() -> dict:
    settings = Settings.load()
    permissions = Permissions.load()
    with _lock:
        return {
            "stats": stats(db()),
            "settings": settings.__dict__,
            "indexing": _index_state["running"],
            "progress": _index_state["progress"],
            "ai_available": ai.available(),
            "data_dir": str(data_dir()),
            "features": features.describe(settings.features, permissions),
            "permissions": permissions.as_list(),
            "presets": features.presets(),
            # What the setup screen starts with ticked. Distinct from what is
            # enabled, which on a fresh install is deliberately nothing.
            "default_features": features.default_enabled(),
            "connectors": connector_summary(),
            "setup_complete": settings.setup_complete,
            "suggested_folders": [
                folder for folder in default_watch_folders() if folder not in settings.folders
            ],
        }


@app.post("/api/settings")
def save_settings(payload: dict = Body(...), x_cairn_token: str | None = Header(None)) -> dict:
    guard(x_cairn_token)
    settings = Settings.load()
    for field in settings.__dataclass_fields__:
        if field in payload:
            setattr(settings, field, payload[field])
    settings.folders = [f for f in settings.folders if str(f).strip()]
    settings.save()
    return {"ok": True, "settings": settings.__dict__}


@app.get("/api/folders")
def folder_suggestions(path: str = Query("")) -> dict:
    """Browse the filesystem so a folder can be picked without typing a path.

    Read-only, directories only, and it never descends into the noise list -
    the picker should show you Documents, not node_modules.
    """
    from cairn.extract import should_skip_dir

    base = Path(path).expanduser() if path.strip() else Path.home()
    if not base.is_dir():
        base = Path.home()
    children = []
    try:
        for entry in sorted(base.iterdir(), key=lambda p: p.name.lower()):
            if entry.is_dir() and not should_skip_dir(entry.name):
                children.append({"name": entry.name, "path": str(entry)})
    except OSError:
        pass
    return {
        "current": str(base),
        "parent": str(base.parent) if base.parent != base else "",
        "children": children[:300],
    }


# ------------------------------------------------- permissions and features


@app.post("/api/permissions")
def set_permission(payload: dict = Body(...), x_cairn_token: str | None = Header(None)) -> dict:
    """Grant or revoke one capability. Revoking takes effect immediately."""
    guard(x_cairn_token)
    try:
        permission = Permission(str(payload.get("key", "")))
    except ValueError as exc:
        raise HTTPException(400, "No such permission.") from exc
    granted = bool(payload.get("granted"))
    permissions = Permissions.load()
    permissions.decide(permission, granted)
    return {"ok": True, "permissions": permissions.as_list()}


@app.post("/api/features")
def set_features(payload: dict = Body(...), x_cairn_token: str | None = Header(None)) -> dict:
    """Switch features on or off, and mark setup as done."""
    guard(x_cairn_token)
    settings = Settings.load()
    wanted = payload.get("features")
    if isinstance(wanted, list):
        settings.features = [key for key in wanted if key in features.BY_KEY]
    if "preset" in payload:
        settings.preset = str(payload.get("preset") or "")
    if payload.get("complete"):
        settings.setup_complete = True
        record("setup", "completed", ", ".join(settings.features))
    settings.save()
    return {"ok": True, "features": features.describe(settings.features, Permissions.load())}


@app.get("/api/model")
def model_settings() -> dict:
    """What is configured. Never contains a key."""
    from cairn.modelkeys import describe

    return describe()


@app.post("/api/model")
def save_model(payload: dict = Body(...), x_cairn_token: str | None = Header(None)) -> dict:
    """Save a key, an Ollama address, or which provider to prefer."""
    guard(x_cairn_token)
    from cairn.modelkeys import PROVIDERS, choose, describe, set_key, set_ollama_host

    if "key" in payload:
        provider = str(payload.get("provider", ""))
        if provider not in PROVIDERS:
            raise HTTPException(400, "Unknown provider.")
        set_key(provider, str(payload.get("key", "")))
        # Deliberately not logged with the key, and not logged at all beyond
        # the fact a key changed - the activity log is a plain file the user
        # is encouraged to read and might paste somewhere.
        record("model", "key changed", provider)
    if "ollama_host" in payload:
        set_ollama_host(str(payload.get("ollama_host", "")))
        record("model", "ollama address set", str(payload.get("ollama_host", "")))
    if "choose" in payload:
        choose(str(payload.get("choose", "auto")), str(payload.get("model", "")))
    return describe()


@app.post("/api/model/test")
def test_model(payload: dict = Body(default={}), x_cairn_token: str | None = Header(None)) -> dict:
    """Ask the provider one trivial question, so a wrong key is found here
    rather than the first time the user actually needs an answer."""
    guard(x_cairn_token)
    allow(Permission.SEND_TO_AI)
    from cairn import ai

    try:
        provider = ai.resolve(str(payload.get("provider", "auto")), str(payload.get("model", "")))
        reply = ai._call(provider, "Reply with the single word: ready", timeout=30.0)
    except ai.NotConfigured as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    return {"ok": True, "provider": f"{provider.name}/{provider.model}", "reply": reply[:120]}


@app.get("/api/connectors")
def list_connectors() -> dict:
    from cairn.connectors import describe as describe_connectors

    return {"connectors": describe_connectors()}


@app.post("/api/connectors/{key}/{action}")
def change_connector(
    key: str, action: str, x_cairn_token: str | None = Header(None)
) -> dict:
    """Link or unlink a connected service.

    Sign-in asks the service for exactly the permissions already granted here,
    so this endpoint cannot widen access on its own - it can only act on a
    decision the user already made on the permissions screen.
    """
    guard(x_cairn_token)
    from cairn.connectors import NotConnected
    from cairn.connectors import google as google_connector

    if key != "google":
        raise HTTPException(404, "No such connector.")
    try:
        if action == "connect":
            return {"ok": True, "status": google_connector.connect()}
        if action == "disconnect":
            google_connector.disconnect()
            return {"ok": True, "status": google_connector.status()}
        if action == "forget":
            with _lock:
                removed = google_connector.forget_indexed_mail(db())
            return {"ok": True, "removed": removed}
        if action == "sync":
            allow(Permission.GMAIL_READ)
            feature_on("email")
            from cairn.connectors.mail_index import sync

            with _lock:
                return {"ok": True, **sync(db())}
    except NotConnected as exc:
        raise HTTPException(400, str(exc)) from exc
    except Denied as denied:
        raise HTTPException(403, str(denied)) from denied
    raise HTTPException(400, "Unknown action.")


@app.post("/api/reset")
def reset_cairn(payload: dict = Body(...), x_cairn_token: str | None = Header(None)) -> dict:
    """Start over. Always backs up first; never removes without a copy."""
    guard(x_cairn_token)
    from cairn.reset import start_over

    erase = bool(payload.get("erase_everything"))
    if erase and str(payload.get("confirm", "")).strip().lower() != "erase":
        raise HTTPException(400, "Erasing everything needs to be confirmed by typing 'erase'.")
    with _lock:
        return start_over(db(), erase_everything=erase)


@app.get("/api/backups")
def backups() -> dict:
    from cairn.reset import list_backups

    return {"backups": list_backups(), "data_dir": str(data_dir())}


@app.get("/api/activity")
def activity() -> dict:
    """What Cairn has actually done, not what it promises it would do."""
    return {"events": recent_activity(), "path": str(data_dir() / "activity.log")}


# ------------------------------------------------------------------ search


@app.get("/api/search")
def do_search(q: str = Query(""), kind: str = Query(""), limit: int = Query(30)) -> dict:
    feature_on("search")
    with _lock:
        hits = search.search(db(), q, limit=limit, kind=kind)
    return {"query": q, "count": len(hits), "hits": [h.__dict__ for h in hits]}


@app.get("/api/passages")
def passages(path: str = Query(...), q: str = Query("")) -> dict:
    with _lock:
        return {"path": path, "passages": search.passages_for(db(), path, q)}


@app.post("/api/open")
def open_path(payload: dict = Body(...), x_cairn_token: str | None = Header(None)) -> dict:
    """Open a file, or reveal its folder, using the system's own handler."""
    guard(x_cairn_token)
    allow(Permission.OPEN_FILES)
    target = str(payload.get("path", ""))
    reveal = bool(payload.get("reveal"))
    if target.startswith("note:"):
        raise HTTPException(400, "Notes live inside Cairn, not on disk.")

    with _lock:
        known = db().execute("SELECT path FROM files WHERE path = ?", (target,)).fetchone()
    if not known:
        raise HTTPException(404, "That path is not in the index.")

    path = Path(target)
    if not path.exists():
        raise HTTPException(404, "The file has moved or been deleted.")

    try:
        if sys.platform == "win32":
            if reveal:
                subprocess.Popen(["explorer", "/select,", str(path)])
            else:
                os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R" if reveal else str(path)] + ([str(path)] if reveal else []))
        else:
            subprocess.Popen(["xdg-open", str(path.parent if reveal else path)])
    except OSError as exc:
        raise HTTPException(500, f"Could not open it: {exc}") from exc
    record(Permission.OPEN_FILES, "revealed" if reveal else "opened", target)
    return {"ok": True}


# ------------------------------------------------------------------- brief


@app.get("/api/brief")
def get_brief() -> dict:
    with _lock:
        return brief.build(db())


# ------------------------------------------------------------- commitments


@app.get("/api/commitments")
def list_commitments(who: str = Query("")) -> dict:
    feature_on("commitments")
    with _lock:
        return {"items": commitments.open_items(db(), who=who)}


@app.post("/api/commitments")
def add_commitment(payload: dict = Body(...), x_cairn_token: str | None = Header(None)) -> dict:
    guard(x_cairn_token)
    text = str(payload.get("text", "")).strip()
    if not text:
        raise HTTPException(400, "Nothing to add.")
    from cairn.dates import parse_due

    item = commitments.Commitment(
        text=text,
        who=str(payload.get("who", "me")),
        due=parse_due(str(payload.get("due") or text)),
        source="manual",
        source_ref=f"manual:{int(time.time())}",
    )
    with _lock:
        added = commitments.store(db(), [item])
        db().commit()
    return {"ok": True, "added": added, "due": item.due.isoformat() if item.due else None}


@app.post("/api/commitments/{item_id}/{action}")
def change_commitment(
    item_id: int, action: str, x_cairn_token: str | None = Header(None)
) -> dict:
    guard(x_cairn_token)
    with _lock:
        if action == "done":
            commitments.complete(db(), item_id, True)
        elif action == "undo":
            commitments.complete(db(), item_id, False)
        elif action == "dismiss":
            commitments.dismiss(db(), item_id)
        else:
            raise HTTPException(400, "Unknown action.")
        db().commit()
    return {"ok": True}


# ------------------------------------------------------------------- notes


@app.get("/api/notes")
def list_notes() -> dict:
    feature_on("notes")
    with _lock:
        return {"items": notes.recent(db())}


@app.post("/api/notes")
def add_note(payload: dict = Body(...), x_cairn_token: str | None = Header(None)) -> dict:
    guard(x_cairn_token)
    feature_on("notes")
    body = str(payload.get("body", "")).strip()
    if not body:
        raise HTTPException(400, "Nothing to save.")
    with _lock:
        return notes.add(db(), body)


@app.delete("/api/notes/{note_id}")
def remove_note(note_id: int, x_cairn_token: str | None = Header(None)) -> dict:
    guard(x_cairn_token)
    with _lock:
        notes.delete(db(), note_id)
    return {"ok": True}


# ----------------------------------------------------------------- indexing


def _run_index(full: bool) -> None:
    conn = connect()  # its own connection: this runs off the request thread
    try:
        def progress(p) -> None:
            _index_state["progress"] = p.as_dict()

        result = indexer.reindex(
            conn,
            on_progress=progress,
            should_stop=lambda: _index_state["stop"],
            full=full,
        )
        _index_state["progress"] = result.as_dict()
    except Exception as exc:  # a crashed sweep must still release the flag
        _index_state["progress"] = {"finished": True, "error": str(exc)}
    finally:
        conn.close()
        _index_state["running"] = False
        _index_state["stop"] = False


@app.post("/api/index/start")
def start_index(payload: dict = Body(default={}), x_cairn_token: str | None = Header(None)) -> dict:
    guard(x_cairn_token)
    allow(Permission.READ_FOLDERS)
    if _index_state["running"]:
        return {"ok": False, "reason": "already running"}
    _index_state.update({"running": True, "stop": False, "progress": None})
    threading.Thread(
        target=_run_index, args=(bool(payload.get("full")),), daemon=True
    ).start()
    return {"ok": True}


@app.post("/api/index/stop")
def stop_index(x_cairn_token: str | None = Header(None)) -> dict:
    guard(x_cairn_token)
    _index_state["stop"] = True
    return {"ok": True}


@app.get("/api/index/status")
def index_status() -> dict:
    return {"running": _index_state["running"], "progress": _index_state["progress"]}


# --------------------------------------------------------------------- ask


@app.post("/api/ask")
def ask(payload: dict = Body(...), x_cairn_token: str | None = Header(None)) -> JSONResponse:
    guard(x_cairn_token)
    feature_on("ask")
    allow(Permission.SEND_TO_AI)
    question = str(payload.get("question", "")).strip()
    if not question:
        raise HTTPException(400, "Ask something.")
    settings = Settings.load()
    try:
        with _lock:
            result = ai.ask(db(), question, settings.ai_provider, settings.ai_model)
        return JSONResponse(result)
    except ai.NotConfigured as exc:
        return JSONResponse({"answer": "", "error": str(exc), "sources": []}, status_code=200)
    except Exception as exc:
        return JSONResponse(
            {"answer": "", "error": f"The provider failed: {exc}", "sources": []},
            status_code=200,
        )


# --------------------------------------------------------------------- run


# How often the background sweep looks for changed files. Incremental scans of
# a folder that has not changed cost a second or two, so this can be frequent
# without being felt. The first one waits, because someone who has just opened
# Cairn for the first time is still choosing folders.
RESCAN_EVERY_SECONDS = 30 * 60
FIRST_RESCAN_AFTER_SECONDS = 5 * 60


def _keep_index_fresh(stop: threading.Event) -> None:
    """Re-read changed files on a timer, for as long as Cairn is open.

    This exists because `watch_changes` was a permission Cairn asked for in
    three of its four setup presets and then never used. Asking for something
    you do not use is exactly what the consent layer is supposed to prevent,
    so either the permission had to go or the behaviour had to arrive.

    It is checked on EVERY pass, not once at startup: someone who revokes it
    at 11:04 must not get another sweep at 11:30.
    """
    if stop.wait(FIRST_RESCAN_AFTER_SECONDS):
        return
    while not stop.is_set():
        try:
            permissions = Permissions.load()
            wanted = permissions.allowed(Permission.WATCH_CHANGES) and permissions.allowed(
                Permission.READ_FOLDERS
            )
            if wanted and not _index_state["running"] and Settings.load().folder_paths():
                _index_state.update({"running": True, "stop": False, "progress": None})
                _run_index(False)
        except Exception:
            # A background thread that dies takes the feature with it silently.
            # Whatever went wrong, try again at the next interval.
            _index_state["running"] = False
        if stop.wait(RESCAN_EVERY_SECONDS):
            return


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    import uvicorn

    if host not in ("127.0.0.1", "localhost", "::1"):
        # Cairn reads every document you own. It has no login, because it is
        # not meant to be reachable by anyone but you.
        raise SystemExit("Cairn binds to localhost only. It is not a server.")

    if open_browser:
        def launch() -> None:
            time.sleep(1.0)
            open_as_app(f"http://{host}:{port}/")

        threading.Thread(target=launch, daemon=True).start()

    stop = threading.Event()
    threading.Thread(target=_keep_index_fresh, args=(stop,), daemon=True).start()
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    finally:
        stop.set()
