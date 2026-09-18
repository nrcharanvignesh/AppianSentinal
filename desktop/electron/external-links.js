'use strict';

const { shell } = require('electron');

const INTERNAL_HOSTS = new Set(['127.0.0.1', 'localhost']);

function isExternalHttp(url) {
  try {
    const parsed = new URL(url);
    return (
      (parsed.protocol === 'http:' || parsed.protocol === 'https:') &&
      !INTERNAL_HOSTS.has(parsed.hostname)
    );
  } catch {
    return false;
  }
}

function applyExternalLinkPolicy(win) {
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (isExternalHttp(url)) {
      void shell.openExternal(url);
      return { action: 'deny' };
    }
    return { action: 'allow' };
  });
  win.webContents.on('will-navigate', (event, url) => {
    if (isExternalHttp(url)) {
      event.preventDefault();
      void shell.openExternal(url);
    }
  });
}

module.exports = { applyExternalLinkPolicy };
