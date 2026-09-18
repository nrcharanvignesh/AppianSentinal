# R29 Visual Acceptance Checklist

## Scope and grading method

This checklist grades the desktop workbench against Appian 26.2 SAIL design
principles and the visual conventions of Appian Designer. The reference basis is:

- [SAIL Design System](https://docs.appian.com/suite/help/26.2/sail/sail-design.html)
- [Appian Designer introduction](https://docs.appian.com/suite/help/26.2/introduction-to-application-building.html)
- [Appian navigation and tabs patterns](https://docs.appian.com/suite/help/26.2/SAIL_Pallet_Patterns.html)
- [Appian indicator icon guidance](https://docs.appian.com/suite/help/26.2/ux_indicator_icons.html)

Each item is binary. PASS means that the cited rendered image shows the result,
or that the cited Playwright assertion proves behavior that a still image cannot
prove. A missing required image or assertion is a FAIL. Browser developer chrome
and test-runner overlays count as a visual failure.

Graded evidence:

- `desktop/test-results/workbench-loaded-1440x900.png`
- `desktop/test-results/workbench-loaded-1024x640.png`
- `desktop/test-results/workbench-empty-1440x900.png`
- `desktop/test-results/workbench-loading-1440x900.png`
- `desktop/test-results/workbench-error-1440x900.png`
- `desktop/tests/workbench.spec.js`

## Final grade: 40 of 40 PASS

### Information hierarchy - 4 of 4

- [x] IH1 PASS - The application bar is the highest-contrast horizontal region and contains product, application, connection, status, and import information.
- [x] IH2 PASS - The explorer, editor, results panel, and assistant are visually distinct regions with persistent borders or surface changes.
- [x] IH3 PASS - The open object name and UUID appear above source content, while object type and actions remain secondary.
- [x] IH4 PASS - Screenshots contain only product and workspace chrome; no framework development badge or test overlay is visible.

### Navigation - 4 of 4

- [x] N1 PASS - The selected explorer object has a blue left marker and a distinct selected background.
- [x] N2 PASS - The active object tab, object-view tab, result tab, and assistant tab each have one blue active indicator.
- [x] N3 PASS - Tab labels remain visible without page-level horizontal overflow at both graded viewport sizes.
- [x] N4 PASS - Object groups expose expansion state, objects expose selection state, and result and assistant controls use tab roles in Playwright.

### Density - 4 of 4

- [x] D1 PASS - Explorer rows are compact and consistently spaced, with names truncated instead of overlapping adjacent regions.
- [x] D2 PASS - Toolbars keep labels and actions on one row at 1024x640 and 1440x900.
- [x] D3 PASS - The results panel gives diagnostics a compact row format without excessive card padding.
- [x] D4 PASS - The 1024x640 view retains usable explorer, editor, outline, results, and assistant regions with no page-level horizontal overflow.

### Controls - 4 of 4

- [x] C1 PASS - Import and Save use a primary treatment; Copy source and secondary operations use a lower-emphasis treatment.
- [x] C2 PASS - Disabled Save and Send controls are visibly muted and are asserted disabled by Playwright where their prerequisites are absent.
- [x] C3 PASS - Search, text areas, tabs, tree rows, and buttons have visible boundaries or interaction affordances appropriate to their role.
- [x] C4 PASS - Diagnostic severity is not encoded by color alone: the Problems row includes `ERROR`, a code, a message, and a line number.

### Color - 4 of 4

- [x] CL1 PASS - Navy and Appian blue identify the application bar, active navigation, primary controls, and status bar.
- [x] CL2 PASS - Main content uses white and light-gray surfaces with dark text; no large saturated content background competes with the editor.
- [x] CL3 PASS - Error red is limited to errors and invalid source, while blue indicates selection, action, or progress.
- [x] CL4 PASS - Offline status is red in both the application bar indicator and assistant heading; it is not shown in success green.

### Typography - 4 of 4

- [x] T1 PASS - UI text uses Segoe UI or its declared sans-serif fallback, and source, UUID, diagnostics, and status data use a monospace face.
- [x] T2 PASS - Product, pane title, object title, labels, and metadata have visibly descending size or weight.
- [x] T3 PASS - Uppercase text is limited to short labels such as DESIGN OBJECTS, OUTLINE, object type, and severity.
- [x] T4 PASS - Text does not overlap or clip at either graded viewport; long identifiers truncate within their own region.

### Focus behavior - 4 of 4

- [x] F1 PASS - Every enabled control reached in the primary keyboard path has a solid focus outline at least 2 CSS pixels wide.
- [x] F2 PASS - Keyboard Tab reaches Import application, Copy source, and Save in that DOM order after an object is opened and edited.
- [x] F3 PASS - Keyboard Tab reaches a bottom-panel tab, and the focused tab retains a visible outline.
- [x] F4 PASS - Ctrl+K moves focus to Search objects; editor keyboard shortcuts do not remove the editor focus indicator.

### Loading state - 4 of 4

- [x] L1 PASS - The loading screenshot shows `Loading application objects...` next to a visible busy indicator.
- [x] L2 PASS - The loading status is exposed with `role="status"` and is asserted before the delayed sidecar response completes.
- [x] L3 PASS - The center message says `Loading Appian application` and does not tell the user to select an object while loading.
- [x] L4 PASS - Loading does not remove the application bar, region layout, import action, or connection status.

### Empty state - 4 of 4

- [x] E1 PASS - The empty screenshot states `Import an Appian export to begin.` in the explorer.
- [x] E2 PASS - The center empty state names the next action and points to Import application in the top bar.
- [x] E3 PASS - Unavailable diagnostics and session actions state why they are disabled instead of showing blank content.
- [x] E4 PASS - The empty state retains the stable workbench layout and shows a zero object count without fabricated data.

### Error state - 4 of 4

- [x] ER1 PASS - The error screenshot shows `Could not load objects: sidecar_unavailable` in the explorer.
- [x] ER2 PASS - The error treatment uses a red marker and pale error surface without turning the full workspace red.
- [x] ER3 PASS - The error state gives a recovery direction: check the sidecar connection or import again.
- [x] ER4 PASS - The error is exposed with `role="alert"` and its intended copy is asserted by Playwright.

## First grading failures and disposition

The first grade used only the two pre-existing loaded-workbench screenshots and
the previous Playwright suite. These items failed:

- IH4 - Both screenshots contained the Next.js development badge. Fixed by disabling development indicators; re-rendered evidence is clean.
- CL4 - `Offline` in the assistant heading used success green. Fixed with explicit online and offline color classes.
- F1, F2, and F4 - The suite did not prove the required focus behavior, and later CSS rules suppressed outlines on some inputs and the editor. Fixed with a uniform 2-pixel `:focus-visible` rule and keyboard-path assertions.
- L1 through L4 - No rendered loading evidence existed, and the center showed empty-state copy while objects loaded. Fixed with a busy treatment, loading-specific center copy, delayed-sidecar assertion, and screenshot.
- E1 through E4 - No rendered initial-empty evidence existed. Fixed with actionable explorer and center copy plus a screenshot and copy assertions.
- ER1 through ER4 - No rendered codebase-load error evidence existed. Fixed with an alert treatment, recovery copy, a failed-sidecar assertion, and screenshot.

No known visual deviation remains in this checklist. This is not a claim that a
still image proves animation quality, color contrast ratios, screen-reader
output, or behavior at ungraded viewport sizes. The Playwright assertions cover
only the keyboard and semantic behavior named above.
