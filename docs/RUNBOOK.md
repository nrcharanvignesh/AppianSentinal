# Desktop and installer runbook

Order below is the production path on Windows. Python 3.11+, Node 18+, and
`pip` packages from `pyproject.toml` extras `dev` and `build` are required.
Use `python scripts/install_dev.py` for tests. For PyInstaller also install
the `build` extra (`pip install pyinstaller`) because `pip install -e .[build]`
hits the same broken `setuptools.backends._legacy` backend as editable install.

## 1. Sidecar binary

From the repository root:

```
pyinstaller sidecar.spec --noconfirm
```

Runtime is about 7-8 minutes. Output is `dist/appian-sentinel-sidecar/` at
about 90 MB.

The spec must bundle `appian_sentinel/web/static` and
`appian_sentinel/web/templates`. `main.py` mounts `StaticFiles` and Jinja
templates at import time; without those directories the frozen exe aborts
before it binds a port. The spec also bundles `appian.skill` and
`GenAI Documentation.xlsx`.

## 2. Frozen smoke

`python tools/smoke_sidecar.py` with no extra env tests the **source** uvicorn
process, not the binary. That distinction already hid a frozen startup crash.

To smoke the built exe, point at it and run the same script. It checks
`/api/health` ownership echo and the token gate on `/api/status`.

```
set SENTINEL_SMOKE_SIDECAR_EXE=dist\appian-sentinel-sidecar\appian-sentinel-sidecar.exe
python tools/smoke_sidecar.py
```

Default bind used by the smoke script is `127.0.0.1:7851`.

## 3. Next.js renderer and Electron installer

```
cd desktop
npm ci
npx next build
npm run dist
```

`npm run dist` is `npm run build:installers:win`, which:

1. Runs `pyinstaller sidecar.spec --noconfirm` again from the repo (or a short
   path mirror when the repo path is >= 100 characters).
2. Runs `npm run build:desktop` (`next build --webpack` plus electron-builder).
3. Writes `desktop/release/desktop/AppianSentinel-Setup.exe` and the delivery
   wrapper `installers/AppianSentinel-Standalone-Install.cmd`.

There is no `npm run build:next`. NSIS output lives under
`desktop/release/desktop/` (`electron-builder.yml` `directories.output`).
The sidecar folder is packed as `resources/sidecar/`.

If Electron exits immediately, unset `ELECTRON_RUN_AS_NODE` in the shell.

### Trap: corrupt electron-builder cache (`EPERM` on rename)

A build can complete PyInstaller, Next, packaging and signing, then fail on the
last step with:

```
EPERM: operation not permitted, rename
  ...\electron-builder\Cache\nsis-resources-3.4.1\nsis-resources-3.4.1-XXXXX.tmp
  -> ...\electron-builder\Cache\nsis-resources-3.4.1\nsis-resources-3.4.1-XXXXX
```

This is a half-extracted download, not a code defect; the same class of failure
has hit the cached Electron zip. Clear the entries and re-run:

```powershell
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\electron-builder\Cache\nsis-resources-3.4.1"
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\electron-builder\Cache\nsis-3.0.4.1"
```

To avoid re-running the 8-minute PyInstaller step while diagnosing, retry just
`npx electron-builder --win --config electron-builder.yml --publish never`; the
sidecar and `.next/standalone` outputs are reused.

### Verifying the delivery artifact

`npm run build:installers:win` prints the output path on success. Verify the
payload rather than trusting the write: read the `.cmd`, base64-decode every
line after the `:BUNDLE` marker, and confirm the byte count and SHA-256 match
both the `$ExpectedBytes`/`$ExpectedSha256` header values and
`desktop/release/desktop/AppianSentinel-Setup.exe` on disk. Known-good run:
190,525,297 bytes of payload inside a 242.3 MB `.cmd`.

## Playwright

`playwright install chromium` hangs on this network. Use installed Edge:

`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`

Pass that path as Playwright `executable_path`. Prefer
`wait_until="domcontentloaded"` over `"networkidle"` for this app.
`desktop/playwright.config.js` uses channel `msedge` and port 8911
(`SENTINEL_PW_PORT`).

## Ports

- Sidecar/agent: 7851 (`SENTINEL_AGENT_PORT`)
- UI: 8871 (`SENTINEL_UI_PORT`)
- 7842 and 8888 are owned by Testing Toolkit; do not reuse them.
- 8899 is held by a local Java process on the developer machine; do not bind it.

## Parallel lane integration

Work was split by file ownership so parallel agents did not share write trees:

- Engine and tests: `appian_sentinel/`, `tests/`, `tools/`, `sidecar.spec`,
  `pyproject.toml`
- Desktop shell: `desktop/`
- Process and verification docs: this file, root `README.md`,
  `.github/workflows/ci.yml`, status lines in `docs/REQUIREMENTS.md`

Conflicts were avoided by not editing another lane's files. Shared gates are
the commands in the root README (`pytest`, `ruff`, `npx next build`). Corpus
proof stays local behind `./appian_export/` and `RUN_APPIAN_CORPUS=1`; CI does
not claim that proof.

Per-lane evidence, including the defect each lane found, is archived in
`docs/LANE-EVIDENCE.md`.

## Trap: credentials in tracebacks

`logger.exception(...)` writes a full traceback. Provider and Azure DevOps errors
embed the outbound request, including the `Authorization` and PAT headers, so a
traceback at an authenticated call site puts a live credential into the log stream.
Log a masked message instead and drop `exc_info` at any site downstream of an
authenticated call.

Blast radius today is a developer terminal, not disk: the sidecar configures logging
with `basicConfig` and no `FileHandler`, `pipeChild` in `desktop/electron/main.js`
forwards sidecar output to the supervisor's own stdout/stderr rather than to
`desktop.log`, and a packaged Windows GUI build has no console at all. Two conditions
would turn this into on-disk credential storage, so treat masking as load-bearing
rather than cosmetic:

- The sidecar already receives `SENTINEL_LOG_DIR`. Adding a `FileHandler` that honors
  it would persist every unmasked traceback.
- Redirecting `pipeChild` into `desktop.log` would do the same.

Workspace history is not a leak path here. `_TRACKED_ROOTS` in
`appian_sentinel/services/workspace.py` is an allowlist of Appian export directories,
so log files and `settings.json` are never snapshotted even if they sit in the
workspace root. Keep it an allowlist; a denylist would invert that guarantee.
