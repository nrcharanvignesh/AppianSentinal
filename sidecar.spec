# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Appian Sentinel sidecar.

Builds a one-dir executable at ``dist/appian-sentinel-sidecar/`` that Electron
spawns in production. Bundle with:

    pyinstaller sidecar.spec --noconfirm

The whole ``dist/appian-sentinel-sidecar/`` folder is then packed by
electron-builder (see desktop/package.json -> build.extraResources).
"""

from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [
    ("Appian Sentinel.txt", "."),
    ("appian.skill", "."),
    ("GenAI Documentation.xlsx", "."),
    # main.py mounts StaticFiles and Jinja2Templates at import time; without
    # these the frozen exe aborts on startup before it can bind a port.
    ("appian_sentinel/web/static", "appian_sentinel/web/static"),
    ("appian_sentinel/web/templates", "appian_sentinel/web/templates"),
]
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

# The build interpreter is a shared global Python that also carries Qt, the
# scientific stack, torch and dev tooling. None of it is imported by
# appian_sentinel, but PyInstaller's hook chain collects it anyway: Qt aborts
# the build outright and torch/scipy add gigabytes. Excluding by name is the
# documented remedy.
# ponytail: name-based excludes; build the sidecar in a dedicated minimal venv
# if this list starts needing maintenance.
_EXCLUDES = [
    # GUI toolkits (two Qt bindings present -> hard build abort)
    "PyQt5", "PyQt6", "PySide2", "PySide6", "shiboken2", "shiboken6",
    "tkinter", "_tkinter", "wx", "kivy", "pygame",
    # scientific / ML stack
    "torch", "torchvision", "torchaudio", "tensorflow", "keras",
    "numpy", "pandas", "scipy", "sklearn", "matplotlib", "seaborn",
    "numba", "llvmlite", "sympy", "polars", "pyarrow", "h5py",
    "transformers", "tokenizers", "safetensors", "onnx", "onnxruntime",
    "cv2", "PIL", "skimage",
    # notebooks / interactive
    "IPython", "ipykernel", "jupyter", "jupyter_client", "jupyter_core",
    "notebook", "nbformat", "nbconvert", "zmq", "traitlets",
    # dev + docs tooling
    "pytest", "_pytest", "py", "sphinx", "docutils", "babel",
    "black", "blib2to3", "yapf", "yapf_third_party", "pylint", "astroid",
    "jedi", "parso", "isort", "mypy", "ruff",
]

a = Analysis(
    ["appian_sentinel/sidecar.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=_EXCLUDES,
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
