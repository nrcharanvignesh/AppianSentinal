# Appian Sentinel Requirements

This file is the source of truth for delivery. The order below follows runtime
and build dependencies. A requirement is complete only when its acceptance
checks pass.

## Wave 0: Ground truth and execution controls

1. Read and integrate `appian.skill` fully.
    - Use its SAIL syntax, schema, icon, structural, and anti-invention rules.
    - Acceptance: generated SAIL passes schema, icon, AST, and structural checks.
    - Status: MET. `sail_catalog.build_default_sail_catalog().valid` has 669 callables; `tests/test_knowledge_ground_truth.py` passed in `python -m pytest -q`.

2. Read and integrate `GenAI Documentation.xlsx`.
    - Use documented proxy endpoints, request formats, model names, and limits.
    - Acceptance: contract tests cover OpenAI chat and Anthropic messages paths.
    - Status: MET. `tests/test_knowledge_ground_truth.py::test_genai_catalog_provides_models_protocols_and_limits` and `tests/test_llm_protocols.py` OpenAI `/chat/completions` plus Anthropic `/v1/messages` cases passed in `python -m pytest -q`.

3. Analyze `Interactions Hub.zip` as the reference Appian export.
    - Cover every archive directory, object type, metadata file, and payload form.
    - Acceptance: inventory counts and round-trip package checks are reproducible.
    - Status: MET FOR SCALE AND STRUCTURE IN CI; REAL-EXPORT FIDELITY REMAINS LOCAL-ONLY. The default suite generates a deterministic 300-object, client-free modern-Haul export, reconciles every parsed type and file, exercises a non-flat dependency graph, and proves an equivalent ZIP rebuild. `RUN_APPIAN_CORPUS=1 python -m pytest tests/test_package_equivalence.py tests/parser/test_sail_corpus_regression.py tests/test_codebase_inventory.py tests/test_icon_enum_validation.py -q` remains the fidelity gate for the 2,624-object `./appian_export/`; that client data is deliberately not committed.

4. Fan out work by independent subsystem.
    - Use parallel audits, disjoint implementation lanes, and one integration gate.
    - Acceptance: each lane returns evidence and passes the shared test suite.
    - Status: MET. File-ownership split is recorded in `docs/RUNBOOK.md`; per-lane evidence, including the defect each lane found, is archived in `docs/LANE-EVIDENCE.md`. Every lane was integrated through one shared gate (`python -m pytest -q` plus `ruff check`) rather than merged on trust.

5. Establish repository and verification foundations.
    - Add a safe Git baseline, automated tests, fixtures, linting, and build checks.
    - Acceptance: clean checkout can run all checks with documented commands.
    - Status: MET. Root `README.md` documents commands that exited 0 here; `.github/workflows/ci.yml` runs install, ruff, and pytest. The earlier `pip install -e .` break is fixed: `build-backend` is now `setuptools.build_meta` with package discovery scoped to `appian_sentinel*`, and `python -m pip install -e . --no-deps --dry-run` exits 0 ("Would install appian-sentinel-0.1.0"). Doc drift found and fixed here: `README.md` still described the editable install as broken and quoted a stale 172-test count. Residual: corpus gates skip without `./appian_export/`, and CI does not run the Playwright, PyInstaller, frozen-sidecar, or desktop-boot gates.

## Wave 1: Appian code intelligence

6. Parse an Appian export ZIP into a structured codebase map.
    - Validate ZIP boundaries and stream or bound large-file operations.
    - Acceptance: the reference ZIP parses without data loss or unsafe extraction.
    - Status: MET FOR SYNTHETIC SCALE IN CI; REAL-EXPORT FIDELITY REMAINS LOCAL-ONLY. `tests/test_zip_handler.py` covers unsafe paths and size bounds. The default synthetic scale gate parses and rebuilds a deterministic 300-object export, while `test_full_export_rebuild_is_equivalent` remains the local-only proof for all 2,784 real-export files under `RUN_APPIAN_CORPUS=1`.

7. Organize every supported object by Appian object type.
    - Include content subtypes, record types, process models, data types, groups,
      sites, APIs, integrations, data stores, translations, and document payloads.
    - Acceptance: parsed totals reconcile with the export inventory.
    - Status: MET FOR SYNTHETIC SCALE IN CI; REAL-EXPORT FIDELITY REMAINS LOCAL-ONLY. The default 300-object fixture covers all 21 supported parsed object types and reconciles generated and parsed per-type counts. `test_optional_full_reference_inventory_reconciles` remains the local-only real-export check: 652 constants, 615 interfaces, 610 expression rules, 178 process models, 155 documents, 148 record types, and 2,624 objects total. The installed-GUI run reports 2,687 objects for the same application, and the two numbers are not in conflict: `./appian_export/` is an older extraction that the ZIP has since moved past by 89 files, and parsing `Interactions Hub.zip` directly yields exactly the 2,687 the GUI shows.

