const { test, expect } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

const SCREENSHOT_DIR = path.join(__dirname, '..', 'test-results');
const SCREENSHOT_1024 = path.join(SCREENSHOT_DIR, 'workbench-loaded-1024x640.png');
const SCREENSHOT_1440 = path.join(SCREENSHOT_DIR, 'workbench-loaded-1440x900.png');
const SCREENSHOT_EMPTY = path.join(SCREENSHOT_DIR, 'workbench-empty-1440x900.png');
const SCREENSHOT_LOADING = path.join(SCREENSHOT_DIR, 'workbench-loading-1440x900.png');
const SCREENSHOT_ERROR = path.join(SCREENSHOT_DIR, 'workbench-error-1440x900.png');
const SCREENSHOT_DARK = path.join(SCREENSHOT_DIR, 'workbench-dark-1440x900.png');
const SCREENSHOT_LIGHT = path.join(SCREENSHOT_DIR, 'workbench-light-1440x900.png');
const DESIGNER_DARK_1440 = path.join(SCREENSHOT_DIR, 'designer-dark-1440x900.png');
const DESIGNER_DARK_1024 = path.join(SCREENSHOT_DIR, 'designer-dark-1024x640.png');
const DESIGNER_LIGHT_1440 = path.join(SCREENSHOT_DIR, 'designer-light-1440x900.png');
const DESIGNER_LIGHT_1024 = path.join(SCREENSHOT_DIR, 'designer-light-1024x640.png');
const PENDING_DELETE_1440 = path.join(SCREENSHOT_DIR, 'pending-deletion-1440x900.png');
const TAB_NAMES = ['Problems', 'Dependencies', 'Tests', 'Changes', 'History', 'Output'];
const EMPTY_EXPLORER = 'Import an Appian export to begin.';
const UUID = '_a-11111111-1111-8000-1111-111111111111_100001';
const HELPER_UUID = '_a-11111111-1111-8000-1111-111111111111_100002';
const HELPER_UUID_2 = '_a-11111111-1111-8000-1111-111111111111_100003';
const SOURCE = [
  'a!localVariables(',
  '  local!total: ri!value,',
  '  a!textField(label: "Demo", value: rule!APP_Helper(local!total)) == \'bad\'',
  ')',
].join('\n');

async function stubSidecar(page, options = {}) {
  const {
    loaded = false,
    codebaseDelay = 0,
    codebaseError = '',
    // R27 breadth: let a test describe a codebase of many object types rather
    // than the single expression-rule shape the other tests rely on.
    byType = null,
    uuidToName = null,
    objectTypeByUuid = null,
    descriptions = null,
    diagnostics = null,
    models = null,
    modelsError = '',
    settingsTestError = '',
    socketMessages = [],
  } = typeof options === 'boolean' ? { loaded: options } : options;
  const calls = [];
  await page.routeWebSocket('**/ws**', (socket) => {
    setTimeout(() => {
      socketMessages.forEach((message) => socket.send(JSON.stringify(message)));
    }, 100);
  });
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const routeCall = {
      method: request.method(),
      path: url.pathname,
      params: Object.fromEntries(url.searchParams),
      body: null,
    };
    if (request.method() !== 'GET' && request.headers()['content-type']?.includes('application/json')) {
      routeCall.body = request.postDataJSON();
    }
    calls.push(routeCall);

    let status = 200;
    let body = {};
    if (url.pathname === '/api/codebase') {
      if (codebaseDelay) {
        await new Promise((resolve) => setTimeout(resolve, codebaseDelay));
      }
      if (codebaseError) {
        status = 503;
        body = { detail: codebaseError };
      } else {
        body = loaded ? {
          app_name: 'Sentinel Demo',
          appian_version: '26.1',
          by_type: byType || { expression_rule: [UUID, HELPER_UUID, HELPER_UUID_2] },
          uuid_to_name: uuidToName || {
            [UUID]: 'APP_Test',
            [HELPER_UUID]: 'APP_Helper',
            [HELPER_UUID_2]: 'APP_Helper',
          },
          descriptions: descriptions || {},
        } : null;
      }
    } else if (url.pathname === '/api/status') {
      body = { status: 'idle', current_step: 0 };
    } else if (url.pathname === '/api/test-results') {
      body = { status: 'no_results' };
    } else if (url.pathname === '/api/diff') {
      body = { created: [], modified: [] };
    } else if (url.pathname === '/api/settings') {
      body = {};
    } else if (url.pathname === '/api/history' && request.method() === 'GET') {
      body = [{
        hash: 'revision-1',
        message: 'baseline',
        actor: 'system',
        timestamp: '2026-09-18T12:00:00',
        requirement_id: '',
      }];
    } else if (url.pathname === '/api/history/restore') {
      status = 409;
      body = { detail: { reason: 'workspace_not_clean' } };
    } else if (url.pathname === `/api/objects/${UUID}/diagnostics`) {
      body = diagnostics ? { is_valid: false, diagnostics } : {
        is_valid: false,
        diagnostics: [{
          code: 'SAIL001',
          message: 'Example object problem',
          severity: 'error',
          line: 3,
          column: 3,
          end_line: 3,
          end_column: 14,
        }],
      };
    } else if (url.pathname === `/api/objects/${UUID}/tests`) {
      body = {
        object_uuid: UUID,
        tests: [{
          name: 'Positive total',
          description: 'Returns a total for a valid value.',
          inputs: { value: '10' },
          assertion_type: 'output_equals',
          expected: '10',
        }],
      };
    } else if (url.pathname === `/api/objects/${UUID}`) {
      body = {
        uuid: UUID,
        name: 'APP_Test',
        object_type: 'expression_rule',
        definition: routeCall.body?.definition || SOURCE,
        rule_inputs: [{ name: 'value', type_name: 'Integer', is_list: false }],
      };
    } else if (url.pathname === `/api/objects/${HELPER_UUID}`
      || url.pathname === `/api/objects/${HELPER_UUID_2}`) {
      body = {
        uuid: url.pathname.endsWith(HELPER_UUID) ? HELPER_UUID : HELPER_UUID_2,
        name: 'APP_Helper',
        object_type: 'expression_rule',
        definition: 'ri!value',
      };
    } else if (url.pathname === '/api/tests/bulk') {
      body = routeCall.body?.preview
        ? { preview: true, diff: { [UUID]: '- old test\n+ Generated test\n' } }
        : { preview: false, revision: 'revision-2', object_uuids: [UUID] };
    } else if (url.pathname === '/api/settings/models') {
      if (modelsError) {
        status = 502;
        body = { status: 'error', message: modelsError, models: [] };
      } else {
        body = { status: 'ok', models: models || [] };
      }
    } else if (url.pathname === '/api/settings/test' && settingsTestError) {
      status = 502;
      body = { status: 'error', message: settingsTestError };
    } else if (url.pathname === '/api/stories') {
      body = { files: [{ name: 'story.pdf' }, { name: 'notes.md' }] };
    } else if (url.pathname.startsWith('/api/typed-objects/') && request.method() === 'DELETE') {
      body = {
        status: 'deleted',
        uuid: decodeURIComponent(url.pathname.split('/').at(-1)),
        file_path: 'content/deleted.xml',
        dependents: [],
        children: [],
        forced: url.searchParams.get('force') === 'true',
      };
    } else if (objectTypeByUuid && url.pathname.startsWith('/api/objects/')) {
      const uuid = url.pathname.split('/')[3];
      body = {
        uuid,
        name: uuidToName?.[uuid] || uuid,
        object_type: objectTypeByUuid[uuid],
        definition: `-- ${objectTypeByUuid[uuid]} source for ${uuidToName?.[uuid]}`,
      };
    }
    await route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
  });
  return calls;
}

