'use strict';

const os = require('node:os');
const path = require('node:path');

const WORKSPACE_DIRNAME = 'AppianSentinel';

function localDocumentsDir() {
  return path.join(process.env.USERPROFILE || os.homedir(), 'Documents');
}

function resolveWorkspaceRoot() {
  const override = process.env.SENTINEL_WORKSPACE_DIR?.trim();
  return override || path.join(localDocumentsDir(), WORKSPACE_DIRNAME);
}

function resolveWorkspacePaths() {
  const workspace = resolveWorkspaceRoot();
  return Object.freeze({
    workspace,
    install: path.join(workspace, 'install'),
    projects: path.join(workspace, 'projects'),
    logs: path.join(workspace, 'logs'),
    config: path.join(workspace, 'config'),
    cache: path.join(workspace, 'cache'),
    tmp: path.join(workspace, 'tmp'),
    electron: path.join(workspace, 'electron'),
  });
}

module.exports = {
  localDocumentsDir,
  resolveWorkspaceRoot,
  resolveWorkspacePaths,
};
