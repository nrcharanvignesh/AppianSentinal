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
    - Status: MET FOR SCALE AND STRUCTURE IN THE DEFAULT SUITE; REAL-EXPORT FIDELITY REMAINS LOCAL-ONLY. The default suite generates a deterministic 300-object, client-free modern-Haul export, reconciles every parsed type and file, exercises a non-flat dependency graph, and proves an equivalent ZIP rebuild. `RUN_APPIAN_CORPUS=1 python -m pytest tests/test_package_equivalence.py tests/parser/test_sail_corpus_regression.py tests/test_codebase_inventory.py tests/test_icon_enum_validation.py -q` remains the fidelity gate for the 2,624-object `./appian_export/`; that client data is deliberately not committed.

4. Fan out work by independent subsystem.
    - Use parallel audits, disjoint implementation lanes, and one integration gate.
    - Acceptance: each lane returns evidence and passes the shared test suite.
    - Status: MET. File-ownership split is recorded in `docs/RUNBOOK.md`; per-lane evidence, including the defect each lane found, is archived in `docs/LANE-EVIDENCE.md`. Every lane was integrated through one shared gate (`python -m pytest -q` plus `ruff check`) rather than merged on trust.

5. Establish repository and verification foundations.
    - Add a safe Git baseline, automated tests, fixtures, linting, and build checks.
    - Acceptance: clean checkout can run all checks with documented commands.
    - Status: MET. Root `README.md` documents the local commands that exited 0 here. The earlier `pip install -e .` break is fixed: `build-backend` is now `setuptools.build_meta` with package discovery scoped to `appian_sentinel*`, and `python -m pip install -e . --no-deps --dry-run` exits 0 ("Would install appian-sentinel-0.1.0"). Per user direction, no CI workflow is committed because this account has no Actions minutes or Git LFS storage. Residual: corpus gates skip without `./appian_export/`; Playwright, PyInstaller, `frozen-sidecar`, desktop boot, renderer authentication, Job Object, and installed-GUI gates are local commands.

## Wave 1: Appian code intelligence

6. Parse an Appian export ZIP into a structured codebase map.
    - Validate ZIP boundaries and stream or bound large-file operations.
    - Acceptance: the reference ZIP parses without data loss or unsafe extraction.
    - Status: MET FOR SYNTHETIC SCALE IN THE DEFAULT SUITE; REAL-EXPORT FIDELITY REMAINS LOCAL-ONLY. `tests/test_zip_handler.py` covers unsafe paths and size bounds. The default synthetic scale gate parses and rebuilds a deterministic 300-object export, while `test_full_export_rebuild_is_equivalent` remains the local-only proof for all 2,784 real-export files under `RUN_APPIAN_CORPUS=1`.

7. Organize every supported object by Appian object type.
    - Include content subtypes, record types, process models, data types, groups,
      sites, APIs, integrations, data stores, translations, and document payloads.
    - Acceptance: parsed totals reconcile with the export inventory.
    - Status: MET FOR SYNTHETIC SCALE IN THE DEFAULT SUITE; REAL-EXPORT FIDELITY REMAINS LOCAL-ONLY. The default 300-object fixture covers all 21 supported parsed object types and reconciles generated and parsed per-type counts. `test_optional_full_reference_inventory_reconciles` remains the local-only real-export check: 652 constants, 615 interfaces, 610 expression rules, 178 process models, 155 documents, 148 record types, and 2,624 objects total. The installed-GUI run reports 2,687 objects for the same application, and the two numbers are not in conflict: `./appian_export/` is an older extraction that the ZIP has since moved past by 89 files, and parsing `Interactions Hub.zip` directly yields exactly the 2,687 the GUI shows.

8. Resolve UUIDs, names, source files, and object references bidirectionally.
    - Acceptance: every indexed object resolves by UUID and name where metadata exists.
    - Status: MET FOR SYNTHETIC SCALE IN THE DEFAULT SUITE; REAL-EXPORT "EVERY OBJECT" REMAINS LOCAL-ONLY. `test_synthetic_scale_every_uuid_and_unique_name_resolves` parses a 300-object generated export, resolves every UUID via `get_object`, and treats duplicate names as `AmbiguousObjectNameError` rather than a guess. Slim unique/ambiguous cases remain in `tests/test_codebase_inventory.py`. `test_optional_full_reference_inventory_reconciles` now also asserts `get_object` for all 2,624 real UUIDs when `./appian_export/` is present.

