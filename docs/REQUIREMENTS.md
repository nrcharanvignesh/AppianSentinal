# Appian Sentinel Requirements

This file is the source of truth for delivery. The order below follows runtime
and build dependencies. A requirement is complete only when its acceptance
checks pass.

## Wave 0: Ground truth and execution controls

1. Read and integrate `appian.skill` fully.
   - Use its SAIL syntax, schema, icon, structural, and anti-invention rules.
   - Acceptance: generated SAIL passes schema, icon, AST, and structural checks.

2. Read and integrate `GenAI Documentation.xlsx`.
   - Use documented proxy endpoints, request formats, model names, and limits.
   - Acceptance: contract tests cover OpenAI chat and Anthropic messages paths.

3. Analyze `Interactions Hub.zip` as the reference Appian export.
   - Cover every archive directory, object type, metadata file, and payload form.
   - Acceptance: inventory counts and round-trip package checks are reproducible.

4. Fan out work by independent subsystem.
   - Use parallel audits, disjoint implementation lanes, and one integration gate.
   - Acceptance: each lane returns evidence and passes the shared test suite.

5. Establish repository and verification foundations.
   - Add a safe Git baseline, automated tests, fixtures, linting, and build checks.
   - Acceptance: clean checkout can run all checks with documented commands.

## Wave 1: Appian code intelligence

6. Parse an Appian export ZIP into a structured codebase map.
   - Validate ZIP boundaries and stream or bound large-file operations.
   - Acceptance: the reference ZIP parses without data loss or unsafe extraction.

7. Organize every supported object by Appian object type.
   - Include content subtypes, record types, process models, data types, groups,
     sites, APIs, integrations, data stores, translations, and document payloads.
   - Acceptance: parsed totals reconcile with the export inventory.

8. Resolve UUIDs, names, source files, and object references bidirectionally.
   - Acceptance: every indexed object resolves by UUID and name where metadata exists.

9. Provide an Appian expression AST and code-intelligence service.
   - Include source ranges, diagnostics, symbols, references, formatting, and safe edits.
   - Acceptance: parser tests cover real SAIL from the reference application.

10. Validate SAIL against Appian rules and the bundled reference.
    - Reject invented functions, parameters, enum values, icons, UUIDs, invalid
      nesting, invalid operators, and undeclared rule inputs.
    - Acceptance: known-invalid fixtures fail with line and column diagnostics.

11. Read and write all required Appian object tiers.
    - Support content objects, record types, process models, and their metadata.
    - Acceptance: object-level round trips preserve untouched XML and payloads.

12. Rebuild the full Appian ZIP in the original archive structure.
    - Acceptance: unzip, analyze, rebuild, and re-analyze produce equivalent inventory.

13. Build a deployable patch ZIP containing only required changed objects.
    - Include required metadata and explicit dependency warnings or closure.
    - Acceptance: archive contents equal the selected change set and required metadata.

## Wave 2: Requirements, AI, and generation

14. Configure the firm LiteLLM proxy in the desktop settings.
    - Store secrets outside source control and mask them in responses and logs.
    - Acceptance: settings persist locally and secrets never appear in API output.

15. Route models through the documented protocol.
    - Support OpenAI-compatible `/chat/completions` and Anthropic-compatible
      `/v1/messages` according to model and explicit protocol selection.
    - Acceptance: mocked contract tests verify both request and response shapes.

16. Accept requirements from typed chat, PDF, ADO PAT/REST, or configured ADO MCP.
    - Acceptance: each source produces the same normalized user-story model.

17. Extract description and acceptance criteria without losing source traceability.
    - Acceptance: normalized criteria retain source IDs and original text.

18. Ask focused clarification questions before inventing missing Appian identifiers,
    data-model fields, relationships, intent, or business rules.
    - Acceptance: ambiguous fixtures stop before generation and list blocking questions.

19. Provide the central streaming chatbot.
    - Preserve session state, reconnect safely, and show actionable failures.
    - Acceptance: chat works through WebSocket and HTTP fallback.

20. Create and modify required Appian objects across all three tiers.
    - Use existing object identities and real data-model context; never invent UUIDs.
    - Acceptance: generated changes pass validation and object round-trip tests.

21. Generate comprehensive functional, negative, edge, regression, performance, and
    accessibility test cases mapped to every acceptance criterion.
    - Acceptance: the coverage matrix has no uncovered criterion.

22. Bulk-add selected test cases to interfaces and expression rules.
    - Provide preview, validation, selection, apply, and rollback.
    - Acceptance: bulk operation is atomic and produces a reviewable diff.

23. Run the agent loop until every acceptance criterion and executable test passes.
    - Distinguish static validation from tests that require a live Appian environment.
    - Acceptance: failures trigger bounded fixes; unresolved external tests remain blocked,
      never falsely reported as passed.

## Wave 3: Workspace, MCP, and desktop IDE

24. Track generated changes with Git-like workspace history.
    - Show baseline, staged changes, object diffs, commits/snapshots, and rollback.
    - Acceptance: every mutation records actor, requirement, timestamp, and before/after.

25. Expose an exhaustive specialized Appian MCP server.
    - Cover workspace lifecycle, analysis, search, objects, code intelligence,
      dependencies, requirements, validation, generation, tests, changes, and packaging.
    - Acceptance: tool schemas are complete, typed, documented, and contract-tested.

26. Preserve the required MCP blueprint capabilities.
    - Include analyze ZIP, read ADO work item, and generate patch ZIP.
    - Acceptance: all three run end to end against fixtures.

27. Provide object browsing for interfaces, constants, rules, record types, process
    models, and every other parsed type.
    - Acceptance: users can open objects from the type tree and inspect metadata and source.

28. Provide a proper Appian-focused IDE.
    - Include object explorer, tabs, read/edit source, SAIL highlighting, diagnostics,
      symbols, references, dependency views, copy, diff, save, undo, and test panels.
    - Acceptance: keyboard and mouse workflows pass rendered UI tests.

29. Match Appian's current design language closely.
    - Use Appian-style information hierarchy, navigation, density, controls, color,
      typography, focus behavior, loading, empty, and error states.
    - Acceptance: rendered desktop views pass the visual acceptance checklist.

30. Show progress for upload, parsing, AI calls, all workflow steps, test runs,
    packaging, and downloads.
    - Acceptance: every operation longer than one second reports phase, detail, and result.

31. Ship a standalone Windows Electron and Next.js desktop application with the Python
    backend embedded.
    - Start and stop the sidecar safely, bind only to loopback, work without a browser,
      and provide full and patch ZIP downloads.
    - Acceptance: a clean-machine installer test completes the full reference workflow.

## Release gate

"Works flawlessly" means all automated checks pass, rendered UI checks pass, package
round trips pass, and clean-machine installation passes. Live Appian deployment and
execution are reported separately because an offline application cannot prove runtime
behavior inside an Appian environment.
