"""Starting over.

This module exists because of a real wall: leftover state from testing left a
freshly downloaded copy skipping its welcome screen, and diagnosing that took
a terminal and a JSON file. Anyone without a terminal would simply have
concluded the program was broken.

The rule these tests defend is that a reset never destroys anything without
first making a copy you can get back.
"""

import pytest

from cairn import notes
from cairn.config import Settings
from cairn.permissions import Permission, Permissions, recent_activity
from cairn.reset import list_backups, start_over


@pytest.fixture
def lived_in(conn, granted):
    """An installation with some history in it."""
    settings = Settings(folders=["/somewhere"], features=["search", "notes"])
    settings.setup_complete = True
    settings.save()
    notes.add(conn, "Spoke to the bank. I'll send the mandate form on Tuesday.")
    notes.add(conn, "Second note, with nothing to promise in it at all.")
    return conn


def test_running_setup_again_keeps_everything(lived_in):
    result = start_over(lived_in, erase_everything=False)

    assert result["scope"] == "setup"
    assert Settings.load().setup_complete is False
    assert len(notes.recent(lived_in)) == 2, "notes must survive"
    assert lived_in.execute(
        "SELECT COUNT(*) AS n FROM commitments"
    ).fetchone()["n"] == 1
    assert Permissions.load().allowed(Permission.READ_FOLDERS), "permissions kept"


def test_erasing_everything_removes_everything(lived_in):
    result = start_over(lived_in, erase_everything=True)

    assert result["scope"] == "all"
    assert notes.recent(lived_in) == []
    for table in ("chunks", "files", "notes", "commitments"):
        assert lived_in.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"] == 0
    assert not any(Permissions.load().allowed(p) for p in Permission)
    assert Settings.load().setup_complete is False
    assert Settings.load().folders == []


def test_nothing_is_destroyed_without_a_copy(lived_in):
    """The one rule. A reset with no backup is data loss with extra steps."""
    result = start_over(lived_in, erase_everything=True)

    from pathlib import Path

    saved = Path(result["backup"])
    assert saved.is_dir()
    assert (saved / "cairn.db").exists()
    assert (saved / "settings.json").exists()


def test_the_backup_actually_contains_the_data(lived_in):
    """A backup that restores nothing is worse than none - it is false comfort."""
    import sqlite3
    from pathlib import Path

    result = start_over(lived_in, erase_everything=True)
    restored = sqlite3.connect(str(Path(result["backup"]) / "cairn.db"))
    restored.row_factory = sqlite3.Row
    try:
        bodies = [r["body"] for r in restored.execute("SELECT body FROM notes")]
        assert len(bodies) == 2
        assert any("mandate form" in b for b in bodies)
        assert restored.execute(
            "SELECT COUNT(*) AS n FROM commitments"
        ).fetchone()["n"] == 1
    finally:
        restored.close()


def test_the_backup_is_made_before_anything_is_removed(lived_in):
    """Order matters: a crash midway must not land between the two."""
    result = start_over(lived_in, erase_everything=True)
    assert result["removed"]["notes"] == 2, "it counted what was there, not what is left"


def test_a_reset_is_written_down(lived_in):
    start_over(lived_in, erase_everything=True)
    entries = [e for e in recent_activity() if e["permission"] == "reset"]
    assert entries and entries[0]["action"] == "ERASED"
    assert "note(s)" in entries[0]["detail"]


def test_backups_are_listed_so_the_reset_is_visibly_undoable(lived_in):
    assert list_backups() == []
    start_over(lived_in, erase_everything=False)
    found = list_backups()
    assert len(found) == 1 and found[0]["size_mb"] >= 0


# ------------------------------------------------------------- over the wire


def test_erasing_over_http_needs_the_word_typed(api_client):
    api_client.post("/api/notes", json={"body": "Something worth keeping here."})

    refused = api_client.post("/api/reset", json={"erase_everything": True})
    assert refused.status_code == 400
    assert len(api_client.get("/api/notes").json()["items"]) == 1, "nothing was removed"

    done = api_client.post(
        "/api/reset", json={"erase_everything": True, "confirm": "erase"}
    )
    assert done.status_code == 200
    assert api_client.get("/api/notes").json()["items"] == []


def test_resetting_needs_the_token(api_client):
    response = api_client.post("/api/reset", json={}, headers={"X-Cairn-Token": ""})
    assert response.status_code == 403


def test_running_setup_again_over_http_brings_the_welcome_screen_back(api_client):
    assert api_client.get("/api/state").json()["setup_complete"] is True
    api_client.post("/api/reset", json={})
    assert api_client.get("/api/state").json()["setup_complete"] is False