async function openWorkbench(page, loaded = false) {
  const calls = await stubSidecar(page, loaded);
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(250);
  await expect(page.getByLabel('Appian Sentinel')).toBeVisible();
  if (!loaded) {
    await expect(page.getByRole('complementary', { name: 'Object explorer' })).toContainText(
      EMPTY_EXPLORER,
    );
  }
  return calls;
}

// A click that lands before React hydrates is swallowed: the tab takes focus
// but never becomes selected. Retry until the selection actually moves.
async function openSettings(page) {
  const button = page.getByRole('button', { name: 'Settings' });
  await expect(async () => {
    await button.click();
    await expect(page.getByRole('dialog', { name: 'Settings' })).toBeVisible({ timeout: 1000 });
  }).toPass({ timeout: 15000 });
}

async function openTab(page, name) {
  const tab = page.getByRole('tab', { name });
  await expect(async () => {
    await tab.click();
    await expect(tab).toHaveAttribute('aria-selected', 'true', { timeout: 1000 });
  }).toPass({ timeout: 15000 });
}

async function visibleFocus(page) {
  return page.evaluate(() => {
    const element = document.activeElement;
    if (!element || element === document.body) return null;
    const style = window.getComputedStyle(element);
    return {
      name: element.getAttribute('aria-label')
        || element.textContent?.trim().replace(/\s+/g, ' ')
        || element.getAttribute('placeholder')
        || element.tagName,
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
    };
  });
}

