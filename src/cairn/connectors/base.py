"""Connected services, and the rule that governs all of them.

A connector is a source Cairn can read (and sometimes write) that is not the
local disk: mail, calendar, cloud storage. Adding one must not add a new way
of asking for consent, so every connector goes through the same permission
layer as everything else, and every action it takes lands in the same
activity log.

The rule, which is the whole reason this is a framework and not a Gmail
integration:

    **What Cairn asks the service for is decided by what the user granted
    in Cairn, not the other way round.**

Most products request the widest scope at sign-in and then narrow behaviour
in software. That means the access token on your machine can do far more
than the product admits, and you have to trust the software to hold back.
Cairn builds the OAuth scope list FROM the permissions you ticked. If you
never granted "send email", no send scope is ever requested, so the token
physically cannot send - and you can verify that on Google's own permissions
page rather than taking a README's word for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from cairn.permissions import Permission, Permissions


@dataclass(frozen=True)
class Connector:
    key: str
    title: str
    blurb: str
    # Everything this connector could ever do, in the order it should be shown.
    permissions: tuple[Permission, ...]
    # What the user has to do once, outside Cairn, before it can work.
    setup_note: str = ""


class Backend(Protocol):
    """What a connector module must provide."""

    def status(self) -> dict: ...
    def disconnect(self) -> None: ...


class NotConnected(Exception):
    """Permission was granted but the account was never linked, or has expired."""


def granted_permissions(connector: Connector, permissions: Permissions | None = None):
    """Only the capabilities of this connector the user actually allowed."""
    permissions = permissions or Permissions.load()
    return tuple(p for p in connector.permissions if permissions.allowed(p))


def registry() -> dict[str, Connector]:
    from cairn.connectors import google

    return {google.CONNECTOR.key: google.CONNECTOR}


def describe() -> list[dict]:
    """Every connector, what it can do, and whether it is linked."""
    from cairn.connectors import google

    backends = {"google": google}
    permissions = Permissions.load()
    out = []
    for key, connector in registry().items():
        backend = backends[key]
        allowed = granted_permissions(connector, permissions)
        out.append(
            {
                "key": key,
                "title": connector.title,
                "blurb": connector.blurb,
                "setup_note": connector.setup_note,
                "permissions": [p.value for p in connector.permissions],
                "granted": [p.value for p in allowed],
                "status": backend.status(),
            }
        )
    return out
