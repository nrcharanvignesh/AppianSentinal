# Appian Sentinel

Offline agent that parses an Appian application export, inspects SAIL, and
emits full or patch ZIP packages. Python 3.11+ is required.

## Entry points

1. FastAPI web/sidecar (repo root): `python -m uvicorn appian_sentinel.main:app`
   or the console script `appian-sentinel` once the package is importable.
2. Electron + Next.js desktop app: `cd desktop` then `npm run dev`
   (see `desktop/README.md`). The MUI workbench defaults to dark mode and provides a
   persistent light mode. Production spawn is the PyInstaller sidecar.

## Python environment

Declared in `pyproject.toml`: runtime deps plus optional extras `dev`
(pytest, pytest-asyncio, ruff) and `build` (PyInstaller).

`pip install -e .` does not work with current setuptools. The file names
build-backend `setuptools.backends._legacy:_Backend`, which is not importable.
Until that line is changed, install deps from source:

```
python scripts/install_dev.py
```

Tests import `appian_sentinel` from this repository (cwd on `sys.path`).

## Clean checkout: run every check

From the repository root. These commands were run on this tree and exited 0.
`python -m pytest -q` here was 172 passed, 2 skipped (full Appian export present
on disk). A checkout without `./appian_export/` also skips the full-inventory
test, so expect 3 skipped and still exit 0.

```
python scripts/install_dev.py
python -m pytest -q
python -m ruff check appian_sentinel tests tools
```

Desktop UI compile (from `desktop/`, after `npm ci` if `node_modules` is missing).
There is no `npm run build:next` script.

```
cd desktop
npx next build
```

CI runs only the Python commands above. It does not build Electron or PyInstaller.

## Corpus-gated tests

`./appian_export/` is gitignored. It is the 2,624-object reference application
and is not in a clean clone, so these gates skip by default.

Enable the large rebuild and SAIL corpus tests:

```
set RUN_APPIAN_CORPUS=1
python -m pytest -q tests/test_package_equivalence.py tests/parser/test_sail_corpus_regression.py
```

On Unix: `RUN_APPIAN_CORPUS=1 python -m pytest ...`.

The full inventory test
`tests/test_codebase_inventory.py::test_optional_full_reference_inventory_reconciles`
skips when `./appian_export/` is absent (no env var). The committed slim fixture
is `tests/fixtures/reference_export/` (7 files) and always runs.

## Desktop ports

Defaults were moved off 7842/8888 because Testing Toolkit owns those.

- Agent/sidecar: 7842 (`SENTINEL_AGENT_PORT`)
- UI: 8888 (`SENTINEL_UI_PORT`)

Installer and sidecar steps: `docs/RUNBOOK.md`.
