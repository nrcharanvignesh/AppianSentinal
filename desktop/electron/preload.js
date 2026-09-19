'use strict';

const { contextBridge } = require('electron');

function desktopArgument(name, fallback) {
  const prefix = `--${name}=`;
  const raw = process.argv.find((value) => value.startsWith(prefix));
  if (!raw) return fallback;
  try {
    return decodeURIComponent(raw.slice(prefix.length));
  } catch {
    return fallback;
  }
}

const api = Object.freeze({
  baseUrl: desktopArgument('sentinel-base-url', 'http://127.0.0.1:7842'),
  wsUrl: desktopArgument('sentinel-ws-url', 'ws://127.0.0.1:7842'),
  port: Number(desktopArgument('sentinel-port', '7842')),
  token: desktopArgument('sentinel-token', ''),
});

contextBridge.exposeInMainWorld('__SENTINEL_API__', api);
