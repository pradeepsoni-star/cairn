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

from cairn import ai, brief, commitments, indexer, notes, search
from cairn.config import Settings, data_dir, default_watch_folders
from cairn.db import connect, stats

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


# ----------------------------------------------------------------- the page


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__CAIRN_TOKEN__", TOKEN))


@app.get("/app.js")
def script() -> FileResponse:
    return FileResponse(WEB_DIR / "app.js", media_type="application/javascript")


@app.get("/style.css")
def style() -> FileResponse:
    return FileResponse(WEB_DIR / "style.css", media_type="text/css")


# ------------------------------------------------------------------- state


@app.get("/api/state")
def state() -> dict:
    settings = Settings.load()
    with _lock:
        return {
            "stats": stats(db()),
            "settings": settings.__dict__,
            "indexing": _index_state["running"],
            "progress": _index_state["progress"],
            "ai_available": ai.available(),
            "data_dir": str(data_dir()),
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


# ------------------------------------------------------------------ search


@app.get("/api/search")
def do_search(q: str = Query(""), kind: str = Query(""), limit: int = Query(30)) -> dict:
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
    return {"ok": True}


# ------------------------------------------------------------------- brief


@app.get("/api/brief")
def get_brief() -> dict:
    with _lock:
        return brief.build(db())


# ------------------------------------------------------------- commitments


@app.get("/api/commitments")
def list_commitments(who: str = Query("")) -> dict:
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
    with _lock:
        return {"items": notes.recent(db())}


@app.post("/api/notes")
def add_note(payload: dict = Body(...), x_cairn_token: str | None = Header(None)) -> dict:
    guard(x_cairn_token)
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


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    import uvicorn

    if host not in ("127.0.0.1", "localhost", "::1"):
        # Cairn reads every document you own. It has no login, because it is
        # not meant to be reachable by anyone but you.
        raise SystemExit("Cairn binds to localhost only. It is not a server.")

    if open_browser:
        def launch() -> None:
            import webbrowser

            time.sleep(1.0)
            webbrowser.open(f"http://{host}:{port}/")

        threading.Thread(target=launch, daemon=True).start()

    uvicorn.run(app, host=host, port=port, log_level="warning")
