'use strict';

const { contextBridge } = require('electron');

// Read the sidecar port passed via webPreferences.additionalArguments.
function readSidecarPort() {
  const arg = process.argv.find((a) => a.startsWith('--sentinel-port='));
  return arg ? arg.split('=')[1] : '8000';
}

const port = readSidecarPort();

contextBridge.exposeInMainWorld('__SENTINEL_API__', {
  baseUrl: `http://127.0.0.1:${port}`,
  wsUrl: `ws://127.0.0.1:${port}`,
  port,
});