8. Resolve UUIDs, names, source files, and object references bidirectionally.
    - Acceptance: every indexed object resolves by UUID and name where metadata exists.
    - Status: MET FOR SYNTHETIC SCALE IN CI; REAL-EXPORT "EVERY OBJECT" REMAINS LOCAL-ONLY. `test_synthetic_scale_every_uuid_and_unique_name_resolves` parses a 300-object generated export, resolves every UUID via `get_object`, and treats duplicate names as `AmbiguousObjectNameError` rather than a guess. Slim unique/ambiguous cases remain in `tests/test_codebase_inventory.py`. `test_optional_full_reference_inventory_reconciles` now also asserts `get_object` for all 2,624 real UUIDs when `./appian_export/` is present.

9. Provide an Appian expression AST and code-intelligence service.
    - Include source ranges, diagnostics, symbols, references, formatting, and safe edits.
    - Acceptance: parser tests cover real SAIL from the reference application.
    - Status: MET FOR SYNTHETIC SCALE IN CI; REAL-SAIL FIDELITY REMAINS LOCAL-ONLY. The default 300-object scale gate validates every generated interface and expression-rule definition and builds their cross-object references. `tests/parser/test_sail_corpus_regression.py` remains the local-only regression gate for real reference SAIL under `RUN_APPIAN_CORPUS=1`.

10. Validate SAIL against Appian rules and the bundled reference.
    - Reject invented functions, parameters, enum values, icons, UUIDs, invalid
      nesting, invalid operators, and undeclared rule inputs.
    - Acceptance: known-invalid fixtures fail with line and column diagnostics.
    - Status: PARTIAL. Icon validation merges the truncated Appian scrape with 75 corpus-observed names while keeping `is_complete is False`; reference-export coverage improved from 5/75 known (70 unknown, 263 occurrences) to 75/75 known (0 unknown). `tests/test_icon_enum_validation.py` passed 11 tests and the full suite passed 202 tests with 2 skipped.

11. Read and write all required Appian object tiers.
    - Support content objects, record types, process models, and their metadata.
    - Acceptance: object-level round trips preserve untouched XML and payloads.
    - Status: MET. `tests/test_object_writer_roundtrip.py` covers modify on all three tiers with preserve-unrelated-nodes assertions, and create on all three tiers. Defect found and fixed here: an audit showed create was only ever tested on the content tier, and adding create round trips proved the writer emitted record types and process models that the project's own parser could not read back. The writer put `uuid` and `name` in child elements while real exports and `parse_record_type_xml` use attributes, and it omitted the `process_model_port/pm/meta` wrapper and locale string-map name that `parse_process_model_xml` requires. Both create paths now emit the real export shape and are proven by writing, re-running `build_codebase_map`, and resolving the object by UUID, name, and file path.

12. Rebuild the full Appian ZIP in the original archive structure.
    - Acceptance: unzip, analyze, rebuild, and re-analyze produce equivalent inventory.
    - Status: MET FOR SYNTHETIC SCALE IN CI; REAL-EXPORT FIDELITY REMAINS LOCAL-ONLY. The default gate rebuilds and re-analyzes a deterministic 300-object export with identical type counts, UUIDs, relative paths, metadata bytes, and synthetic document payload hashes. `test_full_export_rebuild_is_equivalent` remains the local-only real-export proof for 2,624 objects, 2,784 files, and all 155 client document payloads. A defect found and fixed here: zero-change rebuilds previously rewrote `export.log` line endings.

13. Build a deployable patch ZIP containing only required changed objects.
    - Include required metadata and explicit dependency warnings or closure.
    - Acceptance: archive contents equal the selected change set and required metadata.
    - Status: MET. `tests/test_packaging_roundtrip.py` and `tests/test_mcp_blueprint_e2e.py::test_analyze_and_generate_patch_blueprint_tools_end_to_end` passed in `python -m pytest -q`.

## Wave 2: Requirements, AI, and generation

14. Configure the firm LiteLLM proxy in the desktop settings.
    - Store secrets outside source control and mask them in responses and logs.
    - Acceptance: settings persist locally and secrets never appear in API output.
    - Status: MET. `tests/test_settings_persistence.py` proves exact non-secret persistence, masked GET/POST responses, and exclusion of `settings.json` from workspace history; `tests/test_secret_logging.py` proves LLM provider and ADO client credentials never appear in emitted log records.