9. Provide an Appian expression AST and code-intelligence service.
    - Include source ranges, diagnostics, symbols, references, formatting, and safe edits.
    - Acceptance: parser tests cover real SAIL from the reference application.
    - Status: MET FOR SYNTHETIC SCALE IN THE DEFAULT SUITE; REAL-SAIL FIDELITY REMAINS LOCAL-ONLY. The default 300-object scale gate validates every generated interface and expression-rule definition and builds their cross-object references. `tests/parser/test_sail_corpus_regression.py` remains the local-only regression gate for real reference SAIL under `RUN_APPIAN_CORPUS=1`.

10. Validate SAIL against Appian rules and the bundled reference.
    - Reject invented functions, parameters, enum values, icons, UUIDs, invalid
      nesting, invalid operators, and undeclared rule inputs.
    - Acceptance: known-invalid fixtures fail with line and column diagnostics.
    - Status: MET. The official Appian 26.8 documentation tables are bundled as 1,127 standard aliases, 43 indicator keys, and 127 news-event keys. Six deprecated standard aliases observed in the real export remain accepted. Literal keys are validated against the correct namespace and invented keys are errors; dynamic expressions are left to Appian runtime evaluation. `tests/test_icon_enum_validation.py` is the focused gate; the old full-suite count was removed because it no longer describes the current tree.

11. Read and write all required Appian object tiers.
    - Support content objects, record types, process models, and their metadata.
    - Acceptance: object-level round trips preserve untouched XML and payloads.
    - Status: MET. `tests/test_object_writer_roundtrip.py` covers modify on all three tiers with preserve-unrelated-nodes assertions, and create on all three tiers. Defect found and fixed here: an audit showed create was only ever tested on the content tier, and adding create round trips proved the writer emitted record types and process models that the project's own parser could not read back. The writer put `uuid` and `name` in child elements while real exports and `parse_record_type_xml` use attributes, and it omitted the `process_model_port/pm/meta` wrapper and locale string-map name that `parse_process_model_xml` requires. Both create paths now emit the real export shape and are proven by writing, re-running `build_codebase_map`, and resolving the object by UUID, name, and file path.

12. Rebuild the full Appian ZIP in the original archive structure.
    - Acceptance: unzip, analyze, rebuild, and re-analyze produce equivalent inventory.
    - Status: MET FOR SYNTHETIC SCALE IN THE DEFAULT SUITE; REAL-EXPORT FIDELITY REMAINS LOCAL-ONLY. The default gate rebuilds and re-analyzes a deterministic 300-object export with identical type counts, UUIDs, relative paths, metadata bytes, and synthetic document payload hashes. `test_full_export_rebuild_is_equivalent` remains the local-only real-export proof for 2,624 objects, 2,784 files, and all 155 client document payloads. A defect found and fixed here: zero-change rebuilds previously rewrote `export.log` line endings.

13. Build a deployable patch ZIP containing only required changed objects.
    - Include required metadata and explicit dependency warnings or closure.
    - Acceptance: archive contents equal the selected change set and required metadata.
    - Status: MET. `tests/test_packaging_roundtrip.py` and `tests/test_mcp_blueprint_e2e.py::test_analyze_and_generate_patch_blueprint_tools_end_to_end` passed in `python -m pytest -q`.

## Wave 2: Requirements, model service, and generation

14. Configure the model service in the desktop settings.
    - Store secrets outside source control and mask them in responses and logs.
    - Acceptance: settings persist locally and secrets never appear in API output.
    - Status: MET. `tests/test_settings_persistence.py` proves exact non-secret persistence, masked GET/POST responses, and exclusion of `settings.json` from workspace history; `tests/test_secret_logging.py` proves model service and Azure DevOps client credentials never appear in emitted log records.

