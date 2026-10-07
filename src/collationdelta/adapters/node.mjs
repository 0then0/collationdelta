#!/usr/bin/env node
// One batch, no npm dependencies. All comparisons call the actual Intl API.
import fs from 'node:fs';

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
  version: '0.1.0',
  contract: 'intl.collator.v1',
};

function observe(request) {
  if (request.protocol_version !== 1 || !Array.isArray(request.corpus?.entries)) {
    throw new Error('invalid request/protocol version');
  }
  const profile = request.profile;
  const base = { protocol_version: 1, runtime, adapter, effective: null, results: [] };
  function unsupported(reason, effective = null) {
    return { ...base, status: 'unsupported', reason, effective };
  }
  if (profile?.contract !== adapter.contract)
    return unsupported('unsupported application comparator contract');
  const allowed = {
    sensitivity: ['base', 'accent', 'case', 'variant'],
    caseFirst: ['upper', 'lower', 'false'],
    usage: ['sort', 'search'],
    numeric: 'boolean',
    ignorePunctuation: 'boolean',
    collation: 'string',
  };
  if (
    !profile.options ||
    typeof profile.options !== 'object' ||
    Array.isArray(profile.options)
  ) {
    return unsupported('options must be an object');
  }
  for (const [key, value] of Object.entries(profile.options)) {
    if (!(key in allowed)) return unsupported(`unsupported option: ${key}`);
    const rule = allowed[key];
    if (Array.isArray(rule) ? !rule.includes(value) : typeof value !== rule) {
      return unsupported(`invalid option value: ${key}`);
    }
  }
  let canonical, collator;
  try {
    canonical = Intl.getCanonicalLocales(profile.locale)[0];
    if (
      !canonical ||
      !Intl.Collator.supportedLocalesOf([canonical], { localeMatcher: 'lookup' }).length
    ) {
      return unsupported('requested locale has no supported lookup match');
    }
    collator = new Intl.Collator(canonical, {
      ...profile.options,
      localeMatcher: 'lookup',
    });
  } catch (error) {
    return unsupported(`Intl configuration rejected: ${error.message}`);
  }
  const effective = collator.resolvedOptions();
  const locale = new Intl.Locale(canonical);
  const expectedCollation = profile.options.collation ?? locale.collation;
  if (expectedCollation && expectedCollation !== effective.collation) {
    return unsupported(
      `requested collation ${expectedCollation} did not resolve`,
      effective,
    );
  }
  // Unicode extensions are requests too. Unsupported kn/kf must not disappear.
  const extensions = new Map();
  const u = canonical.toLowerCase().split('-x-')[0].split('-u-')[1]?.split('-') ?? [];
  for (let i = 0; i < u.length; i++) {
    if (u[i].length === 2) {
      const key = u[i];
      const parts = [];
      while (i + 1 < u.length && u[i + 1].length !== 2) parts.push(u[++i]);
      extensions.set(key, parts.join('-') || 'true');
    }
  }
  const expected = { ...profile.options };
  if (!('numeric' in expected) && extensions.has('kn')) {
    if (!['true', 'false'].includes(extensions.get('kn')))
      return unsupported('unsupported kn extension', effective);
    expected.numeric = extensions.get('kn') === 'true';
  }
  if (!('caseFirst' in expected) && extensions.has('kf'))
    expected.caseFirst = extensions.get('kf');
  for (const [key, value] of Object.entries(expected)) {
    if (effective[key] !== value)
      return unsupported(`requested ${key} did not resolve`, effective);
  }
  const results = [];
  for (const left of request.corpus.entries) {
    for (const right of request.corpus.entries) {
      try {
        const value = collator.compare(left.value, right.value);
        if (!Number.isFinite(value)) throw new Error('non-finite comparator return');
        results.push({ left: left.id, right: right.id, status: 'ok', value });
      } catch (error) {
        results.push({
          left: left.id,
          right: right.id,
          status: 'error',
          reason: error.message,
        });
      }
    }
  }
  return { ...base, status: 'ok', effective, results };
}

try {
  const request = JSON.parse(fs.readFileSync(0, 'utf8'));
  process.stdout.write(JSON.stringify(observe(request)) + '\n');
} catch (error) {
  process.stderr.write(`adapter error: ${error.message}\n`);
  process.exitCode = 1;
}
