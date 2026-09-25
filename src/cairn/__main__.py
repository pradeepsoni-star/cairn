"""What runs when someone double-clicks the downloaded file.

The packaged build has no terminal behind it, so the rules are different from
the command line: there is nobody to read a stack trace, and an error that
closes the window instantly is indistinguishable from "it didn't work".

So this does three things the CLI does not need to:

* defaults to opening the interface, because a double-click means "show me
  the thing", never "print usage and exit";
* finds a free port rather than failing when 8765 is taken, since the person
  who has something else on that port is not going to read a port error;
* writes any crash to a file next to the data and tells them where, because
  a window that vanishes teaches them nothing.
"""

from __future__ import annotations

import contextlib
import socket
import sys
import traceback


def _free_port(preferred: int = 8765) -> int:
    """The usual port if it is free, otherwise any port the OS will give us."""
    for candidate in (preferred, preferred + 1, preferred + 2):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", candidate))
                return candidate
            except OSError:
                continue
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _packaged() -> bool:
    """True when running from a PyInstaller build rather than from Python."""
    return getattr(sys, "frozen", False)


def main() -> int:
    from cairn.cli import main as cli_main

    arguments = sys.argv[1:]
    # A double-click passes no arguments. Anyone who typed a command meant it.
    if _packaged() and not arguments:
        return cli_main(["serve", "--port", str(_free_port())])
    return cli_main(arguments or None)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception:
        from cairn.config import data_dir

        report = data_dir() / "crash.txt"
        try:
            report.write_text(traceback.format_exc(), encoding="utf-8")
            print(f"\nCairn stopped unexpectedly. Details written to:\n  {report}\n")
        except OSError:
            traceback.print_exc()
        if _packaged():
            # Without this the window closes before anything can be read.
            with contextlib.suppress(EOFError, KeyboardInterrupt):
                input("Press Enter to close. ")
        raise SystemExit(1) from None
