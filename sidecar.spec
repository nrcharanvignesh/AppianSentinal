# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Appian Sentinel sidecar.

Builds a one-dir executable at ``dist/appian-sentinel-sidecar/`` that Electron
spawns in production. Bundle with:

    pyinstaller sidecar.spec --noconfirm

The whole ``dist/appian-sentinel-sidecar/`` folder is then packed by
electron-builder (see desktop/package.json -> build.extraResources).
"""

from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [("Appian Sentinel.txt", ".")]
binaries = []
hiddenimports = []

# Pull in packages that load data files / use dynamic imports.
for pkg in (
    "uvicorn", "fastapi", "starlette", "pdfplumber", "pdfminer",
    "lxml", "anyio", "websockets", "aiofiles", "openai",
    "pydantic", "pydantic_settings", "httpx", "multipart",
):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

# uvicorn resolves its loop/protocol implementations dynamically.
hiddenimports += collect_submodules("uvicorn")
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]

a = Analysis(
    ["appian_sentinel/sidecar.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="appian-sentinel-sidecar",
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="appian-sentinel-sidecar",
)