test.describe('R28-R30 workbench rendered checks (no codebase loaded)', () => {
  test('app bar renders product name', async ({ page }) => {
    await openWorkbench(page);
    const brand = page.getByLabel('Appian Sentinel');
    await expect(brand).toBeVisible();
    await expect(brand).toContainText('Appian Sentinel');
    await expect(brand.locator('svg')).toBeVisible();
  });

  test('dark mode is default and light mode persists', async ({ page }) => {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
    await page.setViewportSize({ width: 1440, height: 900 });
    await openWorkbench(page);

    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await expect(page.getByRole('button', { name: 'Use light mode' })).toBeVisible();
    await page.screenshot({ path: SCREENSHOT_DARK, fullPage: false });

    await page.getByRole('button', { name: 'Use light mode' }).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    await expect(page.getByRole('button', { name: 'Use dark mode' })).toBeVisible();
    await page.screenshot({ path: SCREENSHOT_LIGHT, fullPage: false });

    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  });

  test('all primary work areas resize and persist', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openWorkbench(page);
    const explorer = page.getByRole('separator', { name: 'Resize object explorer' });
    const editor = page.getByRole('separator', { name: 'Resize assistant' });
    const results = page.getByRole('separator', { name: 'Resize results panel' });

    const explorerBefore = Number(await explorer.getAttribute('aria-valuenow'));
    const explorerBox = await explorer.boundingBox();
    await page.mouse.move(explorerBox.x + 2, explorerBox.y + 40);
    await page.mouse.down();
    await page.mouse.move(explorerBox.x + 42, explorerBox.y + 40, { steps: 4 });
    await page.mouse.up();
    await expect(explorer).toHaveAttribute('aria-valuenow', String(explorerBefore + 40));

    const editorBefore = Number(await editor.getAttribute('aria-valuenow'));
    await editor.focus();
    await page.keyboard.press('ArrowLeft');
    await expect(editor).toHaveAttribute('aria-valuenow', String(editorBefore + 16));

    const resultsBefore = Number(await results.getAttribute('aria-valuenow'));
    await results.focus();
    await page.keyboard.press('ArrowUp');
    await expect(results).toHaveAttribute('aria-valuenow', String(resultsBefore + 16));

    const saved = {
      explorer: await explorer.getAttribute('aria-valuenow'),
      editor: await editor.getAttribute('aria-valuenow'),
      results: await results.getAttribute('aria-valuenow'),
    };
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('separator', { name: 'Resize object explorer' }))
      .toHaveAttribute('aria-valuenow', saved.explorer);
    await expect(page.getByRole('separator', { name: 'Resize assistant' }))
      .toHaveAttribute('aria-valuenow', saved.editor);
    await expect(page.getByRole('separator', { name: 'Resize results panel' }))
      .toHaveAttribute('aria-valuenow', saved.results);
  });

  test('object explorer region exists and shows empty state', async ({ page }) => {
    await openWorkbench(page);
    const explorer = page.getByRole('complementary', { name: 'Object explorer' });
    await expect(explorer).toBeVisible();
    await expect(explorer).toContainText(EMPTY_EXPLORER);
  });

  test('object type filter and chat selection', async ({ page }) => {
    await stubSidecar(page, {
      loaded: true,
      byType: { expression_rule: [UUID], interface: [HELPER_UUID] },
      uuidToName: { [UUID]: 'APP_Test', [HELPER_UUID]: 'APP_Iface' },
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('treeitem', { name: 'APP_Test' })).toBeVisible();
    await page.getByLabel('Filter object type').selectOption('interface');
    await expect(page.getByRole('treeitem', { name: 'APP_Iface' })).toBeVisible();
    await expect(page.getByRole('treeitem', { name: 'APP_Test' })).toHaveCount(0);
    await page.getByLabel('Add APP_Iface to chat').check();
    await expect(page.getByLabel('Selected chat objects')).toContainText('APP_Iface');
  });

  test('tool activity renders the orchestrator metadata shape and statuses', async ({ page }) => {
    const toolMessage = (status) => ({
      type: 'message',
      data: {
        id: `tool-${status}`,
        role: 'assistant',
        message_type: 'tool',
        content: `Tool read_object ${status}.`,
        metadata: {
          call_id: `call-${status}`,
          tool: 'read_object',
          status,
          object_uuids: [UUID],
          result_summary: status,
        },
      },
    });
    await stubSidecar(page, {
      loaded: true,
      socketMessages: ['ok', 'blocked', 'failed'].map(toolMessage),
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });

    await expect(page.getByLabel('Tool calls')).toHaveCount(3);
    await expect(page.locator('.tool-call-list code')).toHaveText([
      'read_object', 'read_object', 'read_object',
    ]);
    await expect(page.locator('.messages .object-chip strong')).toHaveText([
      'APP_Test', 'APP_Test', 'APP_Test',
    ]);
    await expect(page.locator('.tool-status.is-ok')).toHaveText('ok');
    await expect(page.locator('.tool-status.is-blocked')).toHaveText('blocked');
    await expect(page.locator('.tool-status.is-failed')).toHaveText('failed');
  });

  test('chat pending deletion requires confirmation and force opt-in', async ({ page }) => {
    const deleteUuid = 'constant-delete-uuid';
    const pending = {
      type: 'message',
      data: {
        id: 'pending-delete',
        role: 'assistant',
        message_type: 'tool',
        content: 'Raw delete result must not be shown.',
        metadata: {
          tool: 'delete_constant',
          status: 'ok',
          object_uuids: [deleteUuid],
          result: {
            result: {
              status: 'pending_deletion',
              pending_deletion: true,
              applied: false,
              tool: 'delete_constant',
              object: { uuid: deleteUuid, name: 'APP_MaxRetries', type: 'constant' },
              reverse_dependencies: [HELPER_UUID],
              children: [],
              confirmation: {
                required: true,
                action: 'delete_typed_object',
                slug: 'constant',
                object_uuid: deleteUuid,
                preview: false,
                force_required: true,
              },
            },
          },
        },
      },
    };
    const calls = await stubSidecar(page, {
      loaded: true,
      byType: { constant: [deleteUuid], expression_rule: [HELPER_UUID] },
      uuidToName: { [deleteUuid]: 'APP_MaxRetries', [HELPER_UUID]: 'APP_Helper' },
      objectTypeByUuid: { [deleteUuid]: 'constant', [HELPER_UUID]: 'expression_rule' },
      socketMessages: [pending],
    });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/', { waitUntil: 'domcontentloaded' });

    const confirmation = page.getByRole('region', { name: 'Confirm deletion of APP_MaxRetries' });
    await expect(confirmation).toContainText('Nothing has been deleted yet.');
    await expect(confirmation).toContainText('Deleting cannot be undone.');
    await expect(confirmation).toContainText('APP_Helper');
    await expect(page.getByText('Raw delete result must not be shown.')).toHaveCount(0);
    await expect(confirmation.getByRole('button', { name: 'Delete object' })).toBeDisabled();
    expect(calls.filter((call) => call.method === 'DELETE')).toEqual([]);
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
    await page.screenshot({ path: PENDING_DELETE_1440, fullPage: false });

    await confirmation.getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByText('Deletion cancelled. Nothing was deleted.')).toBeVisible();
    expect(calls.filter((call) => call.method === 'DELETE')).toEqual([]);

    await page.reload({ waitUntil: 'domcontentloaded' });
    const nextConfirmation = page.getByRole('region', { name: 'Confirm deletion of APP_MaxRetries' });
    await nextConfirmation.getByLabel('Force deletion. Dependent objects will break.').check();
    await nextConfirmation.getByRole('button', { name: 'Delete object' }).click();
    await expect(page.getByText('APP_MaxRetries was deleted.')).toBeVisible();

    const deletes = calls.filter((call) => call.method === 'DELETE');
    expect(deletes).toHaveLength(1);
    expect(deletes[0].path).toBe(`/api/typed-objects/constant/${encodeURIComponent(deleteUuid)}`);
    expect(deletes[0].params).toMatchObject({ preview: 'false', force: 'true' });
  });

  test('empty state renders intended copy and evidence', async ({ page }) => {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
    await page.setViewportSize({ width: 1440, height: 900 });
    await stubSidecar(page);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.getByText(EMPTY_EXPLORER)).toBeVisible();
    await expect(page.getByText('Import an Appian application')).toBeVisible();
    await page.screenshot({ path: SCREENSHOT_EMPTY, fullPage: false });
    expect(fs.existsSync(SCREENSHOT_EMPTY), `${SCREENSHOT_EMPTY} must exist`).toBeTruthy();
  });

  test('loading state renders intended copy and evidence', async ({ page }) => {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
    await page.setViewportSize({ width: 1440, height: 900 });
    await stubSidecar(page, { codebaseDelay: 3000 });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('status')).toContainText('Loading application objects...');
    await page.waitForTimeout(500);
    await page.screenshot({ path: SCREENSHOT_LOADING, fullPage: false });
    expect(fs.existsSync(SCREENSHOT_LOADING), `${SCREENSHOT_LOADING} must exist`).toBeTruthy();
  });

  test('error state renders intended copy and evidence', async ({ page }) => {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
    await page.setViewportSize({ width: 1440, height: 900 });
    await stubSidecar(page, { codebaseError: 'sidecar_unavailable' });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.tree-state[role="alert"]')).toContainText(
      'Could not load application objects.',
    );
    await page.screenshot({ path: SCREENSHOT_ERROR, fullPage: false });
    expect(fs.existsSync(SCREENSHOT_ERROR), `${SCREENSHOT_ERROR} must exist`).toBeTruthy();
  });

  test('keyboard focus is visible and reaches primary actions in order', async ({ page }) => {
    await openWorkbench(page, true);
    await page.getByRole('treeitem', { name: 'APP_Test' }).click();
    await page.getByLabel('APP_Test source editor').fill(`${SOURCE}\n1`);

    const editorFocus = await visibleFocus(page);
    expect(editorFocus.name).toBe('APP_Test source editor');
    expect(editorFocus.outlineStyle).not.toBe('none');
    expect(parseFloat(editorFocus.outlineWidth)).toBeGreaterThanOrEqual(2);

    await page.keyboard.press('Control+k');
    await expect(page.getByLabel('Search objects')).toBeFocused();
    const searchFocus = await visibleFocus(page);
    expect(searchFocus.outlineStyle).not.toBe('none');
    expect(parseFloat(searchFocus.outlineWidth)).toBeGreaterThanOrEqual(2);

    await page.evaluate(() => {
      document.body.tabIndex = -1;
      document.body.focus();
    });

    const reached = [];
    for (let index = 0; index < 80; index += 1) {
      await page.keyboard.press('Tab');
      const focus = await visibleFocus(page);
      if (!focus) continue;
      expect(
        focus.outlineStyle !== 'none' && parseFloat(focus.outlineWidth) >= 2,
        `"${focus.name}" must have a visible focus outline`,
      ).toBeTruthy();
      reached.push(focus.name);
      if (reached.includes('Save')) break;
    }

    const importIndex = reached.indexOf('Import application');
    const copyIndex = reached.indexOf('Copy source');
    const saveIndex = reached.indexOf('Save');
    expect(importIndex, 'Tab order must reach Import application').toBeGreaterThanOrEqual(0);
    expect(copyIndex, 'Tab order must reach Copy source').toBeGreaterThan(importIndex);
    expect(saveIndex, 'Tab order must reach Save').toBeGreaterThan(copyIndex);
  });

  test('bottom panel tabs are present, clickable, and keyboard reachable', async ({ page }) => {
    await openWorkbench(page);
    const panel = page.getByRole('region', { name: 'Workbench results' });
    const tabs = panel.getByRole('tab');
    await expect(tabs).toHaveCount(TAB_NAMES.length);
    for (const name of TAB_NAMES) {
      await expect(panel.getByRole('tab', { name })).toBeVisible();
    }

    for (const name of TAB_NAMES) {
      const tab = panel.getByRole('tab', { name });
      await tab.click();
      await expect(tab).toHaveAttribute('aria-selected', 'true');
      for (const other of TAB_NAMES.filter((item) => item !== name)) {
        await expect(panel.getByRole('tab', { name: other })).toHaveAttribute(
          'aria-selected',
          'false',
        );
      }
    }

    await page.locator('body').click({ position: { x: 8, y: 8 } });
    let focusedTabName = '';
    for (let i = 0; i < 40; i += 1) {
      await page.keyboard.press('Tab');
      const meta = await page.evaluate(() => {
        const el = document.activeElement;
        if (!el || el.getAttribute('role') !== 'tab') return null;
        const style = window.getComputedStyle(el);
        return {
          name: (el.textContent || '').trim().split('\n')[0],
          outlineWidth: style.outlineWidth,
          outlineStyle: style.outlineStyle,
          outlineColor: style.outlineColor,
        };
      });
      if (!meta) continue;
      focusedTabName = meta.name;
      const outlineVisible =
        meta.outlineStyle !== 'none' && parseFloat(meta.outlineWidth) > 0;
      expect(
        outlineVisible,
        `tab "${meta.name}" Tab focus must be visible (outline ${meta.outlineStyle} ${meta.outlineWidth})`,
      ).toBeTruthy();
      break;
    }
    expect(focusedTabName, 'Tab key must reach a bottom-panel tab').not.toEqual('');
  });

  test('no horizontal overflow at 1024x640', async ({ page }) => {
    await openWorkbench(page);
    await page.setViewportSize({ width: 1024, height: 640 });
    const overflow = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(
      overflow.scrollWidth,
      `scrollWidth ${overflow.scrollWidth} > clientWidth ${overflow.clientWidth} + 1`,
    ).toBeLessThanOrEqual(overflow.clientWidth + 1);
  });

  test('visible text is ASCII only', async ({ page }) => {
    await openWorkbench(page);
    const offenders = await page.evaluate(() => {
      const re = /[^\x00-\x7F]/;
      const found = [];
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      let node = walker.nextNode();
      while (node) {
        const text = node.textContent || '';
        if (re.test(text)) {
          const parent = node.parentElement;
          const hidden =
            parent &&
            (parent.closest('[hidden]') ||
              window.getComputedStyle(parent).display === 'none' ||
              window.getComputedStyle(parent).visibility === 'hidden');
          if (!hidden) {
            found.push(text.replace(/\s+/g, ' ').trim());
          }
        }
        node = walker.nextNode();
      }
      return found;
    });
    expect(offenders, `non-ASCII visible text: ${JSON.stringify(offenders)}`).toEqual([]);
  });

  test('session actions are disabled until a codebase is loaded', async ({ page }) => {
    await openWorkbench(page);
    await expect(page.getByText('Diagnostics disabled: load an export first.')).toBeVisible();
    await page.getByRole('tab', { name: 'Tests' }).click();
    await expect(page.getByRole('button', { name: 'Preview selected' })).toBeDisabled();
    await page.getByRole('tab', { name: 'History' }).click();
    await expect(page.getByText('History disabled: load an export first.')).toBeVisible();
    // Settings is the exception: testing and saving the connection are the
    // recovery path, so gating them on being online would trap the operator.
    await openSettings(page);
    await expect(page.getByRole('button', { name: 'Test', exact: true })).toBeEnabled();
    await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeEnabled();
  });

  test('explorer tree expands, collapses, and relabels chat checkboxes', async ({ page }) => {
    await openWorkbench(page, true);
    const group = page.getByRole('treeitem', { name: /^Expression Rule/ });
    await group.focus();
    await expect(group).toHaveAttribute('aria-expanded', 'true');

    await page.keyboard.press('ArrowLeft');
    await expect(group).toHaveAttribute('aria-expanded', 'false');
    await expect(page.getByRole('treeitem', { name: 'APP_Test' })).toHaveCount(0);

    await page.keyboard.press('ArrowRight');
    await expect(group).toHaveAttribute('aria-expanded', 'true');
    await page.keyboard.press('ArrowRight');
    await expect(page.getByRole('treeitem', { name: 'APP_Test' })).toBeFocused();

    await page.keyboard.press('ArrowLeft');
    await expect(group).toBeFocused();

    // A checked box must not still say "Add": the label has to describe the
    // action the operator would take next.
    await page.getByLabel('Add APP_Test to chat').check();
    await expect(page.getByLabel('Remove APP_Test from chat')).toBeChecked();
  });

  test('dark mode Import and status bar meet 4.5:1 contrast', async ({ page }) => {
    await openWorkbench(page);
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');

    const ratios = await page.evaluate(() => {
      const channel = (part) => {
        const value = part / 255;
        return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
      };
      const luminance = (color) => {
        const [r, g, b] = color.match(/\d+(\.\d+)?/g).map(Number);
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
      };
      const backdrop = (element) => {
        let node = element;
        while (node) {
          const value = window.getComputedStyle(node).backgroundColor;
          if (value && !value.startsWith('rgba(0, 0, 0, 0)')) return value;
          node = node.parentElement;
        }
        return 'rgb(255, 255, 255)';
      };
      const ratio = (element) => {
        const style = window.getComputedStyle(element);
        const first = luminance(style.color);
        const second = luminance(backdrop(element));
        return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
      };
      return {
        import: ratio(
          [...document.querySelectorAll('.topbar .primary-button')]
            .find((node) => node.textContent.includes('Import application')),
        ),
        statusbar: ratio(document.querySelector('.statusbar')),
      };
    });

    expect(ratios.import, `Import contrast ${ratios.import.toFixed(2)}`).toBeGreaterThanOrEqual(4.5);
    expect(ratios.statusbar, `status bar contrast ${ratios.statusbar.toFixed(2)}`).toBeGreaterThanOrEqual(4.5);
  });

  test('settings traps focus, closes with Escape, and restores focus', async ({ page }) => {
    await openWorkbench(page);
    const opener = page.getByRole('button', { name: 'Settings' });
    await opener.focus();
    await opener.click();

    const dialog = page.getByRole('dialog', { name: 'Settings' });
    await expect(dialog).toBeVisible();
    await expect(page.getByLabel('Model service URL')).toBeFocused();

    await dialog.getByRole('button', { name: 'Save', exact: true }).focus();
    await page.keyboard.press('Tab');
    await expect(dialog.getByRole('button', { name: 'Close' })).toBeFocused();

    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(opener).toBeFocused();
  });
});

