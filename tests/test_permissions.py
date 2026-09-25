"""Consent.

This is the file that decides whether Cairn is trustworthy, so it is written
from the position of someone who does not believe the README. Every test here
starts from a fresh install and asks: can this thing read my disk, open my
files, or send anything anywhere, without me having said yes?

The scenario these are really written for is the freelance accountant with
her clients' financial records on the same machine. For her, "the AI feature
is off by default" is not good enough - she needs it to be unreachable, and
she needs to be able to check afterwards what happened.
"""

import pytest

from cairn.config import Settings
from cairn.features import BY_KEY, BY_PRESET, default_enabled, describe
from cairn.permissions import Denied, Permission, Permissions, recent_activity

# ---------------------------------------------------- a fresh install is shut


def test_a_fresh_install_has_been_granted_nothing():
    permissions = Permissions.load()
    for permission in Permission:
        assert permissions.allowed(permission) is False
        assert permissions.get(permission).state == "not asked"


def test_never_asked_is_not_the_same_as_refused():
    """The interface needs to tell them apart: one warrants a prompt, the
    other must not nag someone who already said no."""
    permissions = Permissions.load()
    assert permissions.get(Permission.SEND_TO_AI).granted is None
    permissions.decide(Permission.SEND_TO_AI, False)
    assert Permissions.load().get(Permission.SEND_TO_AI).granted is False


def test_require_raises_until_granted():
    permissions = Permissions.load()
    with pytest.raises(Denied):
        permissions.require(Permission.READ_FOLDERS)
    permissions.decide(Permission.READ_FOLDERS, True)
    permissions.require(Permission.READ_FOLDERS)


def test_the_refusal_says_what_to_do_about_it():
    """"Permission denied" helps nobody."""
    try:
        Permissions.load().require(Permission.OPEN_FILES)
    except Denied as denied:
        assert "Permissions" in str(denied)
        assert "open a file" in str(denied).lower()


def test_a_damaged_permissions_file_fails_closed():
    """The worst possible bug in this module would be defaulting to allowed."""
    Permissions._path().write_text("{not json at all", encoding="utf-8")
    permissions = Permissions.load()
    assert not any(permissions.allowed(p) for p in Permission)


def test_revoking_takes_effect_at_once():
    permissions = Permissions.load()
    permissions.decide(Permission.READ_FOLDERS, True)
    permissions.decide(Permission.READ_FOLDERS, False)
    assert Permissions.load().allowed(Permission.READ_FOLDERS) is False


# --------------------------------------------------------- enforcement sites


def test_indexing_refuses_before_reading_a_single_file(conn, docs):
    """Enforced where files are opened, not where indexing was configured."""
    from cairn import indexer

    settings = Settings(folders=[str(docs)])
    result = indexer.reindex(conn, settings)
    assert result.finished
    assert "not been allowed" in result.error
    assert result.scanned == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"] == 0


def test_revoking_mid_life_stops_the_next_scan(conn, docs):
    from cairn import indexer

    permissions = Permissions.load()
    permissions.decide(Permission.READ_FOLDERS, True)
    settings = Settings(folders=[str(docs)])
    assert indexer.reindex(conn, settings).scanned > 0

    permissions.decide(Permission.READ_FOLDERS, False)
    assert indexer.reindex(conn, settings).scanned == 0


def test_asking_refuses_before_it_even_retrieves_a_passage(conn):
    """A refusal must not leak which of your files matched the question."""
    from cairn import ai

    with pytest.raises(Denied):
        ai.ask(conn, "what are the delivery terms")


# ------------------------------------------------------------- over the wire


def test_a_fresh_install_cannot_be_made_to_index(bare_client):
    response = bare_client.post("/api/index/start", json={})
    assert response.status_code == 403
    assert "Permissions" in response.json()["detail"]


def test_a_fresh_install_cannot_be_made_to_open_a_file(bare_client):
    assert bare_client.post("/api/open", json={"path": "C:/anything"}).status_code == 403


