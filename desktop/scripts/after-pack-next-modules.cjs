'use strict';

const { cpSync, existsSync } = require('node:fs');
const { join } = require('node:path');

exports.default = async function afterPack(context) {
  const src = join(
    context.packager.projectDir,
    '.next',
    'standalone',
    'node_modules'
  );
  const dest = join(
    context.appOutDir,
    'resources',
    'next-standalone',
    'node_modules'
  );
  if (!existsSync(src)) {
    throw new Error(`Next standalone node_modules missing: ${src}`);
  }
  cpSync(src, dest, { recursive: true });
};
