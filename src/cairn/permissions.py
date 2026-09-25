"""What Cairn is allowed to do, decided by the person using it.

Most desktop tools treat permission as a setup step: a checkbox on first run,
never seen again, enforced nowhere. That is not consent, it is paperwork.

Three rules make this real rather than decorative.

1. **Nothing is granted by default.** Every capability starts at "never
   asked". A fresh install can read nothing, open nothing and send nothing.

2. **Enforcement happens where the thing is done**, not where it was
   configured. `require()` is called immediately before reading a folder,
   launching a file or making a network call. A permission revoked at 11:04
   stops the 11:05 action, even if the feature was switched on in January.

3. **Every use is written down.** The sensitive capabilities append to a
   plain-text log the user can read. A promise about what a program does is
   worth much less than a record of what it did.

The wording of each permission matters as much as the code. Each one says
what it allows AND what it does not, because "allow file access" tells
someone nothing about whether their tax returns are about to be uploaded.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from cairn.config import data_dir


class Permission(str, Enum):
    # On this machine
    READ_FOLDERS = "read_folders"
    OPEN_FILES = "open_files"
    WATCH_CHANGES = "watch_changes"
    SEND_TO_AI = "send_to_ai"

    # Connected services. Note there are THREE gmail permissions, not one.
    # Reading someone's mail, writing a draft they will review, and sending
    # something in their name under their signature are three different
    # decisions, and lumping them into one "access your Gmail" switch is how
    # every product in this category loses the cautious buyer.
    GMAIL_READ = "gmail_read"
    GMAIL_DRAFT = "gmail_draft"
    GMAIL_SEND = "gmail_send"
    CALENDAR_READ = "calendar_read"
    CALENDAR_WRITE = "calendar_write"
    DRIVE_READ = "drive_read"


class Tier(str, Enum):
    """How much damage a capability could do if it went wrong.

    The interface uses this to decide how hard to make the decision: READ is a
    switch, WRITE says what it will change, and ACT - anything that another
    human will receive - is confirmed separately and never pre-ticked.
    """

    LOCAL = "local"
    READ = "read"
    WRITE = "write"
    ACT = "act"


@dataclass(frozen=True)
class Capability:
    key: Permission
    title: str
    allows: str
    does_not: str
    # Leaves the machine? The one distinction most people actually care about.
    leaves_machine: bool = False
    tier: Tier = Tier.LOCAL
    # Which connector must be signed in before this can be granted.
    connector: str = ""


CAPABILITIES: dict[Permission, Capability] = {
    Permission.READ_FOLDERS: Capability(
        Permission.READ_FOLDERS,
        "Read the folders you choose",
        "Open and read the text of documents inside the folders you pick, so they "
        "can be searched.",
        "It never changes, moves, renames or deletes a file, never looks outside "
        "the folders you picked, and nothing read this way leaves your computer.",
    ),
    Permission.OPEN_FILES: Capability(
        Permission.OPEN_FILES,
        "Open a file when you click it",
        "Launch a document in whatever program normally opens it, or show it in "
        "your file manager.",
        "It can only open files already in the index, and only when you click. It "
        "cannot run programs, scripts or installers.",
    ),
    Permission.WATCH_CHANGES: Capability(
        Permission.WATCH_CHANGES,
        "Keep the index up to date on its own",
        "Re-read changed files in the background so search results are not stale.",
        "It does not run when Cairn is closed, and it reads nothing outside your "
        "chosen folders.",
    ),
    Permission.SEND_TO_AI: Capability(
        Permission.SEND_TO_AI,
        "Send passages to an AI service to answer questions",
        "When you press Ask, send your question and the handful of paragraphs it "
        "matched to the AI provider whose key you supplied.",
        "It never sends whole files, never sends anything you did not ask about, "
        "and sends nothing at all unless you press Ask.",
        leaves_machine=True,
    ),
    Permission.GMAIL_READ: Capability(
        Permission.GMAIL_READ,
        "Read my email",
        "Read your messages so they can be searched alongside your files, and so "
        "promises you made by email end up on your list.",
        "It cannot write, reply, send, delete, archive or label anything. Your mail "
        "is read into the index on this machine and is not uploaded anywhere.",
        tier=Tier.READ,
        connector="google",
    ),
    Permission.GMAIL_DRAFT: Capability(
        Permission.GMAIL_DRAFT,
        "Write drafts for me to review",
        "Put a draft reply in your Drafts folder, where you read it, change it and "
        "decide whether to send it.",
        "A draft is never sent. Nothing reaches the other person unless you press "
        "send yourself, in Gmail.",
        tier=Tier.WRITE,
        connector="google",
    ),
    Permission.GMAIL_SEND: Capability(
        Permission.GMAIL_SEND,
        "Send email as me",
        "Send a message from your address without you opening Gmail.",
        "This is the one capability where a mistake reaches another human being "
        "and cannot be taken back. It is off, no setup preset asks for it, and "
        "Cairn works completely without it. Leave it off unless you have a "
        "specific reason.",
        leaves_machine=True,
        tier=Tier.ACT,
        connector="google",
    ),
    Permission.CALENDAR_READ: Capability(
        Permission.CALENDAR_READ,
        "Read my calendar",
        "See what is in your diary, so the brief knows what your day looks like "
        "and meeting notes can be matched to meetings.",
        "It cannot create, move, cancel or accept anything.",
        tier=Tier.READ,
        connector="google",
    ),
    Permission.CALENDAR_WRITE: Capability(
        Permission.CALENDAR_WRITE,
        "Put things in my calendar",
        "Create or update events - for example blocking time for something you "
        "promised to do.",
        "It never invites anyone else, and never cancels or declines on your behalf.",
        tier=Tier.WRITE,
        connector="google",
    ),
    Permission.DRIVE_READ: Capability(
        Permission.DRIVE_READ,
        "Read my Drive files",
        "Index documents kept in Google Drive so they are searchable with the rest.",
        "Read only. It cannot edit, move, share or delete anything in your Drive.",
        tier=Tier.READ,
        connector="google",
    ),
}

# Permissions no preset may pre-tick, whatever the user picked. Anything here
# reaches another person and cannot be undone, so it is always a separate,
# deliberate decision.
NEVER_PRESELECTED = frozenset({Permission.GMAIL_SEND})


class Denied(Exception):
    """Raised where the action would happen, not where it was configured."""

    def __init__(self, permission: Permission):
        self.permission = permission
        capability = CAPABILITIES[permission]
        super().__init__(
            f"Cairn has not been allowed to {capability.title.lower()}. "
            f"Turn it on under Permissions if you want this."
        )


@dataclass
class Grant:
    granted: bool | None = None  # None means never asked
    decided_at: float = 0.0

    @property
    def state(self) -> str:
        if self.granted is None:
            return "not asked"
        return "allowed" if self.granted else "refused"


@dataclass
class Permissions:
    grants: dict[str, Grant] = field(default_factory=dict)

    # ------------------------------------------------------------- storage

    @staticmethod
    def _path() -> Path:
        return data_dir() / "permissions.json"

    @classmethod
    def load(cls) -> Permissions:
        path = cls._path()
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A damaged permissions file must fail CLOSED. Defaulting to
            # "allowed" after a bad read would be the worst possible bug in
            # this file.
            return cls()
        grants = {
            key: Grant(value.get("granted"), float(value.get("decided_at", 0)))
            for key, value in raw.get("grants", {}).items()
            if key in {p.value for p in Permission}
        }
        return cls(grants=grants)

    def save(self) -> None:
        payload = {
            "grants": {
                key: {"granted": grant.granted, "decided_at": grant.decided_at}
                for key, grant in self.grants.items()
            }
        }
        self._path().write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # -------------------------------------------------------------- asking

    def get(self, permission: Permission) -> Grant:
        return self.grants.get(permission.value, Grant())

    def allowed(self, permission: Permission) -> bool:
        return self.get(permission).granted is True

    def decide(self, permission: Permission, granted: bool) -> None:
        previous = self.get(permission).granted
        self.grants[permission.value] = Grant(granted, time.time())
        self.save()
        if previous != granted:
            action = "granted" if granted else ("revoked" if previous else "refused")
            record(permission, action)

    def require(self, permission: Permission) -> None:
        if not self.allowed(permission):
            raise Denied(permission)

    def as_list(self) -> list[dict]:
        out = []
        for key, capability in CAPABILITIES.items():
            grant = self.get(key)
            out.append(
                {
                    "key": key.value,
                    "title": capability.title,
                    "allows": capability.allows,
                    "does_not": capability.does_not,
                    "leaves_machine": capability.leaves_machine,
                    "tier": capability.tier.value,
                    "connector": capability.connector,
                    "granted": grant.granted,
                    "state": grant.state,
                    "decided_at": grant.decided_at,
                }
            )
        return out


# ------------------------------------------------------------------- the log


def log_path() -> Path:
    return data_dir() / "activity.log"


def record(permission: Permission | str, action: str, detail: str = "") -> None:
    """Append one line to the activity log.

    Plain text, one line per event, readable in Notepad. A log the user needs
    a tool to read is a log the user will never read.
    """
    key = permission.value if isinstance(permission, Permission) else str(permission)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{key}\t{action}\t{detail}\n"
    try:
        with log_path().open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        # Failing to log must never fail the action the user asked for.
        pass


def recent_activity(limit: int = 200) -> list[dict]:
    path = log_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    events = []
    for line in lines[-limit:][::-1]:
        parts = line.split("\t")
        if len(parts) >= 3:
            events.append(
                {
                    "when": parts[0],
                    "permission": parts[1],
                    "action": parts[2],
                    "detail": parts[3] if len(parts) > 3 else "",
                }
            )
    return events