15. Route models through the documented protocol.
    - Support OpenAI-compatible `/chat/completions` and Anthropic-compatible
      `/v1/messages` according to model and explicit protocol selection.
    - Acceptance: mocked contract tests verify both request and response shapes.
    - Status: MET. `tests/test_llm_protocols.py` passed in `python -m pytest -q`.

16. Accept requirements from typed chat, PDF, Azure DevOps REST, or a configured
    Azure DevOps tool connection.
    - Acceptance: each source produces the same normalized user-story model.
    - Status: PARTIALLY MET. `tests/test_requirement_intake.py` normalizes typed chat,
      a generated PDF, Azure DevOps REST, and an Azure DevOps tool payload into the
      same user-story model. The desktop implements typed chat, PDF/TXT/MD files, and
      Azure DevOps REST. It does not implement a live Azure DevOps tool transport.

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
    - Status: PARTIALLY MET. `tests/test_chat_transports.py` drives WebSocket message
      delivery and the `POST /api/chat` HTTP route. Browser token authentication is
      covered through the `sentinel-token` subprotocol. The renderer does not use the
      HTTP route when the socket is closed, so the acceptance check is not complete.

20. Create and modify required Appian objects across all three tiers.
    - Use existing object identities and real data-model context; never invent UUIDs.
    - Acceptance: generated changes pass validation and object round-trip tests.
    - Status: MET FOR THE THREE REQUIRED TIERS. `tests/test_generated_object_validation.py`
      covers content-tier creation with SAIL validation and parser resolution.
      `tests/test_agent_all_tier_generation.py` drives generation of an interface,
      record type, and process model, then requires all three to resolve by UUID and
      name. `generate_sail` is restricted to interfaces and expression rules because
      record types and process models do not contain SAIL.

21. Generate comprehensive functional, negative, edge, regression, performance, and
    accessibility test cases mapped to every acceptance criterion.
    - Acceptance: the coverage matrix has no uncovered criterion.
    - Status: MET. `tests/test_generated_coverage.py` drives the generator with a
      deterministic model-service response: a complete suite reports full coverage,
      and an incomplete suite reports the exact gaps rather than being accepted.

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
    - Status: MET FOR REGISTRATION AND CONTRACTS. `tests/test_mcp_tool_inventory.py`
      and `tests/test_mcp_generation_tools.py` prove the exact 167-tool set (31
      general plus 136 typed CRUD), non-empty documentation, typed signatures,
      schema/signature parity, model-service configuration rejection, real object
      identity, deterministic generation, and SAIL validation before return.
    - Caveat: registration breadth is not behavioral depth. See requirement 34.

26. Preserve the required MCP blueprint capabilities.
    - Include analyze ZIP, read an Azure DevOps work item, and generate patch ZIP.
    - Acceptance: all three run end to end against fixtures.
    - Status: MET. `tests/test_mcp_blueprint_e2e.py` covers ZIP analysis, patch ZIP
      generation, and a mocked Azure DevOps work item.

27. Provide object browsing for interfaces, constants, rules, record types, process
    models, and every other parsed type.
    - Acceptance: users can open objects from the type tree and inspect metadata and source.
    - Status: MET FOR THE PREVIOUS RENDERER; CURRENT LAYOUT NOT RE-VERIFIED. The
      recorded Playwright run covered grouping, totals, and source panes for multiple
      object tiers. The installed-GUI evidence also predates the current layout.

28. Provide a proper Appian-focused IDE.
    - Include object explorer, tabs, read/edit source, SAIL highlighting, diagnostics,
      symbols, references, dependency views, copy, diff, save, undo, and test panels.
    - Acceptance: keyboard and mouse workflows pass rendered UI tests.
    - Status: MET FOR THE PREVIOUS RENDERER; CURRENT LAYOUT NOT RE-VERIFIED. The
      features remain in code: SAIL highlighting, diagnostics, symbol outline,
      cross-object navigation, dependency lists, and undo/redo. The recorded
      Playwright and screenshot evidence predates the current layout.

