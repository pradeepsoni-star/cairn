"""Gmail, Calendar and Drive, behind one sign-in and six separate permissions.

The important thing in this file is `scopes_for()`. The OAuth scopes Cairn
requests are computed from the permissions the user ticked, so:

  * grant nothing, and no sign-in is possible at all;
  * grant only "read my email", and the token Google issues is read-only -
    the send capability does not exist in it, whatever the code does later;
  * grant "send email" later, and the sign-in has to be repeated, because the
    old token genuinely cannot do it.

That last point is a feature. Escalating what the software may do should cost
the user a deliberate click, not happen quietly because a scope was requested
months ago against a future need.

Sending is additionally refused unless the caller passes `confirmed=True`,
which the interface only sets after showing the user the actual message. Two
independent gates, because this is the one action that cannot be undone.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

from cairn.config import data_dir
from cairn.connectors.base import Connector, NotConnected
from cairn.permissions import Permission, Permissions, record

CONNECTOR = Connector(
    key="google",
    title="Google (Gmail, Calendar, Drive)",
    blurb=(
        "Search your mail alongside your files, catch the promises you made by "
        "email, and see your day. Each part is a separate permission - reading "
        "your mail never implies writing or sending anything."
    ),
    permissions=(
        Permission.GMAIL_READ,
        Permission.GMAIL_DRAFT,
        Permission.GMAIL_SEND,
        Permission.CALENDAR_READ,
        Permission.CALENDAR_WRITE,
        Permission.DRIVE_READ,
    ),
    setup_note=(
        "Needs a free Google Cloud OAuth client, created once. Cairn cannot ship "
        "one, because a shared client would put every user's mail behind the same "
        "credential. The setup screen walks you through it - about five minutes."
    ),
)

# One permission, one scope. Nothing here grants more than its own line.
SCOPES = {
    Permission.GMAIL_READ: "https://www.googleapis.com/auth/gmail.readonly",
    Permission.GMAIL_DRAFT: "https://www.googleapis.com/auth/gmail.compose",
    Permission.GMAIL_SEND: "https://www.googleapis.com/auth/gmail.send",
    Permission.CALENDAR_READ: "https://www.googleapis.com/auth/calendar.readonly",
    Permission.CALENDAR_WRITE: "https://www.googleapis.com/auth/calendar.events",
    Permission.DRIVE_READ: "https://www.googleapis.com/auth/drive.readonly",
}


def client_secret_path() -> Path:
    return data_dir() / "google_client_secret.json"


def token_path() -> Path:
    return data_dir() / "google_token.json"


def scopes_for(permissions: Permissions | None = None) -> list[str]:
    """The OAuth scopes to request: exactly the granted permissions, no more."""
    permissions = permissions or Permissions.load()
    return sorted(
        scope for key, scope in SCOPES.items() if permissions.allowed(key)
    )


def _saved_scopes() -> list[str]:
    try:
        return sorted(json.loads(token_path().read_text(encoding="utf-8")).get("scopes", []))
    except (OSError, json.JSONDecodeError):
        return []


def needs_reconsent(permissions: Permissions | None = None) -> bool:
    """True when the user has granted something the stored token cannot do.

    Only widening matters. Revoking a permission in Cairn stops the action
    here immediately; the stale scope in the token is dealt with by signing
    in again or revoking at Google, and the interface says so.
    """
    wanted = set(scopes_for(permissions))
    return bool(wanted - set(_saved_scopes()))


def status() -> dict:
    permissions = Permissions.load()
    wanted = scopes_for(permissions)
    linked = token_path().exists()
    account = ""
    expires = ""
    if linked:
        try:
            stored = json.loads(token_path().read_text(encoding="utf-8"))
            account = stored.get("account", "")
            expires = stored.get("expiry", "")
        except (OSError, json.JSONDecodeError):
            linked = False
    return {
        "connected": linked,
        "account": account,
        "expires": expires,
        "has_client_secret": client_secret_path().exists(),
        "client_secret_path": str(client_secret_path()),
        "requested_scopes": wanted,
        "token_scopes": _saved_scopes(),
        "needs_reconsent": linked and needs_reconsent(permissions),
        "can_connect": bool(wanted) and client_secret_path().exists(),
    }


def disconnect() -> None:
    """Forget the account. Leaves indexed mail alone - see the note below."""
    with contextlib.suppress(OSError):
        token_path().unlink()
    record("google", "disconnected", "token deleted from this machine")


def forget_indexed_mail(conn) -> int:
    """Remove everything read from Gmail out of the index.

    Separate from `disconnect` on purpose. Unlinking an account and erasing
    what was already read are different intentions, and a product that
    silently does the second when you ask for the first has destroyed data
    you did not ask it to destroy.
    """
    removed = conn.execute("DELETE FROM files WHERE path LIKE 'gmail:%'").rowcount
    conn.execute("DELETE FROM chunks WHERE path LIKE 'gmail:%'")
    conn.commit()
    record(Permission.GMAIL_READ, "index cleared", f"{removed} message(s) removed")
    return removed


# ------------------------------------------------------------------ the API


def _service(api: str, version: str):
    """An authorised Google API client, or a clear explanation of why not."""
    if not token_path().exists():
        raise NotConnected("No Google account is linked. Connect one under Connections.")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise NotConnected(
            "Google support needs extra packages: pip install 'cairn-desk[google]'"
        ) from exc

    credentials = Credentials.from_authorized_user_file(str(token_path()))
    if not credentials.valid and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        _store_credentials(credentials)
    return build(api, version, credentials=credentials, cache_discovery=False)


def _store_credentials(credentials, account: str = "") -> None:
    payload = json.loads(credentials.to_json())
    payload["scopes"] = list(credentials.scopes or [])
    if account:
        payload["account"] = account
    elif token_path().exists():
        with contextlib.suppress(OSError, json.JSONDecodeError):
            payload["account"] = json.loads(token_path().read_text(encoding="utf-8")).get(
                "account", ""
            )
    token_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")


def connect() -> dict:
    """Run the Google sign-in, requesting only the granted scopes."""
    permissions = Permissions.load()
    wanted = scopes_for(permissions)
    if not wanted:
        raise NotConnected(
            "Nothing to connect for: grant at least one Google permission first. "
            "Cairn will then ask Google only for what you granted."
        )
    if not client_secret_path().exists():
        raise NotConnected(
            f"Put your Google OAuth client file at {client_secret_path()} first."
        )
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise NotConnected(
            "Google sign-in needs extra packages: pip install 'cairn-desk[google]'"
        ) from exc

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path()), wanted)
    credentials = flow.run_local_server(port=0, prompt="consent")

    account = ""
    try:
        from googleapiclient.discovery import build

        if Permission.GMAIL_READ in [p for p in SCOPES if permissions.allowed(p)]:
            profile = (
                build("gmail", "v1", credentials=credentials, cache_discovery=False)
                .users()
                .getProfile(userId="me")
                .execute()
            )
            account = profile.get("emailAddress", "")
    except Exception:
        # Knowing the address is a nicety. Failing to fetch it must not undo a
        # sign-in the user just completed.
        pass

    _store_credentials(credentials, account)
    record("google", "connected", f"{account or 'account linked'}: {', '.join(wanted)}")
    return status()


# -------------------------------------------------------------------- gmail


def recent_messages(limit: int = 100, query: str = "newer_than:90d") -> list[dict]:
    """Messages as plain records. Requires GMAIL_READ, checked here."""
    Permissions.load().require(Permission.GMAIL_READ)
    service = _service("gmail", "v1")

    listed = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=min(limit, 500))
        .execute()
    )
    out: list[dict] = []
    for stub in listed.get("messages", [])[:limit]:
        try:
            full = (
                service.users()
                .messages()
                .get(userId="me", id=stub["id"], format="full")
                .execute()
            )
        except Exception:
            continue
        out.append(_flatten(full))
    record(Permission.GMAIL_READ, "read", f"{len(out)} message(s), query: {query}")
    return out


def _header(payload: dict, name: str) -> str:
    for header in payload.get("headers", []):
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _body_text(payload: dict) -> str:
    """Plain text out of a MIME tree, preferring text/plain over HTML."""
    import base64

    from cairn.extract import _strip_markup

    def decode(data: str) -> str:
        return base64.urlsafe_b64decode(data.encode("ascii")).decode("utf-8", "replace")

    plain, html = "", ""
    stack = [payload]
    while stack:
        part = stack.pop()
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data:
            if mime == "text/plain" and not plain:
                plain = decode(data)
            elif mime == "text/html" and not html:
                html = decode(data)
        stack.extend(part.get("parts", []))
    return plain or _strip_markup(html)


def _flatten(message: dict) -> dict:
    payload = message.get("payload", {})
    return {
        "id": message.get("id", ""),
        "thread_id": message.get("threadId", ""),
        "subject": _header(payload, "Subject"),
        "sender": _header(payload, "From"),
        "to": _header(payload, "To"),
        "date": _header(payload, "Date"),
        "snippet": message.get("snippet", ""),
        "body": _body_text(payload),
        "labels": message.get("labelIds", []),
    }


def draft_reply(thread_id: str, to: str, subject: str, body: str) -> dict:
    """Put a draft in Drafts. It is never sent by this function."""
    Permissions.load().require(Permission.GMAIL_DRAFT)
    service = _service("gmail", "v1")
    raw = _encode(to, subject, body)
    draft = (
        service.users()
        .drafts()
        .create(userId="me", body={"message": {"raw": raw, "threadId": thread_id}})
        .execute()
    )
    record(Permission.GMAIL_DRAFT, "drafted", f"to {to}: {subject}")
    return {"draft_id": draft.get("id", ""), "sent": False}


def send(to: str, subject: str, body: str, confirmed: bool = False) -> dict:
    """Send a message. Two gates, deliberately.

    The permission is the standing decision; `confirmed` is this particular
    message. The interface sets it only after showing the user the exact text
    that is about to go out. An automation that skips the second gate is
    indistinguishable, from the recipient's side, from the software mailing
    people by itself.
    """
    Permissions.load().require(Permission.GMAIL_SEND)
    if not confirmed:
        raise PermissionError(
            "Sending needs this specific message to be confirmed, not just the "
            "permission. Cairn will not send anything you have not read."
        )
    service = _service("gmail", "v1")
    result = (
        service.users()
        .messages()
        .send(userId="me", body={"raw": _encode(to, subject, body)})
        .execute()
    )
    record(Permission.GMAIL_SEND, "SENT", f"to {to}: {subject}")
    return {"message_id": result.get("id", ""), "sent": True}


def _encode(to: str, subject: str, body: str) -> str:
    import base64
    from email.message import EmailMessage

    message = EmailMessage()
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


# ----------------------------------------------------------------- calendar


def upcoming_events(days: int = 7, limit: int = 50) -> list[dict]:
    Permissions.load().require(Permission.CALENDAR_READ)
    from datetime import datetime, timedelta, timezone

    service = _service("calendar", "v3")
    now = datetime.now(timezone.utc)
    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=(now + timedelta(days=days)).isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=limit,
        )
        .execute()
    )
    events = [
        {
            "id": item.get("id", ""),
            "title": item.get("summary", "(no title)"),
            "start": item.get("start", {}).get("dateTime") or item.get("start", {}).get("date", ""),
            "end": item.get("end", {}).get("dateTime") or item.get("end", {}).get("date", ""),
            "attendees": [a.get("email", "") for a in item.get("attendees", [])],
            "location": item.get("location", ""),
        }
        for item in result.get("items", [])
    ]
    record(Permission.CALENDAR_READ, "read", f"{len(events)} event(s) over {days} days")
    return events
