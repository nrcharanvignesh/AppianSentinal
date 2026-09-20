const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

// The client is an ES module that Node cannot require, so it is injected into
// the page as a module script and driven through intercepted requests. No
// Electron process and no sidecar are involved.
const CLIENT_SOURCE = fs.readFileSync(
  path.join(__dirname, '..', 'lib', 'typed-crud-api.js'),
  'utf8',
);
const EXPORTS = [
  'getTypedObject',
  'createTypedObject',
  'updateTypedObject',
  'deleteTypedObject',
  'typedCrudApi',
];
// A slash and a space prove the uuid is encoded rather than pasted into the URL.
const UUID = '_a-1111 2222/3333';
const ENCODED_UUID = encodeURIComponent(UUID);

async function loadClient(page, respond) {
  const calls = [];
  await page.routeWebSocket('**/ws**', () => {});
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (!url.pathname.startsWith('/api/typed-objects')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
      return;
    }
    const call = {
      method: request.method(),
      pathname: url.pathname,
      params: Object.fromEntries(url.searchParams),
      token: request.headers()['x-sentinel-token'] || '',
      body: request.postData() ? request.postDataJSON() : null,
    };
    calls.push(call);
    const reply = (respond && respond(call)) || {};
    await route.fulfill({
      status: reply.status || 200,
      contentType: 'application/json',
      body: JSON.stringify(reply.body === undefined ? {} : reply.body),
    });
  });
  await page.addInitScript(() => {
    window.__SENTINEL_API__ = { baseUrl: '', token: 'test-token' };
  });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.addScriptTag({
    type: 'module',
    content: `${CLIENT_SOURCE}\nwindow.__typedCrud = { ${EXPORTS.join(', ')} };`,
  });
  await page.waitForFunction(() => Boolean(window.__typedCrud));
  return calls;
}

function call(page, name, args) {
  return page.evaluate(async ([fn, params]) => {
    try {
      return { ok: true, value: await window.__typedCrud[fn](...params) };
    } catch (error) {
      return {
        ok: false,
        error: {
          name: error.name,
          message: error.message,
          status: error.status,
          reason: error.reason,
          details: error.details,
        },
      };
    }
  }, [name, args]);
}

