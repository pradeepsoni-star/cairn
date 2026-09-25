"""The terminal side of Cairn.

Everything the web page can do is here too, because a tool that only works
when a browser is open is not much use inside a script, a scheduled task or
an SSH session. argparse rather than a CLI framework: one less dependency on
a tool people are asked to install on a work machine.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cairn.config import Settings, data_dir


def _out(text: str = "") -> None:
    # Windows terminals still trip over box-drawing characters in some code
    # pages. Degrading to ASCII beats a UnicodeEncodeError on startup.
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"))


def cmd_index(args: argparse.Namespace) -> int:
    from cairn import indexer
    from cairn.db import session

    settings = Settings.load()
    if not settings.folder_paths():
        _out("No folders chosen. Run:  cairn folders --add \"<path>\"")
        return 1

    _out("Reading:")
    for folder in settings.folder_paths():
        _out(f"  {folder}")
    _out()

    def progress(p) -> None:
        sys.stdout.write(
            f"\r  {p.scanned:,} scanned  {p.added:,} new  {p.updated:,} updated  "
            f"{p.unchanged:,} same  {p.unreadable:,} skipped   "
        )
        sys.stdout.flush()

    with session() as conn:
        result = indexer.reindex(conn, settings, on_progress=progress, full=args.full)
    sys.stdout.write("\r" + " " * 90 + "\r")
    if result.error:
        _out(result.error)
        return 1
    _out(
        f"Done in {result.elapsed:.0f}s: {result.added:,} new, {result.updated:,} updated, "
        f"{result.removed:,} gone, {result.unreadable:,} unreadable."
    )
    _out(f"{result.passages:,} passages added, {result.commitments} commitment(s) found.")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    from cairn.db import session
    from cairn.search import search

    query = " ".join(args.terms)
    with session() as conn:
        hits = search(conn, query, limit=args.limit)
    if not hits:
        _out(f"Nothing matches '{query}'.")
        return 1
    for index, hit in enumerate(hits, start=1):
        snippet = hit.snippet.replace("<mark>", "[").replace("</mark>", "]").replace("\n", " ")
        _out(f"{index:>2}. {hit.name}")
        _out(f"    {hit.folder}")
        _out(f"    {snippet[:200]}")
        _out()
    return 0


def cmd_brief(args: argparse.Namespace) -> int:
    from cairn import brief as briefing
    from cairn.db import session

    with session() as conn:
        _out(briefing.as_text(briefing.build(conn)))
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    from cairn import notes
    from cairn.db import session

    body = " ".join(args.text).strip()
    if not body:
        _out("Type the note after the command, or pipe it in.")
        if not sys.stdin.isatty():
            body = sys.stdin.read().strip()
        if not body:
            return 1
    with session() as conn:
        saved = notes.add(conn, body)
    _out(f"Saved note {saved['id']}.")
    for item in saved["commitments"]:
        due = f" (due {item['due']})" if item["due"] else ""
        _out(f"  picked up: {item['text']}{due}")
    return 0


def cmd_todo(args: argparse.Namespace) -> int:
    from datetime import date

    from cairn import commitments
    from cairn.dates import humanise
    from cairn.db import session

    with session() as conn:
        if args.done:
            commitments.complete(conn, args.done, True)
            _out(f"Ticked off {args.done}.")
            return 0
        if args.dismiss:
            commitments.dismiss(conn, args.dismiss)
            _out(f"Dismissed {args.dismiss}.")
            return 0
        if args.add:
            from cairn.dates import parse_due

            text = " ".join(args.add)
            item = commitments.Commitment(text, "me", parse_due(text), "manual", "manual:cli")
            commitments.store(conn, [item])
            _out(f"Added: {text}" + (f"  (due {item.due})" if item.due else ""))
            return 0

        items = commitments.open_items(conn, who=args.who or "")
        if not items:
            _out("Nothing open.")
            return 0
        today = date.today()
        for item in items:
            due = date.fromisoformat(item["due"]) if item["due"] else None
            mark = "!" if due and due < today else " "
            _out(f"{mark}{item['id']:>4}  {item['text'][:88]}")
            _out(f"       {humanise(due, today)}  -  {Path(item['source_ref']).name}")
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    from cairn import ai
    from cairn.db import session

    question = " ".join(args.question)
    settings = Settings.load()
    with session() as conn:
        try:
            result = ai.ask(conn, question, settings.ai_provider, settings.ai_model)
        except ai.NotConfigured as exc:
            _out(str(exc))
            return 1
    _out(result["answer"])
    if result["sources"]:
        _out()
        _out("From:")
        for source in result["sources"]:
            _out(f"  {source['name']}")
    return 0


def cmd_folders(args: argparse.Namespace) -> int:
    settings = Settings.load()
    if args.add:
        path = str(Path(args.add).expanduser().resolve())
        if not Path(path).is_dir():
            _out(f"Not a folder: {path}")
            return 1
        if path not in settings.folders:
            settings.folders.append(path)
            settings.save()
        _out(f"Watching {path}")
    elif args.remove:
        target = str(Path(args.remove).expanduser().resolve())
        settings.folders = [f for f in settings.folders if f != target]
        settings.save()
        _out(f"Stopped watching {target}")
    if not settings.folders:
        from cairn.config import default_watch_folders

        _out("Cairn is not reading anything yet - it only reads folders you name.")
        suggestions = default_watch_folders()
        if suggestions:
            _out()
            _out("You probably want one of these:")
            for folder in suggestions:
                _out(f'  cairn folders --add "{folder}"')
        return 0
    _out("Folders Cairn reads:")
    for folder in settings.folders:
        mark = " " if Path(folder).is_dir() else "?"
        _out(f" {mark} {folder}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    from cairn.db import session, stats

    with session() as conn:
        counts = stats(conn)
    _out(f"Data:      {data_dir()}")
    _out(f"Files:     {counts['files']:,}")
    _out(f"Passages:  {counts['passages']:,}")
    _out(f"Notes:     {counts['notes']:,}")
    _out(f"Open jobs: {counts['open_commitments']:,}")
    if counts["last_index"]:
        _out(f"Last swept {counts['last_index']}")
    if counts["by_kind"]:
        _out()
        _out("By type:")
        for kind, number in list(counts["by_kind"].items())[:12]:
            _out(f"  {kind:<8} {number:,}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from cairn.server import serve

    _out(f"Cairn is at http://{args.host}:{args.port}/   (Ctrl-C to stop)")
    serve(host=args.host, port=args.port, open_browser=not args.no_browser)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cairn",
        description="Find anything on your computer, and never lose a commitment again.",
    )
    subparsers = parser.add_subparsers(dest="command")

    p = subparsers.add_parser("serve", help="open the Cairn window (default)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(func=cmd_serve)

    p = subparsers.add_parser("index", help="read your folders into the index")
    p.add_argument("--full", action="store_true", help="re-read every file, not just changed ones")
    p.set_defaults(func=cmd_index)

    p = subparsers.add_parser("search", help="search everything indexed")
    p.add_argument("terms", nargs="+")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_search)

    p = subparsers.add_parser("brief", help="what needs you today")
    p.set_defaults(func=cmd_brief)

    p = subparsers.add_parser("note", help="jot something down")
    p.add_argument("text", nargs="*")
    p.set_defaults(func=cmd_note)

    p = subparsers.add_parser("todo", help="open commitments")
    p.add_argument("--who", choices=["me", "them"], default="")
    p.add_argument("--add", nargs="+", help="add one by hand")
    p.add_argument("--done", type=int, metavar="ID")
    p.add_argument("--dismiss", type=int, metavar="ID")
    p.set_defaults(func=cmd_todo)

    p = subparsers.add_parser("ask", help="ask a question of your documents (needs a key)")
    p.add_argument("question", nargs="+")
    p.set_defaults(func=cmd_ask)

    p = subparsers.add_parser("folders", help="choose what Cairn reads")
    p.add_argument("--add", metavar="PATH")
    p.add_argument("--remove", metavar="PATH")
    p.set_defaults(func=cmd_folders)

    p = subparsers.add_parser("stats", help="what is in the index")
    p.set_defaults(func=cmd_stats)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        # Bare `cairn` opens the window, which is what someone typing it once
        # is almost certainly after.
        args = parser.parse_args(["serve"])
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        _out()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
