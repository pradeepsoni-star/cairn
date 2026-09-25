"""Connected services.

The claim this file has to make good on is the one in `connectors/base.py`:
what Cairn asks Google for is decided by what the user granted in Cairn. If
that is true, someone who never granted "send" holds a token that physically
cannot send, and does not have to trust the software to hold back.

Everything here runs against a fake Google API. Nothing touches a real
account - a test suite that needed live credentials would be a test suite
nobody runs.
"""

import pytest

from cairn.connectors import google
from cairn.permissions import NEVER_PRESELECTED, Permission, Permissions, recent_activity

# --------------------------------------------------- scopes follow the grants


def test_granting_nothing_means_no_sign_in_is_even_possible():
    assert google.scopes_for() == []
    assert google.status()["can_connect"] is False


def test_reading_mail_requests_only_the_read_only_scope():
    """The token issued cannot send, whatever the code later does."""
    Permissions.load().decide(Permission.GMAIL_READ, True)
    scopes = google.scopes_for()
    assert scopes == ["https://www.googleapis.com/auth/gmail.readonly"]
    assert not any("gmail.send" in s or "gmail.compose" in s for s in scopes)


def test_each_permission_adds_exactly_its_own_scope():
    permissions = Permissions.load()
    permissions.decide(Permission.GMAIL_READ, True)
    permissions.decide(Permission.CALENDAR_READ, True)
    scopes = google.scopes_for()
    assert len(scopes) == 2
    assert any("gmail.readonly" in s for s in scopes)
    assert any("calendar.readonly" in s for s in scopes)


def test_revoking_a_permission_removes_its_scope_from_the_next_sign_in():
    permissions = Permissions.load()
    permissions.decide(Permission.GMAIL_READ, True)
    permissions.decide(Permission.GMAIL_DRAFT, True)
    assert len(google.scopes_for()) == 2
    permissions.decide(Permission.GMAIL_DRAFT, False)
    assert google.scopes_for() == ["https://www.googleapis.com/auth/gmail.readonly"]


def test_widening_later_forces_a_fresh_sign_in(tmp_path):
    """Escalation should cost a deliberate click, not happen quietly."""
    import json

    Permissions.load().decide(Permission.GMAIL_READ, True)
    google.token_path().write_text(
        json.dumps({"scopes": ["https://www.googleapis.com/auth/gmail.readonly"]}),
        encoding="utf-8",
    )
    assert google.needs_reconsent() is False

    Permissions.load().decide(Permission.GMAIL_SEND, True)
    assert google.needs_reconsent() is True
    assert google.status()["needs_reconsent"] is True


def test_every_permission_maps_to_one_scope_and_no_scope_is_shared():
    """A shared scope would mean granting one thing silently granted another."""
    scopes = list(google.SCOPES.values())
    assert len(scopes) == len(set(scopes))
    for permission in google.CONNECTOR.permissions:
        assert permission in google.SCOPES, f"{permission} has no scope"


# ------------------------------------------------------------- sending is hard


def test_sending_without_the_permission_is_refused():
    from cairn.permissions import Denied

    with pytest.raises(Denied):
        google.send("someone@example.com", "hello", "body", confirmed=True)


def test_sending_with_the_permission_but_no_confirmation_is_still_refused():
    """Two gates: the standing decision, and this particular message.

    Without the second, an automation could mail people in the user's name
    and the recipient could not tell the difference.
    """
    Permissions.load().decide(Permission.GMAIL_SEND, True)
    with pytest.raises(PermissionError, match="confirmed"):
        google.send("someone@example.com", "hello", "body")


def test_no_preset_ever_proposes_sending_mail():
    from cairn.features import PRESETS

    for preset in PRESETS:
        assert not (set(preset.proposes) & NEVER_PRESELECTED), preset.key


def test_drafting_is_not_sending():
    """A draft sits in Drafts. The user sends it, in Gmail, or nobody does."""
    Permissions.load().decide(Permission.GMAIL_DRAFT, True)
    result = _with_fake_gmail(
        lambda: google.draft_reply("t1", "buyer@example.com", "Re: quote", "Here it is.")
    )
    assert result["sent"] is False
    assert result["draft_id"]


# ------------------------------------------------------------------ reading


class _FakeGmail:
    """Enough of the Gmail client to exercise our own code, and no more."""

    def __init__(self, messages):
        self._messages = messages
        self.sent = []
        self.created_drafts = []

    def users(self):
        return self

    def messages(self):
        return self

    def drafts(self):
        return self

    def list(self, **kwargs):
        self._last = {"messages": [{"id": m["id"]} for m in self._messages]}
        return self

    def get(self, userId=None, id=None, format=None):
        self._last = next(m for m in self._messages if m["id"] == id)
        return self

    def create(self, userId=None, body=None):
        self.created_drafts.append(body)
        self._last = {"id": f"draft-{len(self.created_drafts)}"}
        return self

    def send(self, userId=None, body=None):
        self.sent.append(body)
        self._last = {"id": "sent-1"}
        return self

    def execute(self):
        return self._last


