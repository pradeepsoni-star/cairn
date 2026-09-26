"""The HTTP surface.

The security tests here are not ceremony. Any web page you have open can
make requests to 127.0.0.1, so an endpoint that opens files or spends money
without a token is a hole, and an open-file endpoint that accepts any path
is a way to launch arbitrary programs from a crafted page.
"""


def test_the_page_is_served_with_its_token(api_client):
    from cairn import server

    response = api_client.get("/")
    assert response.status_code == 200
    assert server.TOKEN in response.text
    assert "__CAIRN_TOKEN__" not in response.text


def test_state_is_readable_without_a_token(api_client):
    """Reading is harmless; the page needs this before it has done anything."""
    response = api_client.get("/api/state", headers={"X-Cairn-Token": ""})
    assert response.status_code == 200
    assert "stats" in response.json()


def test_writing_without_the_token_is_refused(api_client):
    response = api_client.post("/api/notes", json={"body": "x"}, headers={"X-Cairn-Token": ""})
    assert response.status_code == 403


def test_a_wrong_token_is_refused(api_client):
    response = api_client.post(
        "/api/notes", json={"body": "x"}, headers={"X-Cairn-Token": "guessed"}
    )
    assert response.status_code == 403


def test_opening_a_path_that_is_not_indexed_is_refused(api_client):
    """Otherwise a crafted page could launch anything on the machine."""
    response = api_client.post("/api/open", json={"path": "C:/Windows/System32/calc.exe"})
    assert response.status_code == 404


# --------------------------------------------------------------------- flow


def test_a_note_becomes_a_commitment_and_shows_up_in_the_brief(api_client):
    saved = api_client.post(
        "/api/notes",
        json={"body": "Spoke to the supplier. I'll send the revised figures tomorrow."},
    ).json()
    assert saved["commitments_found"] == 1

    items = api_client.get("/api/commitments").json()["items"]
    assert any("revised figures" in item["text"] for item in items)

    brief = api_client.get("/api/brief").json()
    assert brief["stats"]["open_commitments"] == 1


def test_a_note_is_searchable_straight_away(api_client):
    api_client.post("/api/notes", json={"body": "The warehouse lease renews in November."})
    hits = api_client.get("/api/search", params={"q": "warehouse lease"}).json()
    assert hits["count"] == 1


def test_ticking_a_commitment_removes_it_from_the_open_list(api_client):
    api_client.post("/api/notes", json={"body": "I'll call the freight forwarder on Monday."})
    item = api_client.get("/api/commitments").json()["items"][0]
    assert api_client.post(f"/api/commitments/{item['id']}/done").status_code == 200
    assert api_client.get("/api/commitments").json()["items"] == []


def test_deleting_a_note_does_not_cancel_the_promise_in_it(api_client):
    """Deliberate: you said you would do the thing. Tidying your notes is not
    the same as deciding not to do it."""
    saved = api_client.post(
        "/api/notes", json={"body": "I'll confirm the shipping date by Friday."}
    ).json()
    api_client.delete(f"/api/notes/{saved['id']}")
    assert api_client.get("/api/commitments").json()["items"]


def test_a_commitment_added_by_hand_gets_its_date_read(api_client):
    response = api_client.post(
        "/api/commitments", json={"text": "renew the insurance by end of the month"}
    )
    assert response.json()["due"], "the date in the sentence should have been picked up"


def test_the_folder_picker_never_offers_noise(api_client, tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "node_modules").mkdir()
    children = api_client.get("/api/folders", params={"path": str(tmp_path)}).json()["children"]
    names = {child["name"] for child in children}
    assert "real" in names and "node_modules" not in names


def test_asking_without_a_configured_model_explains_itself(api_client, monkeypatch):
    for variable in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
                     "GOOGLE_API_KEY", "OLLAMA_HOST", "CAIRN_OLLAMA"):
        monkeypatch.delenv(variable, raising=False)
    api_client.post("/api/notes", json={"body": "Delivery terms are DAP Rotterdam."})
    result = api_client.post("/api/ask", json={"question": "what are the delivery terms"}).json()
    # It must say what to DO, not name an environment variable. Someone who
    # does not know what one is cannot act on "set ANTHROPIC_API_KEY".
    assert result["error"]
    assert "ask" in result["error"].lower()
    assert "free" in result["error"].lower(), "it should point at the option that costs nothing"


