#!/usr/bin/env node
// One batch, no npm dependencies. All comparisons call the actual Intl API.
import fs from 'node:fs';
import { observeIntl } from './intl.mjs';

const runtime = {
  node: process.version,
  icu: process.versions.icu ?? null,
  cldr: process.versions.cldr ?? null,
  unicode: process.versions.unicode ?? null,
  platform: process.platform,
  arch: process.arch,
};
const adapter = {
  name: 'collationdelta-intl',
  version: '0.2.0',
  contract: 'intl.collator.v1',
};

try {
  const request = JSON.parse(fs.readFileSync(0, 'utf8'));
  const response = observeIntl(request);
  response.runtime = { ...runtime, ...response.runtime };
  response.adapter = adapter;
  process.stdout.write(JSON.stringify(response) + '\n');
} catch (error) {
  process.stderr.write(`adapter error: ${error.message}\n`);
  process.exitCode = 1;
}
