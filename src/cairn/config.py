"""Where Cairn keeps its things, and what the user has told it.

One rule governs this module: Cairn never writes outside its own data
directory unless the user explicitly asks for a file somewhere. Your documents
are read, never modified, never moved, never uploaded.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "Cairn"


def data_dir() -> Path:
    """The per-user directory holding the index, notes and settings.

    Honours CAIRN_HOME so tests - and anyone who wants their index on a
    different disk - can redirect it without patching anything.
    """
    override = os.environ.get("CAIRN_HOME")
    if override:
        path = Path(override).expanduser()
    elif sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        path = Path(base) / APP_NAME
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
        path = Path(base) / "cairn"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "cairn.db"


def settings_path() -> Path:
    return data_dir() / "settings.json"


def default_watch_folders() -> list[str]:
    """A sensible first guess: the folders nearly everyone keeps work in.

    Only the ones that actually exist are offered, so a fresh Linux box does
    not get a list of Windows folder names.
    """
    home = Path.home()
    candidates = [
        home / "Documents",
        home / "Desktop",
        home / "Downloads",
        home / "Projects",
        home / "OneDrive" / "Documents",
    ]
    seen: list[str] = []
    for candidate in candidates:
        if candidate.is_dir() and str(candidate) not in seen:
            seen.append(str(candidate))
    return seen


@dataclass
class Settings:
    # Empty on purpose. Cairn reads whole documents, so which folders it may
    # read is the user's decision to make, not a default to inherit. The
    # suggestions above are offered in the interface and accepted with a
    # click - the difference between a tool that asks and one that helps
    # itself.
    folders: list[str] = field(default_factory=list)
    # Files above this are skipped: a 200MB video has no text worth the read.
    max_file_mb: int = 40
    # Extra folder names to skip, on top of the built-in noise list.
    exclude: list[str] = field(default_factory=list)
    # Cloud answering is off until the user turns it on AND has a key.
    ai_enabled: bool = False
    ai_provider: str = "auto"
    ai_model: str = ""
    # Commitment scanning over indexed documents, not just notes.
    scan_documents_for_commitments: bool = True
    theme: str = "system"

    @classmethod
    def load(cls) -> Settings:
        path = settings_path()
        if not path.exists():
            settings = cls()
            settings.save()
            return settings
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A corrupt settings file must not stop the app starting. Defaults
            # are always usable, and the user can set folders again in a click.
            return cls()
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self) -> None:
        settings_path().write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def folder_paths(self) -> list[Path]:
        return [Path(f).expanduser() for f in self.folders if Path(f).expanduser().is_dir()]