29. Match Appian's current design language closely.
    - Use Appian-style information hierarchy, navigation, density, controls, color,
      typography, focus behavior, loading, empty, and error states.
    - Acceptance: rendered desktop views pass the visual acceptance checklist.
    - Status: MET FOR THE PREVIOUS RENDERER; CURRENT LAYOUT NOT RE-VERIFIED.
      `docs/VISUAL-ACCEPTANCE.md` records 40 checks, but those results and the recorded
      Playwright run predate the current center-chat layout.

30. Show progress for upload, parsing, model service calls, all workflow steps, test runs,
    packaging, and downloads.
    - Acceptance: every operation longer than one second reports phase, detail, and result.
    - Status: MET. `tests/test_progress_reporting.py` covers workflow step phases,
      model service phases, deferred live tests, and upload/parse metadata.

31. Ship a standalone Windows Electron and Next.js desktop application with the Python
    backend embedded.
    - Start and stop the engine safely, bind only to loopback, work without a browser,
      and provide full and patch ZIP downloads.
    - Acceptance: a clean-machine installer test completes the full reference workflow.
    - Status: MET FOR THE PREVIOUS INSTALLED BUILD; CURRENT BUILD NOT RE-VERIFIED. The standalone `.cmd` installs under Documents without Python or Node at runtime. The UI binds only to 127.0.0.1:8888 and the embedded engine binds only to 127.0.0.1:7842.
    - Two defects that only the installed GUI exposed, both now fixed and both invisible to the prior suite because every UI test mocked the engine and every API test was same-origin with no token:
        1. `/ws` accepted the token only as an `X-Sentinel-Token` header, which a browser cannot set on a handshake, so the app remained offline and reconnected every 2 seconds. The token now rides the `sentinel-token` subprotocol.
        2. The token middleware rejected the CORS preflight with 401 and no CORS headers, so every cross-origin REST call from the renderer on 8888 to the engine on 7842 died as "Failed to fetch" and the Object Explorer showed "Could not load objects". `OPTIONS` is now exempt; the real request is still gated.
    - `desktop/scripts/prove-renderer-auth.mjs` is the regression gate for both. It runs a real browser on a separate origin against the frozen engine with a token set, and proves the tokened REST call and tokened socket succeed while untokened and wrong-token attempts are refused.
    - `desktop/scripts/prove-installed-gui.mjs` drives the installed `AppianSentinel.exe` through the reference workflow with no mock backend. The recorded run imported the 84.2 MB `Interactions Hub.zip`, showed 2,687 parsed objects, opened an object, rebuilt the full ZIP, and downloaded an 84.1 MB archive. This evidence predates the current renderer layout.
    - Engine process cleanup is covered by `desktop/scripts/prove-job-object.mjs`. The script verifies that Windows Job Object ownership terminates a child process when its owner is killed.
    - Residual risk, stated plainly: this is a real install from the shipped `.cmd` on a machine that has previously built the project, not a freshly imaged Windows box. It proves the installed artifact, not the absence of every possible machine-level prerequisite.

32. Show the chatbot's activity in the open.
    - List every object the chat turn involves and every tool call it makes, in order,
      with arguments, status, and result.
    - Acceptance: a live chat turn that calls tools emits one event per call over both
      WebSocket and HTTP, and the desktop renders them as an ordered timeline.
    - Status: PARTIALLY MET. Free-form chat now uses `chat_with_tools`, invokes the
      model-selected read-only tools, and emits ordered start/result messages with
      arguments, status, timing, and bounded result summaries. `tests/test_llm_tool_protocol.py`
      and `tests/test_chat_tool_loop.py` cover the protocol and loop. The renderer is
      not wired to that event schema: `AssistantPanel` looks for
      `metadata.tool_calls`, while real free-form events store `tool`, `args`, `status`,
      and `result_summary` directly in metadata. No rendered test proves a live tool
      turn over both transports, so the acceptance check remains open.

33. Make the chat resilient when the socket is down.
    - Acceptance: sending with a closed WebSocket either falls back to HTTP with the
      selected object UUIDs intact, or reports the failure.
    - Status: NOT MET. `Workbench.sendMessage` returns silently when the socket is not
      OPEN. `api.chat` exists but is never called and posts `{message}` only, dropping
      `object_uuids`. The desktop also appends a local user bubble and then the server
      echo of the same turn, with no de-duplication.

