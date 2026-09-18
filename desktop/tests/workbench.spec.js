const { test, expect } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

const SCREENSHOT_DIR = path.join(__dirname, '..', 'test-results');
const SCREENSHOT_1024 = path.join(SCREENSHOT_DIR, 'workbench-loaded-1024x640.png');
const SCREENSHOT_1440 = path.join(SCREENSHOT_DIR, 'workbench-loaded-1440x900.png');
const SCREENSHOT_EMPTY = path.join(SCREENSHOT_DIR, 'workbench-empty-1440x900.png');
const SCREENSHOT_LOADING = path.join(SCREENSHOT_DIR, 'workbench-loading-1440x900.png');
const SCREENSHOT_ERROR = path.join(SCREENSHOT_DIR, 'workbench-error-1440x900.png');
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
  } = typeof options === 'boolean' ? { loaded: options } : options;
  const calls = [];
  await page.routeWebSocket('**/ws**', () => {});
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const routeCall = { method: request.method(), path: url.pathname, body: null };
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
          by_type: { expression_rule: [UUID, HELPER_UUID, HELPER_UUID_2] },
          uuid_to_name: {
            [UUID]: 'APP_Test',
            [HELPER_UUID]: 'APP_Helper',
            [HELPER_UUID_2]: 'APP_Helper',
          },
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
      body = {
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
    } else if (url.pathname === `/api/objects/${UUID}`) {
      body = {
        uuid: UUID,
        name: 'APP_Test',
        object_type: 'expression_rule',
        definition: routeCall.body?.definition || SOURCE,
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
    } else if (url.pathname === '/api/story') {
      body = { title: 'Uploaded story' };
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
  });

  test('object explorer region exists and shows empty state', async ({ page }) => {
    await openWorkbench(page);
    const explorer = page.getByRole('complementary', { name: 'Object explorer' });
    await expect(explorer).toBeVisible();
    await expect(explorer).toContainText(EMPTY_EXPLORER);
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
      'Could not load objects: sidecar_unavailable',
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

    const outline = page.getByLabel('Symbol outline');
    await expect(outline).toContainText('value');
    await expect(outline).toContainText('total');
    await expect(outline).toContainText('a!textField');

    const editor = page.getByLabel('APP_Test source editor');
    await editor.fill(`${SOURCE}\n1`);
    await expect(page.getByRole('button', { name: 'Save' })).toBeEnabled();
    await editor.press('Control+z');
    await expect(editor).toHaveValue(SOURCE);
    await expect(page.getByRole('button', { name: 'Save' })).toBeDisabled();
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
    const save = page.getByRole('button', { name: 'Save' });
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
    await page.getByLabel('APP_Test').check();

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
        expected: null,
      }],
      preview: true,
    });
    expect(bulkCalls[1].body.preview).toBe(false);
  });

  test('history restore and PDF upload use correct routes', async ({ page }) => {
    const calls = await openWorkbench(page, true);
    await page.getByRole('tab', { name: 'History' }).click();
    const restore = page.getByRole('button', { name: 'Restore' });
    await expect(restore).toBeEnabled();
    await restore.click();
    await expect(page.getByText('Restore error: workspace_not_clean')).toBeVisible();

    await page.getByRole('tab', { name: 'ADO' }).click();
    await page.getByLabel('User story PDF').setInputFiles({
      name: 'story.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.4 test'),
    });
    await expect(page.getByText('PDF story.pdf loaded.')).toBeVisible();

    expect(calls.some((call) => (
      call.method === 'POST'
      && call.path === '/api/history/restore'
      && call.body?.revision === 'revision-1'
    ))).toBeTruthy();
    expect(calls.some((call) => call.method === 'POST' && call.path === '/api/story')).toBeTruthy();
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
      { width: 1024, height: 640, path: SCREENSHOT_1024 },
      { width: 1440, height: 900, path: SCREENSHOT_1440 },
    ]) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.waitForTimeout(150);
      const overflow = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }));
      expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 1);
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
  });
});
