# PyInstaller build: one file somebody can download and double-click.
#
# `pip install` is a barrier to exactly the person who needs this tool most -
# the one who keeps their whole working life in Documents and has never opened
# a terminal. So the packaged build carries everything: the document readers,
# the Google libraries, the web interface. It is larger than a wheel and that
# is the right trade, because the alternative is an install that fails halfway
# with a message about a missing extra.
#
# Build:  pyinstaller packaging/cairn.spec --noconfirm

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"

# The interface is three static files read at runtime, so they must travel.
datas = [(str(SRC / "cairn" / "web"), "cairn/web")]

# googleapiclient ships its API discovery documents as package data, and the
# client cannot build a service without them.
datas += collect_data_files("googleapiclient", includes=["**/*.json"])

hiddenimports = [
    # uvicorn resolves these by name at runtime, so static analysis misses them.
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    # Format readers are imported lazily, inside the function that uses them.
    "pypdf",
    "docx",
    "openpyxl",
    "pptx",
    "striprtf.striprtf",
]
hiddenimports += collect_submodules("cairn")

analysis = Analysis(
    [str(SRC / "cairn" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Nothing here is used, and each one costs tens of megabytes.
    excludes=[
        "tkinter", "matplotlib", "numpy", "pandas", "scipy",
        "PIL", "PySide6", "PyQt5", "PyQt6", "notebook", "IPython",
    ],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="cairn",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # A console window, deliberately. Cairn's interface is a browser tab, and
    # if the server dies the console is the only place the reason appears. A
    # windowless build that fails leaves the user with nothing at all.
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
