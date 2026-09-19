// Appian Designer groups design objects into categories and colours the object
// icon by category. Categories and their memberships are documented; the exact
// hex values are not published, so these are chosen to match the named colours
// and to clear 4.5:1 contrast on both themes.
// See docs/APPIAN-DESIGNER-REFERENCE.md for the sources.

export const CATEGORIES = {
  data: { label: 'Data', color: '#b25a00' },
  process: { label: 'Process', color: '#1b3f73' },
  user: { label: 'User', color: '#1d659c' },
  rule: { label: 'Rule', color: '#6b3fa0' },
  integration: { label: 'Integration', color: '#1a7f37' },
  group: { label: 'Group', color: '#b3261e' },
  content: { label: 'Content management', color: '#2f5d3e' },
  notification: { label: 'Notification', color: '#8a6d00' },
};

// Keys are the object_type values the parser emits.
const TYPES = {
  business_process: ['Business Process', 'data'],
  data_store: ['Data Store', 'data'],
  data_type: ['Data Type', 'data'],
  record_type: ['Record Type', 'data'],

  process_model: ['Process Model', 'process'],
  process_model_folder: ['Process Model Folder', 'process'],
  process_report: ['Process Report', 'process'],
  robotic_task: ['Robotic Task', 'process'],
  robot_pool: ['Robot Pool', 'process'],

  control_panel: ['Control Panel', 'user'],
  dashboard: ['Dashboard', 'user'],
  interface: ['Interface', 'user'],
  portal: ['Portal', 'user'],
  report: ['Report', 'user'],
  site: ['Site', 'user'],
  tempo_report: ['Tempo Report', 'user'],

  ai_agent: ['AI Agent', 'rule'],
  ai_skill: ['AI Skill', 'rule'],
  constant: ['Constant', 'rule'],
  decision: ['Decision', 'rule'],
  expression_rule: ['Expression Rule', 'rule'],
  rule_folder: ['Rule Folder', 'rule'],
  translation_set: ['Translation Set', 'rule'],

  connected_system: ['Connected System', 'integration'],
  integration: ['Integration', 'integration'],
  web_api: ['Web API', 'integration'],
  event_consumer: ['Event Consumer', 'integration'],

  group: ['Group', 'group'],
  group_type: ['Group Type', 'group'],

  document: ['Document', 'content'],
  document_folder: ['Document Folder', 'content'],
  knowledge_center: ['Knowledge Center', 'content'],
  folder: ['Folder', 'content'],

  feed: ['Feed', 'notification'],
};

function titleCase(value) {
  return String(value || '')
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

// An export can contain a type this table does not list. Showing it plainly
// beats hiding it, so unknown types fall back to a neutral badge.
export function objectMeta(objectType) {
  const entry = TYPES[objectType];
  if (!entry) {
    return {
      label: titleCase(objectType) || 'Object',
      category: null,
      color: '#5a6672',
      abbreviation: String(objectType || '?').slice(0, 2).toUpperCase(),
    };
  }
  const [label, category] = entry;
  const words = label.split(' ');
  return {
    label,
    category,
    color: CATEGORIES[category].color,
    abbreviation: (words.length > 1
      ? words[0][0] + words[1][0]
      : label.slice(0, 2)).toUpperCase(),
  };
}

export function objectLabel(objectType) {
  return objectMeta(objectType).label;
}
