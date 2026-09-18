# Appian Sentinel — Desktop App

A standalone Electron + Next.js desktop app with the Python engine embedded as a
sidecar. Upload an Appian export `.zip`, see it organized by object type, drive
the center chatbot with a requirement (typed, PDF, or pulled from Azure DevOps),
and get back a `.zip` containing **only the objects that requirement needs**.

## Architecture

```
AppianSentinel.exe (Electron)
├─ electron/main.js ...... picks a free port, spawns the Python sidecar,
│                          waits for /api/health, serves the UI, opens the window
├─ Next.js renderer ...... app/ — the 3-column UI (talks to the sidecar over localhost)
└─ Python sidecar ........ the existing FastAPI engine (dev: uvicorn; prod: bundled exe)
```

The sidecar address is injected into the renderer by `electron/preload.js` as
`window.__SENTINEL_API__ = { baseUrl, wsUrl }`.

## Prerequisites

- Node 18+ and npm
- Python 3.11+ with the engine installed from the repo root: `pip install -e .`
  (or `pip install -e .[build]` to also get PyInstaller for packaging)

## Development

```bash
cd desktop
npm install
npm run dev          # starts Next (localhost:3000) + Electron, which spawns the sidecar
```

`npm run dev` launches everything. Electron waits for the sidecar's `/api/health`
before loading the UI. If the window shows “Starting engine…” for a long time,
check that `python -m uvicorn appian_sentinel.main:app` runs from the repo root.

> If Electron exits immediately, make sure `ELECTRON_RUN_AS_NODE` is **not** set
> in your shell (the dev scripts already clear it).

## First-run setup (in the app)

Open **Settings** (gear icon) and set:

- **LiteLLM Base URL** — e.g. `https://genai-sharedservice-americas.pwcinternal.com/`
- **LiteLLM API Key**
- **Primary / Fast Model** — `bedrock.anthropic.claude-opus-4-8` / `bedrock.anthropic.claude-sonnet-5`
- **Azure DevOps** — Source (`PAT` or `ADO MCP`), Organization, Project, PAT

Use **Test Connection** to verify the LLM proxy before running a workflow.

## Building the installer (offline app)

```bash
cd desktop
npm run dist         # 1) PyInstaller bundles the sidecar  2) next build  3) electron-builder
```

Outputs:
- `../dist/appian-sentinel-sidecar/` — the bundled Python sidecar (one-dir)
- `desktop/dist/` — the packaged `AppianSentinel` installer (NSIS on Windows)

The sidecar folder is packed into the app under `resources/sidecar/` and spawned
by `electron/main.js` in production.

## The Appian MCP server

The same engine is exposed as an MCP server (`appian-sentinel-mcp`) with tools:
`analyze_appian_zip`, `search_objects`, `get_object`, `read_ado_work_item`,
`apply_object_change`, `generate_patch_zip`.

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