def test_asking_about_something_absent_says_so_without_calling_a_model(api_client):
    result = api_client.post("/api/ask", json={"question": "zzzz nothing like this exists"}).json()
    assert "Nothing in your indexed files" in result["answer"]
    assert not result.get("error")


def test_a_dated_item_never_lands_in_the_no_date_bucket(api_client):
    """The screen once read NO DATE above a row saying "Apr 13"."""
    api_client.post("/api/commitments", json={"text": "file the annual return by 13/04"})
    brief = api_client.get("/api/brief").json()
    assert brief["undated"] == []
    assert brief["due_later"], "a far-off date belongs in Later, not in No date"


def test_the_headline_counts_in_english(api_client):
    api_client.post("/api/commitments", json={"text": "Ravi will send the packing list today"})
    brief = api_client.get("/api/brief").json()
    assert brief["headline"] == "One thing is due today.", brief["headline"]


def test_state_offers_folders_rather_than_assuming_them(api_client):
    """Cairn reads whole documents, so which folders is the user's call."""
    state = api_client.get("/api/state").json()
    assert state["settings"]["folders"] == []
    assert isinstance(state["suggested_folders"], list)


def test_saving_the_same_note_twice_does_not_double_the_commitments(api_client):
    """A double-click on Save is not a second meeting."""
    body = "Call with the bank. I'll send the signed mandate form on Tuesday."
    first = api_client.post("/api/notes", json={"body": body}).json()
    second = api_client.post("/api/notes", json={"body": body}).json()

    assert second["duplicate"] is True
    assert second["id"] == first["id"]
    assert len(api_client.get("/api/notes").json()["items"]) == 1
    assert len(api_client.get("/api/commitments").json()["items"]) == 1


def test_the_cli_can_grant_and_revoke_without_the_browser(isolated_home, capsys):
    """The terminal-first user must not be locked out by the consent layer."""
    from cairn.cli import main
    from cairn.permissions import Permission, Permissions

    assert main(["permissions", "--allow", "read_folders"]) == 0
    assert Permissions.load().allowed(Permission.READ_FOLDERS)

    assert main(["permissions", "--revoke", "read_folders"]) == 0
    assert not Permissions.load().allowed(Permission.READ_FOLDERS)


def test_the_cli_will_not_grant_sending_mail_casually(isolated_home):
    from cairn.cli import main
    from cairn.permissions import Permission, Permissions

    assert main(["permissions", "--allow", "gmail_send"]) == 1
    assert not Permissions.load().allowed(Permission.GMAIL_SEND)

    assert main(["permissions", "--allow", "gmail_send", "--i-understand"]) == 0
    assert Permissions.load().allowed(Permission.GMAIL_SEND)


def test_a_cli_preset_changes_nothing_until_confirmed(isolated_home):
    from cairn.cli import main
    from cairn.config import Settings
    from cairn.permissions import Permission, Permissions

    assert main(["setup", "--preset", "find"]) == 0
    assert Settings.load().setup_complete is False
    assert not Permissions.load().allowed(Permission.READ_FOLDERS)

    assert main(["setup", "--preset", "find", "--yes"]) == 0
    assert Settings.load().features == ["search"]
    assert Permissions.load().allowed(Permission.READ_FOLDERS)


def test_an_unknown_permission_name_is_rejected(isolated_home):
    from cairn.cli import main

    assert main(["permissions", "--allow", "read_everything"]) == 1


def test_the_brief_counts_what_is_open_not_what_fits_on_the_page(api_client):
    """It once announced "you are waiting on 100 things" because its list was
    capped at 100. A page size stated as a fact is worse than no number."""
    from cairn import commitments, server

    items = [
        commitments.Commitment(f"Someone will confirm item {n}", "them", None, "note", f"n:{n}")
        for n in range(150)
    ]
    commitments.store(server.db(), items)
    server.db().commit()

    brief = api_client.get("/api/brief").json()
    assert brief["waiting_on_total"] == 150
    assert len(brief["waiting_on"]) == 100, "the list is still paged"
    assert "150 things" in brief["headline"], brief["headline"]