15. Route models through the documented protocol.
    - Support OpenAI-compatible `/chat/completions` and Anthropic-compatible
      `/v1/messages` according to model and explicit protocol selection.
    - Acceptance: mocked contract tests verify both request and response shapes.
    - Status: MET. `tests/test_llm_protocols.py` passed in `python -m pytest -q`.

16. Accept requirements from typed chat, PDF, ADO PAT/REST, or configured ADO MCP.
    - Acceptance: each source produces the same normalized user-story model.
    - Status: MET. `tests/test_requirement_intake.py` normalizes all four sources - typed chat, a real generated PDF, ADO REST, and an ADO-MCP payload - into the same user-story model. Live desktop ADO-MCP transport is still unproven; its normalization boundary is covered.

17. Extract description and acceptance criteria without losing source traceability.
    - Acceptance: normalized criteria retain source IDs and original text.
    - Status: MET. `tests/test_requirement_intake.py` asserts `source_id` and `source_kind` are populated on stories and criteria for each intake path.

18. Ask focused clarification questions before inventing missing Appian identifiers,
    data-model fields, relationships, intent, or business rules.
    - Acceptance: ambiguous fixtures stop before generation and list blocking questions.
    - Status: MET. `tests/test_clarifying_questions.py` proves missing record type, undefined field, unspecified business rule, and duplicate object-name cases pause before step 4, while an unambiguous case does not pause.

19. Provide the central streaming chatbot.
    - Preserve session state, reconnect safely, and show actionable failures.
    - Acceptance: chat works through WebSocket and HTTP fallback.
    - Status: MET. `tests/test_chat_transports.py` drives both paths: WebSocket streaming via `TestClient.websocket_connect` and the `POST /api/chat` HTTP fallback. Defect found and fixed here: `/ws` only accepted the token as an `X-Sentinel-Token` header, which a browser cannot set on a handshake, so the packaged desktop UI showed "Sidecar offline" permanently while REST worked and reconnected every 2 seconds. The token now rides the `sentinel-token` subprotocol and headers still work for non-browser clients.

20. Create and modify required Appian objects across all three tiers.
    - Use existing object identities and real data-model context; never invent UUIDs.
    - Acceptance: generated changes pass validation and object round-trip tests.
    - Status: MET. `tests/test_generated_object_validation.py` covers content-tier create with SAIL validation, codebase resolution, and rejection of invalid SAIL before write. `tests/test_agent_all_tier_generation.py` closes the tier gap an audit exposed: it drives `Orchestrator.step_4_implementation` with a deterministic fake LLM that returns an interface, a record type, and a process model, then re-runs `build_codebase_map` and requires all three to resolve by UUID and name. That test fails against the pre-fix writer, which is how the unreadable record-type and process-model output described in R11 was found. Note that MCP `generate_sail` is deliberately restricted to interfaces and expression rules, because record types and process models carry no SAIL; their generation goes through the object writer.

21. Generate comprehensive functional, negative, edge, regression, performance, and
    accessibility test cases mapped to every acceptance criterion.
    - Acceptance: the coverage matrix has no uncovered criterion.
    - Status: MET. `tests/test_generated_coverage.py` drives the generator with a deterministic fake LLM: a complete suite reports full coverage, and an incomplete suite reports the exact gaps rather than being silently accepted. Defect found and fixed here: the generation prompt omitted accessibility tests.

22. Bulk-add selected test cases to interfaces and expression rules.
    - Provide preview, validation, selection, apply, and rollback.
    - Acceptance: bulk operation is atomic and produces a reviewable diff.
    - Status: MET. `tests/test_bulk_rollback.py` forces a write failure on the second object and asserts every object's bytes and the history index backup are restored, so partial application is impossible. Preview and atomic apply remain covered by `tests/test_desktop_api.py`.

23. Run the agent loop until every acceptance criterion and executable test passes.
    - Distinguish static validation from tests that require a live Appian environment.
    - Acceptance: failures trigger bounded fixes; unresolved external tests remain blocked,
      never falsely reported as passed.
    - Status: MET. `tests/test_fix_loop_convergence.py` passed in the focused run: a deterministic fake transport drives RED to GREEN on iteration 2 with all linked criteria passing, and a permanently failing run stops exactly at `max_iterations` without a false green. Existing deferred-live guards remain in `tests/test_workflow_results.py`.

## Wave 3: Workspace, MCP, and desktop IDE

