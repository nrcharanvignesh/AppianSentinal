# Appian Sentinel — Desktop App

A standalone Electron + Next.js desktop app with an embedded Python engine.
Upload an Appian export `.zip`, see it organized by object type, drive
the center chatbot with a requirement (typed, PDF, or pulled from Azure DevOps),
and get back a `.zip` containing **only the objects that requirement needs**.

## Architecture

```
AppianSentinel.exe (Electron)
├─ electron/main.js ...... picks a free port, starts the Python engine,
│                          waits for /api/health, serves the UI, opens the window
├─ Next.js renderer ...... app/ — the 3-column UI (talks to the engine over localhost)
└─ Python engine ......... FastAPI in development; bundled executable in production
```

The engine address is injected into the renderer by `electron/preload.js` as
`window.__SENTINEL_API__ = { baseUrl, wsUrl }`.

## Prerequisites

- Node 18+ and npm
- Python 3.11+ with development dependencies installed from the repo root:
  `python scripts/install_dev.py`
- PyInstaller for packaging: `python -m pip install pyinstaller`

## Development

```bash
cd desktop
npm install
npm run dev          # starts Next (localhost:3000), Electron, and the engine
```

`npm run dev` launches everything. Electron waits for the engine's `/api/health`
before loading the UI. If the window shows “Starting engine…” for a long time,
check that `python -m uvicorn appian_sentinel.main:app` runs from the repo root.

> If Electron exits immediately, make sure `ELECTRON_RUN_AS_NODE` is **not** set
> in your shell (the dev scripts already clear it).

## First-run setup (in the app)

Open **Settings** (gear icon) and set:

- **Model service URL**
- **API key**
- **Connection type**
- **Primary model** and **Fast model**
- **Azure DevOps organization**, **project**, and **access token**

Use **Test** to save the settings and verify the model service connection.

## Building the installer (offline app)

```bash
cd desktop
npm run dist         # builds the Windows engine and desktop installers
```

Outputs:
- `../dist/appian-sentinel-sidecar/` — the bundled Python engine (one-dir)
- `desktop/release/desktop/AppianSentinel-Setup.exe` - stable NSIS installer copy
- `installers/AppianSentinel-Standalone-Install.cmd` - verified silent-install wrapper

The engine folder is packed into the app under `resources/sidecar/` and started
by `electron/main.js` in production.

## The Appian MCP server

The same engine is exposed as an MCP server (`appian-sentinel-mcp`). It registers
167 tools: 31 general tools and four typed CRUD tools for each of 34 Appian
object types. `appian_sentinel/mcp_server/server.py` is the authoritative list.

- Analysis: `analyze_appian_zip`, `get_codebase`, `search_objects`, `get_object`,
  `list_objects`, `resolve_object`, `get_dependency_graph`, `workspace_status`
- Code intelligence: `inspect_sail`, `validate_sail`, `validate_object`,
  `validate_workspace`
- Requirements: `read_ado_work_item`, `normalize_requirement`
- Changes: `apply_object_change`, `apply_sail_edit`, `bulk_add_tests`,
  `bulk_replace_tests`
- History: `history_log`, `history_diff`, `history_commit`, `history_restore`
- Tests: `get_object_tests`, `run_object_static_test`, `run_static_tests`,
  `validate_test_coverage`
- Generation: `generate_sail`, `generate_test_suite`, `generate_solution_design`
  (these require a configured model service and return an error without one)
- Packaging: `generate_patch_zip`, `generate_full_zip`

`generate_test_suite`, `get_object_tests`, and `bulk_replace_tests` use Appian's
three expression-rule assertion modes: no-error completion, exact typed output,
and focused SAIL expressions that reference `test!output`. Test XML is cloned
from assertion-compatible templates already present in the exported rule.

Typed CRUD registration does not mean that every type can be created without
an export template. Native creation is implemented for 21 types. Record types
and process models currently use a same-type template through typed CRUD.
Eleven types have no proven native writer because the validation corpus has no
matching Appian export sample: AI Agent, AI Skill, Business Process, Process
Report, Robotic Task, Robot Pool, Dashboard, Control Panel, Control Panel
Hierarchy Item, Group Type, and Feed.

The real-export CRUD gate is not green. Data type and record type objects cannot
be found after typed creation. Process model and Web API reads can return the
original name after an update. The reference export also has no Event Consumer
sample against which to validate native creation.

Register it with any MCP client (Claude Desktop / Cursor), e.g.:

```json
{
  "mcpServers": {
    "appian-sentinel": {
      "command": "appian-sentinel-mcp"
    }
  }
}
```

(or `"command": "python", "args": ["-m", "appian_sentinel.mcp_server.server"]`).