34. State CRUD depth per object type, not just tool count.
    - Acceptance: a per-type matrix of create, get, update and delete outcomes, produced
      against the real export rather than synthetic fixtures.
    - Status: NOT MET. The registry exposes 34 types and 136 CRUD tools. Typed CRUD is
      configured to create 21 types without a template. Record types and process models
      still use same-type templates in typed CRUD even though native writers exist
      elsewhere. Eleven template-only types have no proven native shape because the
      validation corpus has no matching export sample: AI Agent, AI Skill, Business
      Process, Process Report, Robotic Task, Robot Pool, Dashboard, Control Panel,
      Control Panel Hierarchy Item, Group Type, and Feed.
    - The real-export matrix ran on 2026-09-20 and failed. Data type and record type
      creation returned success but subsequent update/get/delete returned `not_found`.
      Process model and Web API updates completed, but get returned the original name.
      Event Consumer native creation ran even though the reference export has no
      same-type sample, which the matrix rejects as unproven.
    - Document payload staging, rollback, positive `export.log` IDs, and
      `application/*.xml` membership are fixed and covered by
      `tests/test_mutation_transaction.py` and `tests/test_export_metadata.py`.
      `tests/test_typed_crud_real_export.py` remains the authoritative per-type gate and
      currently reports one failed and one passed test.

35. Adopt the reference desktop patterns from the Testing-Toolkit project.
    - Acceptance: streaming chat, a credentials/onboarding path, an activity log and a
      state-driven status bar exist in the renderer.
    - Status: PARTIALLY MET. The renderer has a settings dialog and displays progress
      messages, selected-object context, and an activity area inside chat. It does not
      stream model text, has no first-run credentials or onboarding gate, has no separate
      activity log dock, and its footer remains three simple state values rather than a
      workflow status bar.

## Release gate

"Works flawlessly" means all automated checks pass, rendered UI checks pass, package
round trips pass, and clean-machine installation passes. Live Appian deployment and
execution are reported separately because an offline application cannot prove runtime
behavior inside an Appian environment.

Current standing against that gate: focused backend, parser, mutation, and metadata
checks pass, but the real-export typed CRUD gate fails as described in requirement 34.
The recorded package round trips and
Playwright and 40-item visual acceptance results predate the current center-chat layout.
The current Playwright suite still stubs the engine, so it does not prove a live chat
turn or the real activity-event schema.

The installed-GUI evidence is also stale, for a reason worth recording. The NSIS
force-close script embedded in `desktop/scripts/installer.nsh` had an unbalanced
parenthesis, so PowerShell failed to parse it and killed nothing. The running app kept a
lock on `app.asar`, NSIS reported "Failed to uninstall old application files" and the
install left the previous build in place while the wrapper still exited 0. The
parenthesis is fixed, `tests/test_installer_script.py` parse-checks the rendered script
in both directions, and the install wrapper now compares the installed `app.asar` hash
against the build and fails loudly on a mismatch. Requirements 32 to 35 remain
partially met or open as stated above.

An independent audit of R1-R31 on 2026-09-19 found that several statuses above claimed
more than their evidence proved. Those statuses have been corrected rather than the
evidence restated. The audit also drove three real defects out of hiding, all of which
were invisible to the suite because the UI tests mocked the engine, the API tests ran
same-origin without a token, and object-create was only ever tested on the content tier:
the WebSocket token could not be sent by a browser, the CORS preflight was rejected by
the token middleware, and created record types and process models could not be parsed
back by this project's own parser.

Open limitation:

1. Verification depth is local by design. There is no CI workflow: this account has
   no Actions minutes, so a workflow that runs on every push costs without returning
   anything. A clean clone therefore verifies nothing automatically. The corpus,
   Playwright, PyInstaller, `frozen-sidecar`, desktop boot, renderer authentication, Job Object,
   and installed-GUI gates are all run from this machine.

R10 and R31 are now closed with direct evidence. The remaining limitation is the
deliberate local-only verification policy. "Flawless" still overstates the clean-machine
claim because this machine has previously built the project, as R31 describes.