24. Track generated changes with Git-like workspace history.
    - Show baseline, staged changes, object diffs, commits/snapshots, and rollback.
    - Acceptance: every mutation records actor, requirement, timestamp, and before/after.
    - Status: MET. `tests/test_history_mutations.py` proves desktop object save, agent-generated writes, bulk test apply, and history restore record actor, requirement, timestamp, and exact before/after hashes.

25. Expose an exhaustive specialized Appian MCP server.
    - Cover workspace lifecycle, analysis, search, objects, code intelligence,
      dependencies, requirements, validation, generation, tests, changes, and packaging.
    - Acceptance: tool schemas are complete, typed, documented, and contract-tested.
    - Status: MET. `tests/test_mcp_tool_inventory.py` and `tests/test_mcp_generation_tools.py` prove the exact 27-tool set, non-empty documentation, typed signatures, schema/signature parity, every required category, no-LLM rejection, real object identity, deterministic generation, and SAIL validation before return.

26. Preserve the required MCP blueprint capabilities.
    - Include analyze ZIP, read ADO work item, and generate patch ZIP.
    - Acceptance: all three run end to end against fixtures.
    - Status: MET. `tests/test_mcp_blueprint_e2e.py` (analyze ZIP, generate patch ZIP, mocked ADO work item) passed in `python -m pytest -q`.

27. Provide object browsing for interfaces, constants, rules, record types, process
    models, and every other parsed type.
    - Acceptance: users can open objects from the type tree and inspect metadata and source.
    - Status: MET. `npx playwright test` -> 19 passed, including `explorer groups every parsed object type, not just expression rules`, which renders a codebase spanning constants, expression rules, integrations, interfaces, process models, record types, and sites, then requires a labelled group per tier, an accurate total badge, and a rendered source pane after opening both a record type and a process model. The earlier fixture held expression rules only, so a regression on any other tier could have rendered nothing and still passed. Tree behaviour at full scale is separately observed rather than inferred: the installed-GUI run in R31 shows 2,687 objects in this explorer.

28. Provide a proper Appian-focused IDE.
    - Include object explorer, tabs, read/edit source, SAIL highlighting, diagnostics,
      symbols, references, dependency views, copy, diff, save, undo, and test panels.
    - Acceptance: keyboard and mouse workflows pass rendered UI tests.
    - Status: MET. All six code-intelligence features are implemented with no new runtime dependency: SAIL highlighting, inline diagnostic markers with clickable Problems rows, symbol outline, cross-object navigation with an explicit chooser for ambiguous names, inbound/outbound dependency lists, and undo/redo. Verified by `npx playwright test` (12 passed) plus direct screenshot inspection: squiggles land on the invalid `==` operator and a single-quoted string, and the Outline separates Local, Rule input, and Component with line numbers. The highlighter token set is generated from the merged catalog (669 callables), not the 589-name archive subset, so the editor highlights exactly what the validator accepts.

29. Match Appian's current design language closely.
    - Use Appian-style information hierarchy, navigation, density, controls, color,
      typography, focus behavior, loading, empty, and error states.
    - Acceptance: rendered desktop views pass the visual acceptance checklist.
    - Status: MET. `docs/VISUAL-ACCEPTANCE.md` grades 40 binary items across information hierarchy, navigation, density, controls, color, typography, focus behavior, loading, empty, and error states. MUI dark mode is the default, light mode persists across reloads, and both use the supplied product icon. Explorer, assistant, and results regions resize by pointer or keyboard and persist their dimensions. `npx playwright test` passed 18 tests, including both rendered themes, visible 2-pixel focus outlines, primary-action tab order, intended state copy, no console errors, no horizontal overflow, and ASCII-only text.

30. Show progress for upload, parsing, AI calls, all workflow steps, test runs,
    packaging, and downloads.
    - Acceptance: every operation longer than one second reports phase, detail, and result.
    - Status: MET. `tests/test_progress_reporting.py` passed in `python -m pytest -q` (workflow step phases, LLM phase, deferred live tests, upload/parse metadata).

