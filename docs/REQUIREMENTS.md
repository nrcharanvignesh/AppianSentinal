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
    - Status: MET. Root `README.md` documents commands that exited 0 here; `.github/workflows/ci.yml` runs install, ruff, and pytest. The earlier `pip install -e .` break is fixed: `build-backend` is now `setuptools.build_meta` with package discovery scoped to `appian_sentinel*`, and `python -m pip install -e . --no-deps --dry-run` exits 0 ("Would install appian-sentinel-0.1.0"). Residual: corpus gates still skip without `./appian_export/`.

## Wave 1: Appian code intelligence

6. Parse an Appian export ZIP into a structured codebase map.
    - Validate ZIP boundaries and stream or bound large-file operations.
    - Acceptance: the reference ZIP parses without data loss or unsafe extraction.
    - Status: MET FOR SYNTHETIC SCALE IN CI; REAL-EXPORT FIDELITY REMAINS LOCAL-ONLY. `tests/test_zip_handler.py` covers unsafe paths and size bounds. The default synthetic scale gate parses and rebuilds a deterministic 300-object export, while `test_full_export_rebuild_is_equivalent` remains the local-only proof for all 2,784 real-export files under `RUN_APPIAN_CORPUS=1`.

7. Organize every supported object by Appian object type.
    - Include content subtypes, record types, process models, data types, groups,
      sites, APIs, integrations, data stores, translations, and document payloads.
    - Acceptance: parsed totals reconcile with the export inventory.
    - Status: MET FOR SYNTHETIC SCALE IN CI; REAL-EXPORT FIDELITY REMAINS LOCAL-ONLY. The default 300-object fixture covers all 21 supported parsed object types and reconciles generated and parsed per-type counts. `test_optional_full_reference_inventory_reconciles` remains the local-only real-export check: 652 constants, 615 interfaces, 610 expression rules, 178 process models, 155 documents, 148 record types, and 2,624 objects total.

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
    - Status: MET. `tests/test_object_writer_roundtrip.py` content, record_type, and process_model preserve-unrelated-nodes cases passed in `python -m pytest -q`.

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
    - Status: MET. `tests/test_chat_transports.py` drives both paths: WebSocket streaming via `TestClient.websocket_connect` and the `POST /api/chat` HTTP fallback.

20. Create and modify required Appian objects across all three tiers.
    - Use existing object identities and real data-model context; never invent UUIDs.
    - Acceptance: generated changes pass validation and object round-trip tests.
    - Status: MET. `tests/test_generated_object_validation.py` passed in `python -m pytest -q` (create + SAIL validate + codebase resolve; invalid SAIL rejected before write).

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
    - Status: MET. `npx playwright test` -> 17 passed, and the rendered workbench screenshot shows the typed Object Explorer tree, name/UUID search, and an opened object with Source and Metadata tabs. Caveat: the rendered runs use the deterministic sidecar fixture, so tree behaviour at 2,624-object scale is inferred from the parser tests rather than observed.

28. Provide a proper Appian-focused IDE.
    - Include object explorer, tabs, read/edit source, SAIL highlighting, diagnostics,
      symbols, references, dependency views, copy, diff, save, undo, and test panels.
    - Acceptance: keyboard and mouse workflows pass rendered UI tests.
    - Status: MET. All six code-intelligence features are implemented with no new runtime dependency: SAIL highlighting, inline diagnostic markers with clickable Problems rows, symbol outline, cross-object navigation with an explicit chooser for ambiguous names, inbound/outbound dependency lists, and undo/redo. Verified by `npx playwright test` (12 passed) plus direct screenshot inspection: squiggles land on the invalid `==` operator and a single-quoted string, and the Outline separates Local, Rule input, and Component with line numbers. The highlighter token set is generated from the merged catalog (669 callables), not the 589-name archive subset, so the editor highlights exactly what the validator accepts.

29. Match Appian's current design language closely.
    - Use Appian-style information hierarchy, navigation, density, controls, color,
      typography, focus behavior, loading, empty, and error states.
    - Acceptance: rendered desktop views pass the visual acceptance checklist.
    - Status: MET. `docs/VISUAL-ACCEPTANCE.md` grades 40 binary items across information hierarchy, navigation, density, controls, color, typography, focus behavior, loading, empty, and error states. MUI dark mode is the default, light mode persists across reloads, and both use the supplied product icon. `npx playwright test` passed 17 tests, including both rendered themes, visible 2-pixel focus outlines, primary-action tab order, intended state copy, no console errors, no horizontal overflow, and ASCII-only text.

30. Show progress for upload, parsing, AI calls, all workflow steps, test runs,
    packaging, and downloads.
    - Acceptance: every operation longer than one second reports phase, detail, and result.
    - Status: MET. `tests/test_progress_reporting.py` passed in `python -m pytest -q` (workflow step phases, LLM phase, deferred live tests, upload/parse metadata).

31. Ship a standalone Windows Electron and Next.js desktop application with the Python
    backend embedded.
    - Start and stop the sidecar safely, bind only to loopback, work without a browser,
      and provide full and patch ZIP downloads.
    - Acceptance: a clean-machine installer test completes the full reference workflow.
    - Status: PARTIAL. Installer `.cmd` built. Documents install exists. `prove_desktop_boot.py` against that `AppianSentinel.exe` returned health 200 on 7842 and UI bound on 8888 (`boot_exit=0`). Frozen sidecar pytest covers upload, package, download. STILL NOT MET: clean-machine GUI of the full ZIP import/rebuild workflow.

## Release gate

"Works flawlessly" means all automated checks pass, rendered UI checks pass, package
round trips pass, and clean-machine installation passes. Live Appian deployment and
execution are reported separately because an offline application cannot prove runtime
behavior inside an Appian environment.

Current standing against that gate: automated checks pass and package round trips pass,
including the full 2,624-object rebuild. Rendered UI checks (R27, R28, R29) now have a
green 17-test run and a 40-item visual acceptance pass. One condition remains unmet:
clean-machine installation (R31) has a hash-verified artifact
but no install on a machine without the development toolchain, so the full reference
workflow has never been driven through the installed application. Until that clears,
this application is not "flawless" and should not be described as such.