test.describe('typed CRUD renderer client contract', () => {
  test('create posts the route payload and carries the session and token', async ({ page }) => {
    const created = {
      status: 'created',
      uuid: 'new-uuid',
      name: 'APP_NewRule',
      file_path: 'rules/new-uuid.xml',
    };
    const calls = await loadClient(page, () => ({ body: created }));

    const result = await call(page, 'createTypedObject', ['expression_rule', {
      name: 'APP_NewRule',
      templateUuid: 'template-uuid',
      fields: { definition: '2 + 2' },
    }]);

    expect(result.ok, JSON.stringify(result.error)).toBeTruthy();
    expect(result.value).toEqual(created);
    expect(calls).toHaveLength(1);
    expect(calls[0].method).toBe('POST');
    expect(calls[0].pathname).toBe('/api/typed-objects/expression_rule');
    expect(calls[0].params).toEqual({ session_id: 'default' });
    expect(calls[0].token).toBe('test-token');
    // Parity with TypedCreateBody: every field present, preview defaulted off.
    expect(calls[0].body).toEqual({
      name: 'APP_NewRule',
      template_uuid: 'template-uuid',
      fields: { definition: '2 + 2' },
      preview: false,
    });
  });

  test('create preview sends preview true and returns the preview result', async ({ page }) => {
    const preview = {
      status: 'preview',
      uuid: 'new-uuid',
      name: 'APP_NewRule',
      action: 'create',
      template_uuid: 'template-uuid',
    };
    const calls = await loadClient(page, () => ({ body: preview }));

    const result = await call(page, 'createTypedObject', ['interface', {
      name: 'APP_NewRule',
      preview: true,
    }]);

    expect(result.value).toEqual(preview);
    expect(calls[0].body).toEqual({
      name: 'APP_NewRule',
      template_uuid: '',
      fields: {},
      preview: true,
    });
  });

  test('get and update address one object by encoded uuid', async ({ page }) => {
    const calls = await loadClient(page, (received) => ({
      body: received.method === 'GET'
        ? { uuid: UUID, name: 'APP_Rule', object_type: 'expression_rule', direct_dependencies: [], direct_dependents: [] }
        : { status: 'updated', uuid: UUID, file_path: 'rules/rule.xml' },
    }));

    const read = await call(page, 'getTypedObject', ['expression_rule', UUID]);
    expect(read.ok, JSON.stringify(read.error)).toBeTruthy();
    expect(read.value.uuid).toBe(UUID);

    const updated = await call(page, 'updateTypedObject', ['expression_rule', UUID, {
      fields: { name: 'APP_Renamed' },
    }]);
    expect(updated.value).toEqual({ status: 'updated', uuid: UUID, file_path: 'rules/rule.xml' });

    expect(calls.map((item) => item.method)).toEqual(['GET', 'PUT']);
    for (const item of calls) {
      expect(item.pathname).toBe(`/api/typed-objects/expression_rule/${ENCODED_UUID}`);
      expect(item.params).toEqual({ session_id: 'default' });
    }
    expect(calls[0].body).toBeNull();
    // Parity with TypedUpdateBody.
    expect(calls[1].body).toEqual({ fields: { name: 'APP_Renamed' }, preview: false });
  });

  test('delete previews by default and sends force as a query flag', async ({ page }) => {
    const deleted = {
      status: 'deleted',
      uuid: UUID,
      file_path: 'rules/rule.xml',
      dependents: ['caller-uuid'],
      children: [],
      forced: true,
    };
    const calls = await loadClient(page, (received) => ({
      body: received.params.preview === 'true'
        ? { ...deleted, status: 'preview', forced: false }
        : deleted,
    }));

    const previewed = await call(page, 'deleteTypedObject', ['expression_rule', UUID]);
    expect(previewed.value.status).toBe('preview');

    const applied = await call(page, 'deleteTypedObject', ['expression_rule', UUID, {
      force: true,
      preview: false,
    }]);
    expect(applied.value).toEqual(deleted);

    expect(calls.map((item) => item.method)).toEqual(['DELETE', 'DELETE']);
    expect(calls[0].params).toEqual({ session_id: 'default', force: 'false', preview: 'true' });
    expect(calls[1].params).toEqual({ session_id: 'default', force: 'true', preview: 'false' });
    expect(calls[1].body).toBeNull();
  });

  test('errors expose the mutation reason and its details, not the status line', async ({ page }) => {
    const calls = await loadClient(page, (received) => (
      received.method === 'DELETE'
        ? {
          status: 400,
          body: {
            detail: {
              reason: 'dependency_blocked',
              object_uuid: UUID,
              dependents: ['caller-uuid'],
              children: [],
            },
          },
        }
        : { status: 404, body: { detail: 'Unknown object type: nope' } }
    ));

    const blocked = await call(page, 'deleteTypedObject', ['expression_rule', UUID, { preview: false }]);
    expect(blocked.ok).toBeFalsy();
    expect(blocked.error.name).toBe('TypedCrudError');
    expect(blocked.error.message).toBe('dependency_blocked');
    expect(blocked.error.status).toBe(400);
    expect(blocked.error.reason).toBe('dependency_blocked');
    expect(blocked.error.details).toEqual({
      object_uuid: UUID,
      dependents: ['caller-uuid'],
      children: [],
    });

    const unknown = await call(page, 'getTypedObject', ['nope', 'some-uuid']);
    expect(unknown.ok).toBeFalsy();
    expect(unknown.error.message).toBe('Unknown object type: nope');
    expect(unknown.error.status).toBe(404);
    expect(unknown.error.reason).toBe('');

    expect(calls).toHaveLength(2);
  });

  test('a missing slug, uuid, or name fails before any request is sent', async ({ page }) => {
    const calls = await loadClient(page);

    for (const [name, args] of [
      ['getTypedObject', ['expression_rule', '']],
      ['updateTypedObject', ['', UUID, {}]],
      ['deleteTypedObject', ['expression_rule', '   ']],
      ['createTypedObject', ['expression_rule', { name: '' }]],
    ]) {
      const result = await call(page, name, args);
      expect(result.ok, `${name} must reject`).toBeFalsy();
      expect(result.error.reason).toBe('missing_argument');
    }
    expect(calls).toEqual([]);
  });

  test('the grouped export is the same contract as the named functions', async ({ page }) => {
    await loadClient(page, () => ({ body: { status: 'preview', uuid: 'u1', action: 'create' } }));
    const shape = await page.evaluate(() => {
      const group = window.__typedCrud.typedCrudApi;
      return {
        keys: Object.keys(group).sort(),
        matches: group.get === window.__typedCrud.getTypedObject
          && group.create === window.__typedCrud.createTypedObject
          && group.update === window.__typedCrud.updateTypedObject
          && group.remove === window.__typedCrud.deleteTypedObject,
      };
    });
    expect(shape.keys).toEqual(['create', 'get', 'remove', 'update']);
    expect(shape.matches).toBeTruthy();
  });
});
