"""Turning a file on disk into text Cairn can search.

Every reader here follows the same contract: return the text, or return
nothing. A reader never raises, because one malformed PDF in a folder of
four thousand must not end the sweep - and the user will never know which
file it was. Failures are counted, not thrown.

The one non-obvious behaviour is cloud placeholders. OneDrive, Dropbox and
iCloud all leave zero-byte stubs on disk for files that live in the cloud.
Opening one triggers a download: silently, over the user's connection,
potentially gigabytes of it. Cairn detects those stubs and skips them. This
is the difference between a tool you leave running and one you uninstall.
"""

from __future__ import annotations

import os
import re
import stat
import sys
from pathlib import Path

# Folders that never contain anything a person is looking for, and which are
# large enough to dominate a sweep if walked. Matched on the folder's own
# name, never on any ancestor's, so a project that happens to live under a
# folder called "build" is still indexed.
SKIP_DIRS = frozenset(
    {
        ".git", ".hg", ".svn", ".idea", ".vscode", ".vs", "__pycache__",
        "node_modules", "bower_components", "vendor", "site-packages",
        ".venv", "venv", "env", ".env", ".tox", ".nox", ".mypy_cache",
        ".pytest_cache", ".ruff_cache", ".gradle", ".cargo", ".rustup",
        "dist", "build", "target", "out", "bin", "obj", ".next", ".nuxt",
        "$RECYCLE.BIN", "System Volume Information", "Windows", "Program Files",
        "Program Files (x86)", "AppData", "Library", "Applications",
        ".Trash", ".cache", "Cache", "Caches", "tmp", "temp", "Temp",
    }
)

PLAIN_TEXT = frozenset(
    {
        ".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv", ".json",
        ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".xml", ".html",
        ".htm", ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".h",
        ".cpp", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".sh", ".ps1",
        ".sql", ".r", ".m", ".swift", ".kt", ".scala", ".vue", ".svelte",
        ".css", ".scss", ".tex", ".bib", ".srt", ".vtt",
    }
)

RICH_TEXT = frozenset({".pdf", ".docx", ".xlsx", ".xlsm", ".pptx", ".rtf", ".epub"})

SUPPORTED = PLAIN_TEXT | RICH_TEXT


def kind_of(path: Path) -> str:
    return path.suffix.lower().lstrip(".") or "file"


def should_skip_dir(name: str) -> bool:
    return name in SKIP_DIRS or (name.startswith(".") and name not in {".", ".."})


def is_cloud_placeholder(path: Path) -> bool:
    """True for a file whose bytes are not actually on this disk.

    On Windows the file attributes say so outright. Elsewhere there is no
    reliable signal, so we do not guess - a wrong guess there would skip a
    real file, which is worse than reading a stub.
    """
    if sys.platform != "win32":
        return False
    try:
        attributes = path.stat().st_file_attributes  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        return False
    offline = getattr(stat, "FILE_ATTRIBUTE_OFFLINE", 0x1000)
    recall_open = getattr(stat, "FILE_ATTRIBUTE_RECALL_ON_OPEN", 0x40000)
    recall_access = getattr(stat, "FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS", 0x400000)
    return bool(attributes & (offline | recall_open | recall_access))


# --------------------------------------------------------------------- readers


def sanitise(text: str) -> str:
    """Make text safe to store.

    A lone surrogate - the unpaired half of an emoji, which turns up in files
    that were written by something that mangled its own encoding - cannot be
    encoded as UTF-8, and SQLite raises when you try to insert one. On a real
    machine this ended a 400-file sweep at file 410. Anything unpaired is
    dropped; the rest of the document is perfectly good.
    """
    if not text:
        return ""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        text = text.encode("utf-8", "ignore").decode("utf-8", "ignore")
    # NUL cannot appear in a SQLite text value either.
    return text.replace("\x00", "")


def _strip_markup(markup: str) -> str:
    """Text out of HTML, without the tags and without the entities.

    Indexing raw HTML puts &rdquo; and </div> into your search results and,
    worse, into the commitments lifted out of them.
    """
    import html as html_module

    without_scripts = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>", " ", markup, flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(r"<[^>]+>", " ", without_scripts)
    text = html_module.unescape(text)
    return re.sub(r"[ \t]{2,}", " ", text)


