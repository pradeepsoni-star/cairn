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
def settings_for(docs):
    from cairn.config import Settings

    settings = Settings(folders=[str(docs)])
    settings.save()
    return settings


@pytest.fixture
def api_client(isolated_home, monkeypatch):
    """A TestClient over the real app, with its own database."""
    from fastapi.testclient import TestClient

    from cairn import server
    from cairn.db import connect

    connection = connect(Path(os.environ["CAIRN_HOME"]) / "api.db")
    monkeypatch.setattr(server, "_conn", connection)
    client = TestClient(server.app)
    client.headers.update({"X-Cairn-Token": server.TOKEN})
    yield client
    connection.close()
