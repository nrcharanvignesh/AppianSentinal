// Renderer client for the typed CRUD routes at /api/typed-objects/{slug}.
// Slugs are the MCP slugs in appian_sentinel/models/object_registry.py
// (expression_rule, interface, record_type, integration, rule_folder, ...).

const SESSION_ID = 'default';

/**
 * @typedef {Object} TypedMutationResult
 * @property {'preview'|'created'|'updated'|'deleted'} status
 * @property {string} uuid
 * @property {string} [name] Create responses only.
 * @property {'create'|'update'} [action] Preview responses only.
 * @property {string} [file_path] Applied responses only.
 * @property {string} [template_uuid] Template-backed create responses only.
 * @property {string[]} [fields] Update preview: the field names that would change.
 */

/**
 * @typedef {Object} TypedDeleteResult
 * @property {'preview'|'deleted'} status
 * @property {string} uuid
 * @property {string} file_path
 * @property {string[]} dependents
 * @property {string[]} children
 * @property {boolean} forced True when force overrode a dependency block.
 */

/**
 * @typedef {Object} TypedObject
 * @property {string} uuid
 * @property {string} name
 * @property {string} object_type
 * @property {string[]} direct_dependencies
 * @property {string[]} direct_dependents
 */

/** Error carrying the backend mutation reason, not just the HTTP status. */
export class TypedCrudError extends Error {
  constructor(message, status, reason, details) {
    super(message);
    this.name = 'TypedCrudError';
    this.status = status;
    this.reason = reason;
    this.details = details;
  }
}

// ponytail: copied from lib/api.js, which does not export its request helper.
// Collapse into one helper when that module can be edited.
function runtimeApi() {
  if (typeof window !== 'undefined' && window.__SENTINEL_API__) {
    return window.__SENTINEL_API__;
  }
  const baseUrl = typeof window !== 'undefined' ? window.location.origin : '';
  return { baseUrl };
}

function requestHeaders(headers) {
  const result = new Headers(headers || {});
  const token = runtimeApi().token;
  if (token) result.set('X-Sentinel-Token', token);
  return result;
}

function segment(value, label) {
  const text = typeof value === 'string' ? value.trim() : '';
  if (!text) throw new TypedCrudError(`Missing ${label}.`, 0, 'missing_argument', { argument: label });
  return encodeURIComponent(text);
}

function query(params = {}) {
  return new URLSearchParams({ session_id: SESSION_ID, ...params }).toString();
}

function json(body) {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  };
}

// MutationError reaches the renderer as {"detail": {"reason": ..., ...}}, while
// routing failures send a plain string detail. Both must reach the operator as
// the cause, not as a bare status line.
function toError(response, body) {
  const detail = body && body.detail;
  const structured = detail && typeof detail === 'object' ? detail : null;
  const { reason = '', ...details } = structured || {};
  const message = typeof detail === 'string'
    ? detail
    : reason || (body && body.message) || `${response.status} ${response.statusText}`;
  return new TypedCrudError(message, response.status, reason, details);
}

async function request(path, options = {}) {
  const response = await fetch(`${runtimeApi().baseUrl}${path}`, {
    ...options,
    headers: requestHeaders(options.headers),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw toError(response, body);
  }
  if (response.status === 204) return null;
  return response.json();
}

/**
 * Read one typed object with its direct dependency edges.
 * @param {string} slug
 * @param {string} uuid
 * @returns {Promise<TypedObject>}
 */
export function getTypedObject(slug, uuid) {
  return request(
    `/api/typed-objects/${segment(slug, 'slug')}/${segment(uuid, 'uuid')}?${query()}`,
  );
}

/**
 * Create a typed object, optionally from a template object.
 * @param {string} slug
 * @param {{name: string, templateUuid?: string, fields?: Object, preview?: boolean}} body
 * @returns {Promise<TypedMutationResult>}
 */
export function createTypedObject(slug, body = {}) {
  const { name, templateUuid = '', fields = {}, preview = false } = body;
  if (typeof name !== 'string' || !name.trim()) {
    throw new TypedCrudError('Missing name.', 0, 'missing_argument', { argument: 'name' });
  }
  return request(`/api/typed-objects/${segment(slug, 'slug')}?${query()}`, json({
    name,
    template_uuid: templateUuid,
    fields,
    preview,
  }));
}

/**
 * Update fields on one typed object.
 * @param {string} slug
 * @param {string} uuid
 * @param {{fields?: Object, preview?: boolean}} body
 * @returns {Promise<TypedMutationResult>}
 */
export function updateTypedObject(slug, uuid, body = {}) {
  const { fields = {}, preview = false } = body;
  return request(
    `/api/typed-objects/${segment(slug, 'slug')}/${segment(uuid, 'uuid')}?${query()}`,
    { ...json({ fields, preview }), method: 'PUT' },
  );
}

/**
 * Delete one typed object. Defaults to a preview, matching the route default.
 * force is required when dependents or children exist.
 * @param {string} slug
 * @param {string} uuid
 * @param {{force?: boolean, preview?: boolean}} options
 * @returns {Promise<TypedDeleteResult>}
 */
export function deleteTypedObject(slug, uuid, options = {}) {
  const { force = false, preview = true } = options;
  return request(
    `/api/typed-objects/${segment(slug, 'slug')}/${segment(uuid, 'uuid')}`
    + `?${query({ force, preview })}`,
    { method: 'DELETE' },
  );
}

export const typedCrudApi = {
  get: getTypedObject,
  create: createTypedObject,
  update: updateTypedObject,
  remove: deleteTypedObject,
};