def _message(identifier, subject, sender, body):
    import base64

    return {
        "id": identifier,
        "threadId": f"thread-{identifier}",
        "snippet": body[:40],
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
                {"name": "To", "value": "me@example.com"},
                {"name": "Date", "value": "Wed, 4 Mar 2026 09:00:00 +0000"},
            ],
            "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()},
        },
    }


_FAKE = _FakeGmail(
    [
        _message(
            "m1",
            "Container booking",
            "anita@example.com",
            "Thanks for the call. I'll send the revised figures on Thursday.",
        ),
        _message(
            "m2",
            "Packing list",
            "buyer@example.com",
            "Can you send over the packing list when you get a moment.",
        ),
    ]
)


def _with_fake_gmail(action):
    import cairn.connectors.google as module

    original = module._service
    module._service = lambda *a, **k: _FAKE
    try:
        return action()
    finally:
        module._service = original


def test_reading_mail_requires_the_permission():
    from cairn.permissions import Denied

    with pytest.raises(Denied):
        _with_fake_gmail(lambda: google.recent_messages())


def test_messages_come_back_as_plain_records():
    Permissions.load().decide(Permission.GMAIL_READ, True)
    messages = _with_fake_gmail(google.recent_messages)
    assert [m["subject"] for m in messages] == ["Container booking", "Packing list"]
    assert "revised figures" in messages[0]["body"]


def test_reading_mail_is_written_down():
    Permissions.load().decide(Permission.GMAIL_READ, True)
    _with_fake_gmail(google.recent_messages)
    reads = [e for e in recent_activity() if e["permission"] == "gmail_read"]
    assert reads and "message(s)" in reads[0]["detail"]


# ------------------------------------------------- mail joins the same index


def test_mail_is_searchable_beside_files(conn):
    from cairn.connectors.mail_index import sync
    from cairn.search import search

    Permissions.load().decide(Permission.GMAIL_READ, True)
    result = _with_fake_gmail(lambda: sync(conn))
    assert result["messages"] == 2

    hits = search(conn, "container booking")
    assert hits and hits[0].kind == "email"


def test_promises_made_by_email_reach_the_same_list(conn):
    from cairn.connectors.mail_index import sync

    Permissions.load().decide(Permission.GMAIL_READ, True)
    _with_fake_gmail(lambda: sync(conn))
    texts = [row["text"] for row in conn.execute("SELECT text FROM commitments")]
    assert any("revised figures" in t for t in texts)


def test_syncing_twice_does_not_duplicate_a_message(conn):
    from cairn.connectors.mail_index import sync

    Permissions.load().decide(Permission.GMAIL_READ, True)
    _with_fake_gmail(lambda: sync(conn))
    _with_fake_gmail(lambda: sync(conn))
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM files WHERE path LIKE 'gmail:%'"
    ).fetchone()["n"]
    assert count == 2


def test_unlinking_the_account_does_not_silently_erase_what_was_read(conn):
    """Two different intentions. Doing the second when asked for the first
    would destroy data the user never asked to lose."""
    import json

    from cairn.connectors.mail_index import sync

    Permissions.load().decide(Permission.GMAIL_READ, True)
    _with_fake_gmail(lambda: sync(conn))
    google.token_path().write_text(json.dumps({"scopes": []}), encoding="utf-8")

    google.disconnect()
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM files WHERE path LIKE 'gmail:%'"
    ).fetchone()["n"] == 2

    assert google.forget_indexed_mail(conn) == 2
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM files WHERE path LIKE 'gmail:%'"
    ).fetchone()["n"] == 0


# ------------------------------------------------------------- over the wire


def test_the_connector_list_is_readable_on_a_fresh_install(bare_client):
    body = bare_client.get("/api/connectors").json()
    google_row = next(c for c in body["connectors"] if c["key"] == "google")
    assert google_row["granted"] == []
    assert google_row["status"]["connected"] is False


def test_syncing_mail_is_refused_without_the_permission(bare_client):
    bare_client.post("/api/features", json={"features": ["email"], "complete": True})
    assert bare_client.post("/api/connectors/google/sync").status_code == 403


def test_connecting_without_granting_anything_explains_itself(bare_client):
    response = bare_client.post("/api/connectors/google/connect")
    assert response.status_code == 400
    assert "grant at least one" in response.json()["detail"].lower()
