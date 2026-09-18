# Lane evidence archive

Requirement 4 asks that work fan out into independent subsystems and that each lane
return evidence and pass the shared test suite. This file is that archive.

Each lane below owned a disjoint set of files, ran to completion, and was integrated
through one shared gate rather than merged on trust. Verification numbers are the
numbers the lane reported at hand-off; the shared gate was re-run afterwards and is
recorded at the bottom. Where a lane found a defect, the defect is listed, because a
lane that reports only successes is not evidence.

## Shared gate

Every lane had to leave this green:

```
python -m pytest -q
python -m ruff check appian_sentinel tests tools
```

## Wave 0-1: ground truth and code intelligence

### Ground truth loaders (R1, R2)
Owned `appian_sentinel/knowledge/`. Replaced hand-maintained SAIL function lists with
the authoritative allowlist extracted from `sail_lint.py` inside `appian.skill`, merged
with 80 names that appear only in the local corpus, giving 669 callables. Model and
protocol metadata now come from `GenAI Documentation.xlsx` instead of literals.
Defect found: the previous catalog was hand-written and drifted from the shipped skill.

### Icon and enum validation (R10)
Owned icon and enum diagnostics. Added SAIL041 and SAIL042.
Defect found: the icon lists scraped into `appian.skill` are truncated (46 rich-text
aliases, 32 system keys), so treating an unknown icon as an error would reject valid
code. Unknown icons are warnings; near-miss typos remain errors. The incompleteness is
exposed as a flag on the catalog rather than hidden.

### Generator write correctness (R11, R20)
Owned `appian_sentinel/generator/object_writer.py`. Added record type and process model
round trips.
Defect found: the writer swallowed failures instead of propagating them, so a failed
object write could be reported as a success.

## Wave 2: packaging, telemetry, intake

### Package round-trip equivalence (R12, R13, R26)
Owned packaging and the MCP blueprint tools. Full export rebuild now asserts identical
per-type counts, identical UUID and relative-path sets, byte-identical `MANIFEST.MF` and
`META-INF/export.log`, and SHA-256 equality across all 155 document payloads.
Defect found: a zero-change rebuild rewrote `export.log` line endings, which would have
shown up as a spurious diff in every patch.

### Progress telemetry (R30)
Owned the progress contract. Upload, parsing, AI calls, workflow steps, test runs,
packaging, and downloads emit through one reporter rather than ad-hoc log lines.

### Requirement intake and chat transports (R16, R17, R19, R21, R22)
Owned intake and chat tests. Four intake sources normalize to one user-story model;
WebSocket and HTTP fallback chat are both driven; bulk apply proves atomic rollback.
Defect found: the test-generation prompt omitted accessibility tests, so the coverage
matrix could never have been complete.

### CI, runbook, reference gate (R3, R5)
Owned `README.md`, `.github/workflows/ci.yml`, `docs/RUNBOOK.md`, and this requirements
ledger. Established the corpus gate behind `RUN_APPIAN_CORPUS=1`.

## Wave 3: desktop and IDE

### Desktop process shape and installers (R31)
Owned `desktop/electron/` and the build scripts. Ported the supervisor shape: Windows
Job Object with `KILL_ON_JOB_CLOSE`, ownership-ID health handshake, Next standalone
output, and a single `.cmd` installer artifact.
Defects found: the frozen sidecar crashed at startup because web static and template
directories were missing from the PyInstaller bundle; default ports 7842/8888 collided
with an existing Testing Toolkit install and were moved to 7851/8871; the app shipped
with the default Electron icon because no `.ico` was generated.

### Wire IDE to real endpoints (R27, R28, R29)
Owned `desktop/lib/api.js`.
Defect found: the client carried a `MISSING` map asserting that object save, diagnostics,
bulk tests, history, and restore were "not served by this sidecar". Those routes all
existed; the probe paths were wrong, so working features were disabled in the UI. Save
also sent `{source}` where the API expects `{definition}`.

## Honest gaps

These are recorded here rather than smoothed over:

- The reference export is client data and is not committed, so R3, R6, R7, R9, and R12
  are proven locally under `RUN_APPIAN_CORPUS=1` but skipped in CI and on a clean clone.
- No clean-machine installer run has happened. The artifact is hash-verified; the
  installed application has not been driven through the full reference workflow.
- Lane evidence is a written record, not a machine-checked artifact. It is only as
  reliable as the gate re-run below.
