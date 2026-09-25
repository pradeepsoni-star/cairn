"""API keys.

A key is a credential even when it is only yours, so the properties worth
testing are the ones about it NOT appearing places: not in a response, not in
the activity log, not on the screen it was typed into.
"""

import json

from cairn import modelkeys
from cairn.permissions import recent_activity

FAKE = "sk-test-DO-NOT-USE-abcdefghijklmnop9Z7Q"


def test_nothing_is_configured_on_a_fresh_install(isolated_home, monkeypatch):
    for names in modelkeys.ENV_NAMES.values():
        for name in names:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert not any(row["configured"] for row in modelkeys.describe()["providers"])


def test_a_saved_key_is_used(isolated_home, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    modelkeys.set_key("gemini", FAKE)
    assert modelkeys.key_for("gemini") == FAKE


def test_the_environment_always_wins(isolated_home, monkeypatch):
    """A machine set up by its owner or their IT department keeps behaving the
    way they set it up, whatever is typed into the app."""
    modelkeys.set_key("gemini", "saved-in-the-app")
    monkeypatch.setenv("GEMINI_API_KEY", "set-in-the-environment")
    assert modelkeys.key_for("gemini") == "set-in-the-environment"
    assert modelkeys.describe()["providers"][2]["source"] == "environment"


def test_describe_never_contains_the_key(isolated_home, monkeypatch):
    """The one that matters. A screen that redisplays a secret leaks it to
    whoever is standing behind you."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    modelkeys.set_key("gemini", FAKE)
    assert FAKE not in json.dumps(modelkeys.describe())


def test_only_the_last_four_characters_are_shown(isolated_home, monkeypatch):
    """The last four, not the first: the start of an API key is a fixed,
    guessable prefix and identifies nothing."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    modelkeys.set_key("gemini", FAKE)
    row = next(r for r in modelkeys.describe()["providers"] if r["key"] == "gemini")
    assert row["tail"] == "...9Z7Q"
    assert FAKE[:10] not in row["tail"]


def test_a_key_can_be_removed(isolated_home, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    modelkeys.set_key("gemini", FAKE)
    modelkeys.set_key("gemini", "")
    assert modelkeys.key_for("gemini") == ""


def test_ollama_needs_no_key_but_must_be_asked_for(isolated_home, monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("CAIRN_OLLAMA", raising=False)
    assert modelkeys.ollama_enabled() is False
    modelkeys.set_ollama_host("http://localhost:11434")
    assert modelkeys.ollama_enabled() is True
    assert modelkeys.ollama_host() == "http://localhost:11434"


def test_the_ollama_default_fits_an_ordinary_laptop(isolated_home):
    """An 8B model on a machine with no graphics card answers in minutes and
    reads as broken. A small model that replies beats a good one that does not."""
    from cairn.ai import DEFAULT_MODELS

    assert DEFAULT_MODELS["ollama"] == "llama3.2"


# ------------------------------------------------------------- over the wire


def test_saving_a_key_needs_the_token(api_client):
    response = api_client.post(
        "/api/model", json={"provider": "gemini", "key": FAKE}, headers={"X-Cairn-Token": ""}
    )
    assert response.status_code == 403


def test_a_key_never_comes_back_over_http(api_client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    api_client.post("/api/model", json={"provider": "gemini", "key": FAKE})

    assert FAKE not in api_client.get("/api/model").text
    assert FAKE not in api_client.get("/api/state").text


def test_a_key_is_never_written_to_the_activity_log(api_client, monkeypatch):
    """The log is a plain text file users are encouraged to read and might
    reasonably paste to someone helping them."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    api_client.post("/api/model", json={"provider": "gemini", "key": FAKE})

    assert FAKE not in api_client.get("/api/activity").text
    entries = [e for e in recent_activity() if e["permission"] == "model"]
    assert entries and entries[0]["detail"] == "gemini"


def test_an_unknown_provider_is_refused(api_client):
    response = api_client.post("/api/model", json={"provider": "someone-else", "key": "x"})
    assert response.status_code == 400
