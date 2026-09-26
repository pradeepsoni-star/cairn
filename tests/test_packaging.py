"""The downloaded build.

A packaged Cairn has no terminal behind it, so the failure modes are
different: nobody reads a stack trace, and a window that vanishes teaches
the user nothing. These tests cover the small amount of behaviour that only
exists because of that.
"""

import socket

from cairn.__main__ import _free_port


def test_the_usual_port_is_used_when_it_is_free():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        spare = int(probe.getsockname()[1])
    assert _free_port(spare) == spare


def test_something_else_on_the_port_does_not_stop_it_starting():
    """The person who already has something on 8765 will not read a port
    error - they will conclude the program is broken."""
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        blocked = int(taken.getsockname()[1])

        chosen = _free_port(blocked)
        assert chosen != blocked
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", chosen))  # raises if the choice was wrong


def test_the_interface_files_travel_with_the_package():
    """PyInstaller bundles what it is told to. If these move, the spec must
    move with them, and a build that silently serves nothing is the result."""
    from cairn.server import WEB_DIR

    for name in ("index.html", "app.js", "style.css"):
        assert (WEB_DIR / name).is_file(), f"{name} is missing from cairn/web"


def test_the_page_still_carries_its_token_placeholder():
    """The whole CSRF protection rests on this substitution happening."""
    from cairn.server import WEB_DIR

    assert "__CAIRN_TOKEN__" in (WEB_DIR / "index.html").read_text(encoding="utf-8")


def test_it_prefers_a_real_window_over_a_browser_tab(monkeypatch):
    """Someone who double-clicks a program and lands in a browser tab, beside
    their email and twelve other tabs, has been told it is a web page rather
    than a thing they installed."""
    from cairn import server

    launched = {}

    def fake_popen(command, **kwargs):
        launched["command"] = command
        return object()

    monkeypatch.setattr(server, "_app_mode_browsers", lambda: [["/fake/chrome"]])
    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)

    assert server.open_as_app("http://127.0.0.1:8765/") == "app window"
    assert "--app=http://127.0.0.1:8765/" in launched["command"]


def test_it_still_opens_when_no_chromium_browser_exists(monkeypatch):
    """A machine with only Firefox, or a locked-down build with the flag
    disabled, must still end up looking at Cairn rather than at nothing."""
    import webbrowser

    from cairn import server

    opened = {}
    monkeypatch.setattr(server, "_app_mode_browsers", lambda: [])
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.setdefault("url", url) or True)

    assert server.open_as_app("http://127.0.0.1:8765/") == "browser tab"
    assert opened["url"] == "http://127.0.0.1:8765/"


def test_a_browser_that_refuses_to_start_falls_through_to_the_next(monkeypatch):
    from cairn import server

    tried = []

    def fussy(command, **kwargs):
        tried.append(command[0])
        if command[0] == "/broken":
            raise OSError("no such file")
        return object()

    monkeypatch.setattr(server, "_app_mode_browsers", lambda: [["/broken"], ["/works"]])
    monkeypatch.setattr(server.subprocess, "Popen", fussy)

    assert server.open_as_app("http://x/") == "app window"
    assert tried == ["/broken", "/works"]