def _read_plain(path: Path) -> str:
    raw = path.read_bytes()
    # A file claiming to be text but full of NULs is a binary someone gave a
    # .txt name. Indexing its bytes produces search noise and nothing else.
    if b"\x00" in raw[:4096]:
        return ""
    text = ""
    for encoding in ("utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    if path.suffix.lower() in (".html", ".htm", ".xml", ".vue", ".svelte"):
        text = _strip_markup(text)
    return text


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            # A single unreadable page should not cost us the other 200.
            continue
    return "\n".join(parts)


def _read_docx(path: Path) -> str:
    import docx

    document = docx.Document(str(path))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _read_xlsx(path: Path) -> str:
    import warnings

    from openpyxl import load_workbook

    # openpyxl warns about extensions it drops on read. We are reading text,
    # not round-tripping the file, so the warning is noise in the middle of a
    # progress line.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        workbook = load_workbook(str(path), read_only=True, data_only=True)
        try:
            parts: list[str] = []
            for sheet in workbook.worksheets:
                parts.append(f"# {sheet.title}")
                for row in sheet.iter_rows(values_only=True):
                    cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
                    if cells:
                        parts.append(" | ".join(cells))
            return "\n".join(parts)
        finally:
            workbook.close()


def _read_pptx(path: Path) -> str:
    from pptx import Presentation

    deck = Presentation(str(path))
    parts: list[str] = []
    for number, slide in enumerate(deck.slides, start=1):
        parts.append(f"# Slide {number}")
        for shape in slide.shapes:
            text = getattr(shape, "text", "")
            if text and text.strip():
                parts.append(text.strip())
    return "\n".join(parts)


def _read_rtf(path: Path) -> str:
    from striprtf.striprtf import rtf_to_text

    return rtf_to_text(path.read_text(encoding="utf-8", errors="ignore"))


def _read_epub(path: Path) -> str:
    import zipfile

    parts: list[str] = []
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.lower().endswith((".xhtml", ".html", ".htm")):
                continue
            markup = archive.read(name).decode("utf-8", errors="ignore")
            parts.append(_strip_markup(markup))
    return "\n".join(parts)


_READERS = {
    ".pdf": _read_pdf,
    ".docx": _read_docx,
    ".xlsx": _read_xlsx,
    ".xlsm": _read_xlsx,
    ".pptx": _read_pptx,
    ".rtf": _read_rtf,
    ".epub": _read_epub,
}


class Unreadable(Exception):
    """The file exists and is wanted, but its text could not be got out."""


def extract(path: Path) -> str:
    """The text of one file. Raises Unreadable rather than returning junk."""
    suffix = path.suffix.lower()
    try:
        if suffix in _READERS:
            return sanitise(_READERS[suffix](path))
        if suffix in PLAIN_TEXT:
            return sanitise(_read_plain(path))
    except ImportError as exc:
        raise Unreadable(
            f"{suffix} needs an optional package: pip install 'cairn-desk[docs]' ({exc})"
        ) from exc
    except Exception as exc:
        raise Unreadable(f"{path.name}: {exc}") from exc
    raise Unreadable(f"{suffix or 'no extension'} is not a searchable format")


# ---------------------------------------------------------------------- chunks

CHUNK_CHARS = 1200
CHUNK_OVERLAP = 150


def chunk(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping passages.

    Overlap matters more than it looks: without it, a sentence that straddles
    a boundary is findable by neither half. The split prefers a paragraph
    break, then a sentence end, then a space, so a passage shown to the user
    reads as language rather than as a slice.
    """
    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = "\n".join(line for line in text.split("\n") if line.strip() or True).strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    passages: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            for separator in ("\n\n", ". ", "\n", " "):
                cut = window.rfind(separator)
                # Only honour a break in the last third; an early one would
                # produce a stub passage and waste the window.
                if cut > size * 0.6:
                    end = start + cut + len(separator)
                    break
        piece = text[start:end].strip()
        if piece:
            passages.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return passages


def walk(roots: list[Path], max_bytes: int, extra_excludes: frozenset[str] = frozenset()):
    """Yield every candidate file below the given roots.

    Symlinked directories are not followed. A loop through a symlink is the
    classic way an indexer ends up walking the same tree forever.
    """
    for root in roots:
        if not root.is_dir():
            continue
        for current, dirs, names in os.walk(root, topdown=True, followlinks=False):
            dirs[:] = [
                d for d in dirs if not should_skip_dir(d) and d.lower() not in extra_excludes
            ]
            for name in names:
                path = Path(current) / name
                if path.suffix.lower() not in SUPPORTED:
                    continue
                try:
                    info = path.stat()
                except OSError:
                    continue
                if info.st_size == 0 or info.st_size > max_bytes:
                    continue
                if is_cloud_placeholder(path):
                    continue
                yield path, info