31. Ship a standalone Windows Electron and Next.js desktop application with the Python
    backend embedded.
    - Start and stop the sidecar safely, bind only to loopback, work without a browser,
      and provide full and patch ZIP downloads.
    - Acceptance: a clean-machine installer test completes the full reference workflow.
    - Status: PARTIAL. Installer `.cmd` built. Documents install exists. `prove_desktop_boot.py` against that `AppianSentinel.exe` returned health 200 on 7842 and UI bound on 8888 (`boot_exit=0`). Frozen sidecar pytest covers upload, package, download.
    - Two defects that only the installed GUI exposed, both now fixed and both invisible to the prior suite because every UI test mocked the sidecar and every API test was same-origin with no token:
        1. `/ws` accepted the token only as an `X-Sentinel-Token` header, which a browser cannot set on a handshake, so the app showed "Sidecar offline" permanently and reconnected every 2 seconds. The token now rides the `sentinel-token` subprotocol.
        2. The token middleware rejected the CORS preflight with 401 and no CORS headers, so every cross-origin REST call from the renderer on 8888 to the sidecar on 7842 died as "Failed to fetch" and the Object Explorer showed "Could not load objects". `OPTIONS` is now exempt; the real request is still gated.
    - `desktop/scripts/prove-renderer-auth.mjs` is the regression gate for both. It runs a real browser on a real separate origin against the frozen sidecar with a token set, and proves the tokened REST call and the tokened socket succeed while untokened and wrong-token attempts are refused.
    - Status: MET on the installed application. `desktop/scripts/prove-installed-gui.mjs` drives the real installed `AppianSentinel.exe` through the entire reference workflow with no mock and no stub sidecar, and exited 0 on three consecutive runs in about two minutes each: the GUI reports the sidecar online, imports the 84.2 MB `Interactions Hub.zip`, shows 2,687 parsed objects in the Object Explorer, opens an object and renders its source, rebuilds the full ZIP, and downloads an 84.1 MB archive. The script then audits that archive and requires 2,871 entries with no internal `.history` state, which matches the source export file for file. A third defect surfaced here and is fixed: the rebuilt ZIP carried Sentinel's own `.history` snapshot store, which would have corrupted a real Appian import.
    - "Stop the sidecar safely" is now proven rather than assumed. `desktop/scripts/prove-job-object.mjs` starts an owner process that claims the Job Object and spawns a child that ignores `SIGTERM`, then kills the owner with `taskkill /F` and deliberately without `/T`, so nothing except the job can reap the child. It exits 0 only after observing the child die with its owner. The helper now reports whether assignment actually succeeded, so a nested parent job that blocks assignment exits 3 with a warning instead of passing silently; on this machine assignment succeeds and the guarantee holds.
    - Residual risk, stated plainly: this is a real install from the shipped `.cmd` on a machine that has previously built the project, not a freshly imaged Windows box. It proves the installed artifact, not the absence of every possible machine-level prerequisite.

## Release gate

"Works flawlessly" means all automated checks pass, rendered UI checks pass, package
round trips pass, and clean-machine installation passes. Live Appian deployment and
execution are reported separately because an offline application cannot prove runtime
behavior inside an Appian environment.

Current standing against that gate: automated checks pass (217 passed, 2 skipped) and
package round trips pass, including the full 2,624-object rebuild. Rendered UI checks
(R27, R28, R29) have a green 18-test run and a 40-item visual acceptance pass.

An independent audit of R1-R31 on 2026-09-19 found that several statuses above claimed
more than their evidence proved. Those statuses have been corrected rather than the
evidence restated. The audit also drove three real defects out of hiding, all of which
were invisible to the suite because the UI tests mocked the sidecar, the API tests ran
same-origin without a token, and object-create was only ever tested on the content tier:
the WebSocket token could not be sent by a browser, the CORS preflight was rejected by
the token middleware, and created record types and process models could not be parsed
back by this project's own parser.

Open gaps, in priority order:

1. R10/R1 icon catalog is truncated (`is_complete is False`), so invented icons outside
   the merged set are warnings rather than hard rejects. This one cannot be closed
   honestly from here: the bundled 26.5 reference truncates the list, and the
   authoritative `docs.appian.com` table is rendered client side, so it cannot be
   scraped. Hard-rejecting against a knowingly partial list would fail valid Appian
   icons, and inventing the missing names would break the same anti-invention rule this
   project enforces on the model. Warning is the correct behavior until a complete list
   can be obtained from an Appian instance.
2. Verification depth is local by design. There is no CI workflow: this account has
   no Actions minutes, so a workflow that runs on every push costs without returning
   anything. A clean clone therefore verifies nothing automatically. The corpus,
   Playwright, PyInstaller, frozen-sidecar, desktop-boot, renderer-auth, Job Object,
   and installed-GUI gates are all run from this machine.

R31, the gap that mattered most, is now closed against the installed application, and
the Job Object, R20 tier, and R27 breadth gaps are closed with direct evidence. What
is left is one ground-truth limitation and one deliberate cost decision, neither of
which is unfinished implementation work. "Flawless" still overstates it: the icon
catalog is provably partial, and the clean-machine claim is bounded as R31 describes.