test.describe('loaded codebase API contracts and rendered checks', () => {
  test('code intelligence renders and editor history tracks saved source', async ({ page }) => {
    await openWorkbench(page, true);
    await page.getByRole('treeitem', { name: 'APP_Test' }).click();

    await expect(page.locator('.sail-callable').filter({ hasText: 'a!localVariables' })).toBeVisible();
    await expect(page.locator('.sail-operator.is-invalid').filter({ hasText: '==' })).toBeVisible();
    await expect(page.locator('.sail-string.is-invalid').filter({ hasText: "'bad'" })).toBeVisible();
    await expect(page.locator('.has-diagnostic')).toBeVisible();

    const outline = page.getByRole('complementary', { name: 'Rule inputs' });
    await expect(outline).toContainText('value');
    await expect(outline).toContainText('total');
    await expect(outline).toContainText('a!textField');

    const editor = page.getByLabel('APP_Test source editor');
    await editor.fill(`${SOURCE}\n1`);
    await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeEnabled();
    await editor.press('Control+z');
    await expect(editor).toHaveValue(SOURCE);
    await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeDisabled();
    await editor.press('Control+y');
    await expect(editor).toHaveValue(`${SOURCE}\n1`);
    await editor.press('Control+Shift+z');
    await expect(editor).toHaveValue(`${SOURCE}\n1`);
  });

  test('problems, references, and dependencies navigate', async ({ page }) => {
    await openWorkbench(page, true);
    await page.getByRole('treeitem', { name: 'APP_Test' }).click();

    await page.getByText('Example object problem').click();
    const selection = await page.getByLabel('APP_Test source editor').evaluate((element) => ({
      start: element.selectionStart,
      end: element.selectionEnd,
    }));
    expect(selection.end).toBeGreaterThan(selection.start);

    await page.getByRole('tab', { name: 'Dependencies' }).click();
    await expect(page.getByRole('tabpanel')).toContainText('Outbound references');
    await expect(page.getByRole('tabpanel')).toContainText('APP_Helper');

    const editor = page.getByLabel('APP_Test source editor');
    await editor.evaluate((element) => {
      const offset = element.value.indexOf('rule!APP_Helper') + 8;
      element.setSelectionRange(offset, offset);
      element.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
    });
    await expect(page.getByRole('dialog', { name: 'Choose referenced object' })).toBeVisible();
    await expect(page.getByRole('dialog').getByText('APP_Helper', { exact: false })).toHaveCount(2);
    await page.getByRole('dialog').getByRole('button').first().click();
    await expect(page.getByRole('tabpanel')).toContainText('Inbound references');
    await expect(page.getByRole('tabpanel')).toContainText('APP_Test');
  });

  test('object diagnostics and save use per-object contracts', async ({ page }) => {
    const calls = await openWorkbench(page, true);
    await page.getByRole('treeitem', { name: 'APP_Test' }).click();

    await expect(page.getByText('Example object problem')).toBeVisible();
    expect(calls.some((call) => (
      call.method === 'GET' && call.path === `/api/objects/${UUID}/diagnostics`
    ))).toBeTruthy();

    const editor = page.getByLabel('APP_Test source editor');
    await editor.fill('2 + 2');
    const save = page.getByRole('button', { name: 'Save', exact: true });
    await expect(save).toBeEnabled();
    await save.click();
    await expect(page.getByText('Saved')).toBeVisible();

    const put = calls.find((call) => (
      call.method === 'PUT' && call.path === `/api/objects/${UUID}`
    ));
    expect(put?.body).toEqual({ definition: '2 + 2' });
  });

  test('bulk tests require preview before confirmed apply', async ({ page }) => {
    const calls = await openWorkbench(page, true);
    await page.getByRole('tab', { name: 'Tests' }).click();
    // Scoped to the bulk picker: the Build grid also has a row checkbox for
    // this object, so an unscoped label match is ambiguous.
    await page.locator('.bulk-picker').getByLabel('APP_Test').check();

    const previewButton = page.getByRole('button', { name: 'Preview selected' });
    const applyButton = page.getByRole('button', { name: 'Confirm apply' });
    await expect(previewButton).toBeEnabled();
    await expect(applyButton).toBeDisabled();
    await previewButton.click();
    await expect(page.getByLabel('Bulk test preview')).toContainText('+ Generated test');
    await expect(applyButton).toBeEnabled();
    await applyButton.click();
    await expect(page.getByText('Apply complete. Revision revision-2.')).toBeVisible();

    const bulkCalls = calls.filter((call) => (
      call.method === 'POST' && call.path === '/api/tests/bulk'
    ));
    expect(bulkCalls).toHaveLength(2);
    expect(bulkCalls[0].body).toEqual({
      object_uuids: [UUID],
      tests: [{
        name: 'Generated test',
        description: '',
        inputs: {},
        assertion_type: 'output_equals',
        expected: null,
        assertion_expression: '',
      }],
      preview: true,
    });
    expect(bulkCalls[1].body.preview).toBe(false);
  });

  test('history restore and chat requirement intake use correct routes', async ({ page }) => {
    const calls = await openWorkbench(page, true);
    await page.getByRole('tab', { name: 'History' }).click();
    const restore = page.getByRole('button', { name: 'Restore' });
    await expect(restore).toBeEnabled();
    await restore.click();
    await expect(page.getByText('Restore error: workspace_not_clean')).toBeVisible();

    await page.getByLabel('Attach files').setInputFiles([
      {
        name: 'story.pdf',
        mimeType: 'application/pdf',
        buffer: Buffer.from('%PDF-1.4 test'),
      },
      {
        name: 'notes.md',
        mimeType: 'text/markdown',
        buffer: Buffer.from('# Notes'),
      },
    ]);
    await expect(page.getByText('2 requirement files loaded.')).toBeVisible();

    await page.getByLabel('Azure DevOps work item').fill('42');
    await page.getByRole('button', { name: 'Load work item' }).click();
    await expect(page.getByText('Work item 42 loaded.')).toBeVisible();

    expect(calls.some((call) => (
      call.method === 'POST'
      && call.path === '/api/history/restore'
      && call.body?.revision === 'revision-1'
    ))).toBeTruthy();
    expect(calls.some((call) => call.method === 'POST' && call.path === '/api/stories')).toBeTruthy();
    expect(calls.some((call) => call.method === 'POST' && call.path === '/api/ado/workitem')).toBeTruthy();
  });

  test('loaded workbench has no console errors, overflow, or non-ASCII text', async ({ page }) => {
    const consoleErrors = [];
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text());
    });
    await openWorkbench(page, true);
    await page.getByRole('treeitem', { name: 'APP_Test' }).click();

    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
    for (const viewport of [
      { width: 1024, height: 640, path: SCREENSHOT_1024, evidence: DESIGNER_DARK_1024 },
      { width: 1440, height: 900, path: SCREENSHOT_1440, evidence: DESIGNER_DARK_1440 },
    ]) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.waitForTimeout(150);
      const overflow = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }));
      expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 1);
      await page.screenshot({ path: viewport.path, fullPage: false });
      await page.screenshot({ path: viewport.evidence, fullPage: false });
    }

    await page.getByRole('button', { name: 'Use light mode' }).click();
    for (const viewport of [
      { width: 1024, height: 640, path: DESIGNER_LIGHT_1024 },
      { width: 1440, height: 900, path: DESIGNER_LIGHT_1440 },
    ]) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.waitForTimeout(150);
      await page.screenshot({ path: viewport.path, fullPage: false });
    }

    const offenders = await page.evaluate(() => {
      const found = [];
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      let node = walker.nextNode();
      while (node) {
        const parent = node.parentElement;
        const text = node.textContent || '';
        const hidden = parent && (
          parent.closest('[hidden]')
          || window.getComputedStyle(parent).display === 'none'
          || window.getComputedStyle(parent).visibility === 'hidden'
        );
        if (!hidden && /[^\x00-\x7F]/.test(text)) found.push(text.trim());
        node = walker.nextNode();
      }
      return found.filter(Boolean);
    });
    expect(offenders).toEqual([]);
    expect(consoleErrors).toEqual([]);
    expect(fs.existsSync(SCREENSHOT_1024)).toBeTruthy();
    expect(fs.existsSync(SCREENSHOT_1440)).toBeTruthy();
    for (const evidence of [
      DESIGNER_DARK_1024,
      DESIGNER_DARK_1440,
      DESIGNER_LIGHT_1024,
      DESIGNER_LIGHT_1440,
    ]) {
      expect(fs.existsSync(evidence), `${evidence} must exist`).toBeTruthy();
    }
  });

  test('editor toolbar and results are reachable, not silently clipped', async ({ page }) => {
    await openWorkbench(page, true);
    await page.getByRole('treeitem', { name: 'APP_Test' }).click();
    await expect(page.getByLabel('APP_Test source editor')).toBeVisible();

    for (const viewport of [{ width: 1024, height: 640 }, { width: 1440, height: 900 }]) {
      await page.setViewportSize(viewport);
      await page.waitForTimeout(150);

      const layout = await page.evaluate(() => {
        const measure = (selector) => {
          const element = document.querySelector(selector);
          if (!element) return null;
          const box = element.getBoundingClientRect();
          return {
            selector,
            width: Math.round(box.width),
            right: Math.round(box.right),
            clipped: element.scrollWidth > element.clientWidth + 1,
            overflowX: window.getComputedStyle(element).overflowX,
          };
        };
        return {
          innerWidth: window.innerWidth,
          chat: Math.round(document.querySelector('.assistant-panel').getBoundingClientRect().width),
          editor: Math.round(document.querySelector('.center-column').getBoundingClientRect().width),
          chatLeft: Math.round(document.querySelector('.assistant-panel').getBoundingClientRect().left),
          editorLeft: Math.round(document.querySelector('.center-column').getBoundingClientRect().left),
          regions: [
            '.editor-shell', '.editor-toolbar', '.expression-toolbar', '.object-context',
            '.appian-rule-workspace', '.bottom-panel', '.bottom-tabs',
          ].map(measure).filter(Boolean),
        };
      });

      expect(layout.regions.length, 'editor regions must render').toBeGreaterThan(5);
      for (const region of layout.regions) {
        // Overflowing an ancestor that hides it is the defect: the content
        // disappears with no scrollbar to reach it.
        expect(
          region.right,
          `${region.selector} ends at ${region.right} past viewport ${layout.innerWidth} (${viewport.width}px)`,
        ).toBeLessThanOrEqual(layout.innerWidth + 1);
        if (region.clipped) {
          expect(
            ['auto', 'scroll'],
            `${region.selector} overflows but is ${region.overflowX} (${viewport.width}px)`,
          ).toContain(region.overflowX);
        }
      }

      expect(layout.chat, `assistant column ${layout.chat}px (${viewport.width}px)`)
        .toBeGreaterThanOrEqual(280);
      expect(layout.editor, `editor column ${layout.editor}px (${viewport.width}px)`)
        .toBeGreaterThanOrEqual(280);
      expect(layout.editorLeft, 'editor must be to the right of the assistant')
        .toBeGreaterThan(layout.chatLeft);

      const clippedControls = await page.evaluate(async () => {
        const editor = document.querySelector('.editor-shell');
        const controls = [...editor.querySelectorAll('button, [role="tab"]')];
        const failures = [];
        for (const control of controls) {
          control.scrollIntoView({ block: 'nearest', inline: 'nearest' });
          await new Promise((resolve) => requestAnimationFrame(resolve));
          const editorBox = editor.getBoundingClientRect();
          const controlBox = control.getBoundingClientRect();
          const rightLimit = Math.min(editorBox.right, window.innerWidth);
          if (controlBox.left < editorBox.left - 1 || controlBox.right > rightLimit + 1) {
            failures.push({
              name: control.getAttribute('aria-label') || control.textContent.trim(),
              left: Math.round(controlBox.left),
              right: Math.round(controlBox.right),
              editorLeft: Math.round(editorBox.left),
              editorRight: Math.round(editorBox.right),
              viewportRight: window.innerWidth,
            });
          }
        }
        return failures;
      });
      expect(
        clippedControls,
        `editor controls must fit or scroll fully into the editor at ${viewport.width}px`,
      ).toEqual([]);
    }
  });

  test('typed object controls call create, update, and delete routes', async ({ page }) => {
    const calls = await openWorkbench(page, true);
    await page.getByRole('treeitem', { name: 'APP_Test' }).click();
    await page.getByRole('button', { name: 'Object operations' }).click();

    await expect(page.getByRole('dialog', { name: 'Object operations' })).toBeVisible();
    await expect(page.getByLabel('Object type', { exact: true })).toHaveValue('expression_rule');
    await expect(page.getByLabel('Object ID')).toHaveValue(UUID);
    await expect(page.getByText('Object operation', { exact: true })).toBeVisible();
    await expect(page.getByLabel('Properties to change')).toBeVisible();

    await page.getByLabel('Object name').fill('APP_NewRule');
    await page.getByRole('button', { name: 'Preview create' }).click();
    await page.getByRole('button', { name: 'Preview update' }).click();
    await page.getByRole('button', { name: 'Preview delete' }).click();
    await page.getByRole('button', { name: 'Delete', exact: true }).click();
    await expect(page.getByText('Delete APP_NewRule?')).toBeVisible();
    await expect(page.getByText('This cannot be undone.')).toBeVisible();
    expect(calls.filter((call) => call.method === 'DELETE')).toHaveLength(1);
    await page.getByRole('button', { name: 'Confirm delete' }).click();

    const typedCalls = calls.filter((call) => call.path.startsWith('/api/typed-objects/'));
    expect(typedCalls.map((call) => call.method)).toEqual(['POST', 'PUT', 'DELETE', 'DELETE']);
    expect(typedCalls[0].path).toBe('/api/typed-objects/expression_rule');
    expect(typedCalls[1].path).toBe(`/api/typed-objects/expression_rule/${UUID}`);
    expect(typedCalls[2].path).toBe(`/api/typed-objects/expression_rule/${UUID}`);
    expect(typedCalls[3].path).toBe(`/api/typed-objects/expression_rule/${UUID}`);
  });

  test('object operations explain types without create examples', async ({ page }) => {
    const gatedTypes = [
      'business_process', 'process_report', 'robotic_task', 'robot_pool',
      'control_panel', 'control_panel_hierarchy_item', 'dashboard', 'ai_agent',
      'ai_skill', 'group_type', 'feed', 'event_consumer',
    ];
    await stubSidecar(page, {
      loaded: true,
      byType: Object.fromEntries(gatedTypes.map((type, index) => [type, [`gated-${index}`]])),
      uuidToName: Object.fromEntries(gatedTypes.map((type, index) => [`gated-${index}`, type])),
      objectTypeByUuid: Object.fromEntries(gatedTypes.map((type, index) => [`gated-${index}`, type])),
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'Object operations' }).click();

    const typePicker = page.getByLabel('Object type', { exact: true });
    await expect(typePicker.locator('option', { hasText: '(create unavailable)' })).toHaveCount(12);
    await typePicker.selectOption('ai_agent');
    await expect(page.getByText(/Create unavailable: no example/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Create', exact: true })).toBeDisabled();
  });

  test('model fields are pickers fed by the gateway, and degrade to text', async ({ page }) => {
    const models = [
      'bedrock.anthropic.claude-sonnet-5',
      'bedrock.anthropic.claude-opus-5',
      'azure.gpt-5.4',
    ];
    await stubSidecar(page, { loaded: true, models });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await openSettings(page);

    const primary = page.getByLabel('Primary model');
    await expect(primary).toHaveRole('combobox');
    for (const model of models) {
      await expect(primary.locator(`option[value="${model}"]`)).toHaveCount(1);
    }
    await primary.selectOption('azure.gpt-5.4');
    await expect(primary).toHaveValue('azure.gpt-5.4');
  });

  test('an unavailable model list degrades to a text field with the reason', async ({ page }) => {
    // A gateway that cannot list models must not lock the operator out.
    await stubSidecar(page, {
      loaded: true,
      modelsError: 'HTTP 502 from gateway: upstream refused',
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await openSettings(page);

    await expect(page.getByLabel('Primary model')).toHaveRole('textbox');
    await expect(page.getByText('upstream refused')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible();
  });

  test('a failed connection test shows the reason, not just the status', async ({ page }) => {
    await stubSidecar(page, {
      loaded: true,
      // Give the picker a model so its status line resolves before the click:
      // otherwise the model fetch and the test result race to the same region.
      models: ['bedrock.anthropic.claude-sonnet-5'],
      settingsTestError: 'HTTP 404 from https://gw/v1/chat/completions: route not found',
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await openSettings(page);
    await expect(page.getByLabel('Primary model')).toHaveRole('combobox');
    // exact: the Build grid renders object names as buttons, and APP_Test
    // would otherwise match this substring.
    await page.getByRole('button', { name: 'Test', exact: true }).click();

    // The old client dropped the body and rendered "502 Bad Gateway".
    await expect(page.getByText('route not found')).toBeVisible();
    await expect(page.getByText('Bad Gateway')).toHaveCount(0);
  });

  test('explorer groups every parsed object type, not just expression rules', async ({ page }) => {
    // R27 was previously proven against a single-type codebase, so a regression
    // in any other tier would have rendered nothing and still passed.
    const types = {
      constant: 'APP_MaxRetries',
      expression_rule: 'APP_CalculateTotal',
      integration: 'APP_PostRequest',
      interface: 'APP_RequestForm',
      process_model: 'APP_RequestApproval',
      record_type: 'APP_Request',
      site: 'APP_RequesterSite',
    };
    const byType = {};
    const uuidToName = {};
    const objectTypeByUuid = {};
    for (const [type, name] of Object.entries(types)) {
      const uuid = `uuid-${type}`;
      byType[type] = [uuid];
      uuidToName[uuid] = name;
      objectTypeByUuid[uuid] = type;
    }

    await stubSidecar(page, { loaded: true, byType, uuidToName, objectTypeByUuid });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const explorer = page.getByRole('complementary', { name: 'Object explorer' });
    await expect(explorer).toBeVisible();

    // The badge counts every object regardless of tier.
    await expect(explorer.locator('.count-badge')).toHaveText(String(Object.keys(types).length));

    const expectedGroups = [
      'Constant', 'Expression Rule', 'Integration', 'Interface',
      'Process Model', 'Record Type', 'Site',
    ];
    for (const label of expectedGroups) {
      await expect(page.getByRole('treeitem', { name: new RegExp(`^${label}`) })).toBeVisible();
    }
    for (const name of Object.values(types)) {
      await expect(page.getByRole('treeitem', { name, exact: true })).toBeVisible();
    }

    // Opening a non-content tier object must render its source, not blank.
    await page.getByRole('treeitem', { name: 'APP_Request', exact: true }).click();
    await expect(page.locator('.code-editor')).toContainText('record_type source for APP_Request');

    await page.getByRole('treeitem', { name: 'APP_RequestApproval', exact: true }).click();
    await expect(page.locator('.code-editor')).toContainText('process_model source for APP_RequestApproval');
  });

  test('the build grid matches Appian Designer columns and opens objects', async ({ page }) => {
    // Appian's Build grid is [checkbox] [type icon] Name | Description |
    // Last Modified. An export has no timestamp, so Last Modified is omitted
    // rather than filled in. See docs/APPIAN-DESIGNER-REFERENCE.md.
    const byType = { record_type: ['uuid-rt'], expression_rule: ['uuid-er'] };
    const uuidToName = { 'uuid-rt': 'APP_Request', 'uuid-er': 'APP_CalculateTotal' };
    await stubSidecar(page, {
      loaded: true,
      byType,
      uuidToName,
      objectTypeByUuid: { 'uuid-rt': 'record_type', 'uuid-er': 'expression_rule' },
      descriptions: { 'uuid-rt': 'Requests raised by staff' },
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });

    const grid = page.getByLabel('Build view');
    await expect(grid.getByRole('columnheader', { name: 'Name' })).toBeVisible();
    await expect(grid.getByRole('columnheader', { name: 'Description' })).toBeVisible();
    await expect(grid.getByRole('columnheader', { name: 'Last Modified' })).toHaveCount(0);
    await expect(grid.getByText('Requests raised by staff')).toBeVisible();

    // Filtering by the official type label narrows the grid.
    await grid.getByLabel('Filter by object type').selectOption('record_type');
    await expect(grid.getByRole('button', { name: 'APP_CalculateTotal' })).toHaveCount(0);

    await grid.getByRole('button', { name: 'APP_Request' }).click();
    await expect(page.locator('.code-editor')).toContainText('record_type source for APP_Request');
  });

  test('interface objects expose Appian design and expression modes', async ({ page }) => {
    const interfaceUuid = 'uuid-interface-designer';
    await stubSidecar(page, {
      loaded: true,
      byType: { interface: [interfaceUuid] },
      uuidToName: { [interfaceUuid]: 'APP_RequestForm' },
      objectTypeByUuid: { [interfaceUuid]: 'interface' },
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.getByRole('treeitem', { name: 'APP_RequestForm' }).click();

    await expect(page.getByRole('tab', { name: 'Design' })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByLabel('Component palette')).toBeVisible();
    await expect(page.getByLabel('Interface live view')).toBeVisible();
    await expect(page.getByLabel('Component configuration')).toBeVisible();
    await expect(page.getByText('Preview requires an Appian runtime')).toBeVisible();

    await page.getByRole('tab', { name: 'Expression' }).click();
    await expect(page.locator('.code-editor')).toBeVisible();
  });
});

// These components were each proved in isolation while they were built. They
// are re-covered here through the real shell, because the serialisation
// defect showed that a component passing against a stub proves nothing about
// the app the user runs.
test.describe('Appian Designer surfaces in the assembled workbench', () => {
  test('the unimplemented application rail and workflow tab are removed', async ({ page }) => {
    await openWorkbench(page, true);
    await expect(page.getByRole('navigation', { name: 'Application' })).toHaveCount(0);
    await expect(page.getByRole('tab', { name: 'Progress' })).toHaveCount(0);
  });

  test('expression rules use the Appian source, tests, and rule-input layout', async ({ page }) => {
    await openWorkbench(page, true);
    await page.getByRole('treeitem', { name: 'APP_Test' }).click();

    await expect(page.getByRole('region', { name: 'Rule source' })).toBeVisible();
    await expect(page.getByRole('region', { name: 'Rule tests' })).toBeVisible();
    await expect(page.getByRole('complementary', { name: 'Rule inputs' })).toBeVisible();
    await expect(page.getByRole('tab', { name: 'Test Cases (1)' })).toBeVisible();
    await expect(page.getByText('Positive total')).toBeVisible();
    await expect(page.getByText('Output equals 10')).toBeVisible();
    await expect(page.getByText('Integer')).toBeVisible();

    const sourcePane = page.getByRole('region', { name: 'Rule source' });
    const before = await sourcePane.evaluate((element) => element.getBoundingClientRect().width);
    await page.getByRole('separator', { name: 'Resize rule source' }).press('ArrowRight');
    const after = await sourcePane.evaluate((element) => element.getBoundingClientRect().width);
    expect(after).toBeGreaterThan(before);
  });

  test('problems use Appian severities and suppress guidance behind syntax errors', async ({ page }) => {
    await stubSidecar(page, {
      loaded: true,
      diagnostics: [
        { code: 'SAIL010', message: 'Unbalanced parenthesis', severity: 'error', line: 2 },
        { code: 'SAIL020', message: 'Unknown function a!nope', severity: 'warning', line: 3 },
        { code: 'SAIL032', message: "Declared input 'unused' is never used", severity: 'recommendation', line: 1 },
      ],
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.getByRole('treeitem', { name: 'APP_Test' }).click();
    await page.getByRole('tab', { name: /^Problems/ }).click();

    // A syntax error is present, so Appian suppresses the rest until it is
    // fixed, and says so rather than silently dropping findings.
    await expect(page.getByText('Unbalanced parenthesis')).toBeVisible();
    await expect(page.getByText(/suppress/i)).toBeVisible();
  });

  test('the expression toolbar formats source and is honest about live-only actions', async ({ page }) => {
    await openWorkbench(page, true);
    await page.getByRole('treeitem', { name: 'APP_Test' }).click();

    const editor = page.getByLabel('APP_Test source editor');
    await expect(editor).toBeVisible();

    // Formatting must be idempotent: a second press changes nothing.
    const format = page.getByRole('button', { name: /Format expression/i });
    await format.click();
    const once = await editor.inputValue();
    await format.click();
    expect(await editor.inputValue()).toBe(once);

    // Actions that need a live Appian environment are disabled, not fake.
    await expect(page.getByRole('button', { name: /Launch the Query Editor/i })).toBeDisabled();
  });

  test('the ad hoc test view never claims the rule was evaluated', async ({ page }) => {
    await openWorkbench(page, true);
    await page.getByRole('treeitem', { name: 'APP_Test' }).click();
    await page.getByRole('tab', { name: 'Ad Hoc Test' }).click();

    await expect(page.getByText('Test Inputs')).toBeVisible();
    await expect(page.getByText('Test Output')).toBeVisible();
    await expect(page.getByRole('button', { name: /TEST RULE/i })).toBeVisible();
    // The absence of an Appian engine has to be stated before the run, not
    // implied afterwards by a missing output value.
    await expect(page.getByText(/Static analysis only/i).first()).toBeVisible();
  });
});
