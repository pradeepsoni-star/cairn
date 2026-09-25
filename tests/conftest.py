"""Test fixtures.

Every test runs against a throwaway CAIRN_HOME. This is not politeness: the
suite indexes folders and writes commitments, and a test run that touched
the developer's own index would be a tool that eats its author's data the
first time someone runs pytest.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "cairn-home"
    home.mkdir()
    monkeypatch.setenv("CAIRN_HOME", str(home))
    yield home


@pytest.fixture
def conn(isolated_home):
    from cairn.db import connect

    connection = connect(isolated_home / "test.db")
    yield connection
    connection.close()


@pytest.fixture
def docs(tmp_path):
    """A small folder that looks like somebody's real working directory."""
    root = tmp_path / "work"
    (root / "notes").mkdir(parents=True)
    (root / "node_modules" / "junk").mkdir(parents=True)
    (root / ".git").mkdir()

    (root / "notes" / "meeting-2026-03-02.md").write_text(
        "# Supplier call\n"
        "Discussed the March shipment and the revised tooling cost.\n"
        "I'll send the updated quotation on Thursday.\n"
        "Anita will confirm the container booking.\n"
        "Already sent the old catalogue last week.\n",
        encoding="utf-8",
    )
    (root / "budget.csv").write_text(
        "item,cost\nfreight,1200\npackaging,340\ntooling,8800\n", encoding="utf-8"
    )
    (root / "readme.txt").write_text(
        "Project Falcon covers the packaging redesign for the northern warehouse.\n",
        encoding="utf-8",
    )
    (root / "node_modules" / "junk" / "huge.txt").write_text("noise " * 500, encoding="utf-8")
    (root / ".git" / "config.txt").write_text("secret repo internals", encoding="utf-8")
    return root


@pytest.fixture
def granted():
    """Grant every capability.

    Tests that are about indexing or searching should not also be re-testing
    the permission gate, so they ask for this explicitly. The gate itself is
    tested from a clean slate in test_permissions.py - and the fact that
    every one of these tests failed the moment the gate was added is the
    evidence that it is actually in the path.
    """
    from cairn.permissions import Permission, Permissions

    permissions = Permissions.load()
    for permission in Permission:
        permissions.decide(permission, True)
    return permissions


@pytest.fixture
def settings_for(docs, granted):
    from cairn.config import Settings
    from cairn.features import default_enabled

    settings = Settings(folders=[str(docs)], features=default_enabled() + ["ask"])
    settings.setup_complete = True
    settings.save()
    return settings


@pytest.fixture
def api_client(isolated_home, granted, monkeypatch):
    """A TestClient over the real app, fully set up and fully permitted.

    For the opposite - a fresh install that has been granted nothing - use
    `bare_client`.
    """
    from fastapi.testclient import TestClient

    from cairn import server
    from cairn.config import Settings
    from cairn.db import connect
    from cairn.features import BY_KEY

    settings = Settings.load()
    settings.features = list(BY_KEY)
    settings.setup_complete = True
    settings.save()

    connection = connect(Path(os.environ["CAIRN_HOME"]) / "api.db")
    monkeypatch.setattr(server, "_conn", connection)
    client = TestClient(server.app)
    client.headers.update({"X-Cairn-Token": server.TOKEN})
    yield client
    connection.close()


@pytest.fixture
def bare_client(isolated_home, monkeypatch):
    """A TestClient over a FRESH install: nothing granted, setup not done.

    This is what a stranger downloading Cairn actually gets, and it is the
    state most worth testing.
    """
    from fastapi.testclient import TestClient

    from cairn import server
    from cairn.db import connect

    connection = connect(Path(os.environ["CAIRN_HOME"]) / "bare.db")
    monkeypatch.setattr(server, "_conn", connection)
    client = TestClient(server.app)
    client.headers.update({"X-Cairn-Token": server.TOKEN})
    yield client
    connection.close()