def test_the_ai_endpoint_does_not_exist_until_the_feature_is_chosen(bare_client):
    """For the accountant, off is not enough. It has to be absent."""
    response = bare_client.post("/api/ask", json={"question": "anything"})
    assert response.status_code == 404
    assert "switched off" in response.json()["detail"]


def test_switching_the_feature_on_still_leaves_the_permission_to_grant(bare_client):
    bare_client.post("/api/features", json={"features": ["ask"], "complete": True})
    response = bare_client.post("/api/ask", json={"question": "anything"})
    assert response.status_code == 403, "the feature is on, the permission is not"


def test_granting_then_asking_gets_past_both_gates(bare_client, monkeypatch):
    for variable in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
                     "GOOGLE_API_KEY", "OLLAMA_HOST", "CAIRN_OLLAMA"):
        monkeypatch.delenv(variable, raising=False)
    bare_client.post("/api/features", json={"features": ["ask", "notes"], "complete": True})
    bare_client.post("/api/permissions", json={"key": "send_to_ai", "granted": True})
    bare_client.post("/api/notes", json={"body": "Delivery terms are DAP Rotterdam."})
    response = bare_client.post("/api/ask", json={"question": "delivery terms"})
    # Past the gates; it now fails for the honest reason - no model configured.
    assert response.status_code == 200
    assert "key" in response.json()["error"].lower()


def test_a_switched_off_feature_has_no_endpoint(bare_client):
    bare_client.post("/api/features", json={"features": ["search"], "complete": True})
    assert bare_client.get("/api/notes").status_code == 404
    assert bare_client.get("/api/commitments").status_code == 404


# ------------------------------------------------------------------ the log


def test_what_was_sent_is_written_down(conn, monkeypatch):
    """The claim "only the matched paragraphs are sent" is worth nothing
    unless the user can check it afterwards."""
    from cairn import ai, notes

    Permissions.load().decide(Permission.SEND_TO_AI, True)
    notes.add(conn, "Delivery terms are DAP Rotterdam, payment 30 days net.")
    monkeypatch.setattr(ai, "_call", lambda *a, **k: "DAP Rotterdam.")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")

    ai.ask(conn, "delivery terms")

    sent = [e for e in recent_activity() if e["action"] == "sent"]
    assert sent, "a network send must leave a trace"
    assert "passage" in sent[0]["detail"]
    assert "anthropic" in sent[0]["detail"]


def test_grants_and_revocations_are_recorded():
    permissions = Permissions.load()
    permissions.decide(Permission.OPEN_FILES, True)
    permissions.decide(Permission.OPEN_FILES, False)
    actions = [e["action"] for e in recent_activity() if e["permission"] == "open_files"]
    assert "granted" in actions and "revoked" in actions


def test_deciding_the_same_way_twice_does_not_fill_the_log():
    permissions = Permissions.load()
    for _ in range(5):
        permissions.decide(Permission.WATCH_CHANGES, True)
    entries = [e for e in recent_activity() if e["permission"] == "watch_changes"]
    assert len(entries) == 1


# ---------------------------------------------------------------- features


def test_the_presets_only_propose_permissions_their_features_need():
    for preset in BY_PRESET.values():
        needed = set()
        for key in preset.features:
            feature = BY_KEY[key]
            needed |= set(feature.requires) | set(feature.improves_with)
        extra = set(preset.proposes) - needed
        assert not extra, f"{preset.key} asks for {extra} and uses none of it"


def test_the_private_preset_never_proposes_the_network():
    """The whole point of that preset."""
    private = BY_PRESET["private"]
    assert Permission.SEND_TO_AI not in private.proposes
    assert "ask" not in private.features


def test_a_pre_ticked_feature_is_still_inert_until_its_permission_is_given():
    """`default_on` pre-ticks a box in the setup wizard. It grants nothing.

    Search is pre-ticked because it is the reason most people install this,
    but it stays unusable until the folder permission is actually given.
    """
    fresh = Settings()
    for key in default_enabled():
        if BY_KEY[key].requires:
            assert not fresh.has(key), f"{key} is live before its permission was asked for"


def test_a_feature_that_is_on_but_blocked_says_so_rather_than_looking_fine():
    settings = Settings(features=["search"], setup_complete=True)
    described = {f["key"]: f for f in describe(settings.features, Permissions.load())}
    assert described["search"]["enabled"] is True
    assert described["search"]["usable"] is False
    assert described["search"]["blocked_by"] == ["read_folders"]


def test_before_setup_only_the_harmless_features_work():
    """A brand new install should not be a dead screen, but it also must not
    have quietly switched on anything that reads the disk."""
    settings = Settings()
    assert settings.has("notes") and settings.has("brief")
    assert not settings.has("search") and not settings.has("ask")


def test_asking_only_for_search_does_not_hand_you_a_to_do_list(conn, docs, granted):
    """A product that gives you things you did not choose is the thing this
    whole layer exists to prevent."""
    from cairn import indexer

    settings = Settings(folders=[str(docs)], features=["search"], setup_complete=True)
    result = indexer.reindex(conn, settings)

    assert result.added > 0, "search itself must still work"
    assert result.commitments == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM commitments").fetchone()["n"] == 0


# ------------------------------------------- the background sweep obeys it too


def test_the_background_sweep_does_nothing_without_the_permission(monkeypatch):
    """`watch_changes` was asked for in three of four presets and used nowhere.

    A permission you request and never exercise is the exact dishonesty this
    layer exists to prevent, so the behaviour now exists - and it has to obey
    the same switch as everything else.
    """
    import threading

    from cairn import server

    ran = []
    monkeypatch.setattr(server, "_run_index", lambda full: ran.append(full))
    monkeypatch.setattr(server, "FIRST_RESCAN_AFTER_SECONDS", 0)
    monkeypatch.setattr(server, "RESCAN_EVERY_SECONDS", 0.05)

    permissions = Permissions.load()
    permissions.decide(Permission.READ_FOLDERS, True)
    # watch_changes deliberately NOT granted

    stop = threading.Event()
    worker = threading.Thread(target=server._keep_index_fresh, args=(stop,), daemon=True)
    worker.start()
    stop.wait(0.3)
    stop.set()
    worker.join(timeout=2)

    assert ran == [], "it swept without being allowed to"


def test_revoking_mid_run_stops_the_next_background_sweep(monkeypatch, tmp_path):
    """Checked on every pass, not once at startup: revoke at 11:04 and the
    11:30 sweep must not happen."""
    import threading

    from cairn import server

    folder = tmp_path / "work"
    folder.mkdir()
    (folder / "a.txt").write_text("something", encoding="utf-8")
    settings = Settings(folders=[str(folder)], features=["search"], setup_complete=True)
    settings.save()

    ran = []
    monkeypatch.setattr(server, "_run_index", lambda full: ran.append(full))
    monkeypatch.setattr(server, "FIRST_RESCAN_AFTER_SECONDS", 0)
    monkeypatch.setattr(server, "RESCAN_EVERY_SECONDS", 0.05)

    permissions = Permissions.load()
    permissions.decide(Permission.READ_FOLDERS, True)
    permissions.decide(Permission.WATCH_CHANGES, True)

    stop = threading.Event()
    worker = threading.Thread(target=server._keep_index_fresh, args=(stop,), daemon=True)
    worker.start()
    stop.wait(0.25)
    assert ran, "it should have swept while allowed"

    permissions.decide(Permission.WATCH_CHANGES, False)
    server._index_state["running"] = False
    swept_by_then = len(ran)
    stop.wait(0.3)
    stop.set()
    worker.join(timeout=2)

    assert len(ran) == swept_by_then, "it kept sweeping after the permission was revoked"
