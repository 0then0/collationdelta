// Input safety only. Intl negotiation belongs exclusively to intl.mjs;
// persisted evidence is accepted only by the Python importer.
export const INPUT_LIMIT = 1024 * 1024;
export const EXPORT_LIMIT = 16 * 1024 * 1024;
export const DEADLINE_MS = 15000;
const encoder = new TextEncoder();
export const bytes = (value) => encoder.encode(JSON.stringify(value)).length;
function require(ok, message) {
  if (!ok) throw Error(message);
}
function fields(value, keys) {
  require(value && typeof value === 'object' && !Array.isArray(value), 'Expected a JSON object.');
  require(Object.keys(value).length === keys.length &&
    keys.every((k) => Object.hasOwn(value, k)), `Expected fields: ${keys.join(', ')}.`);
}
function scalar(value, depth = 0) {
  require(depth <= 32, 'JSON nesting exceeds 32 levels.');
  if (typeof value === 'string') {
    for (const c of value) {
      const point = c.codePointAt(0);
      require(point < 0xd800 || point > 0xdfff, 'Unpaired surrogate in JSON string.');
    }
  } else if (typeof value === 'number') {
    require(Number.isFinite(value), 'Non-finite JSON number.');
  } else if (value && typeof value === 'object') {
    for (const [key, item] of Object.entries(value)) {
      scalar(key, depth + 1);
      scalar(item, depth + 1);
    }
  }
}
export function parse(text) {
  const result = JSON.parse(text);
  // JSON.parse loses duplicate keys. Walk the already syntax-checked tokens to
  // reject them, including escaped spellings of the same key. No value rewriting.
  const tokens = text.match(/"(?:[^"\\]|\\.)*"|[{}\[\]:,]|[^\s{}\[\]:,]+/gs) ?? [];
  let index = 0;
  function walk(depth = 0) {
    require(depth <= 32, 'JSON nesting exceeds 32 levels.');
    const token = tokens[index++];
    if (token === '{') {
      const keys = new Set();
      while (tokens[index] !== '}') {
        const key = JSON.parse(tokens[index++]);
        require(!keys.has(key), `Duplicate JSON key: ${JSON.stringify(key)}.`);
        keys.add(key);
        index++; // colon
        walk(depth + 1);
        if (tokens[index] !== ',') break;
        index++;
      }
      index++;
    } else if (token === '[') {
      while (tokens[index] !== ']') {
        walk(depth + 1);
        if (tokens[index] !== ',') break;
        index++;
      }
      index++;
    } else if (/^-?\d/.test(token)) {
      const mantissa = token.split(/[eE]/)[0];
      require(Number(token) !== 0 ||
        !/[1-9]/.test(mantissa), 'Nonzero JSON number underflows to zero.');
    }
  }
  walk();
  scalar(result);
  return result;
}
export function validate(corpus, profile) {
  scalar(corpus);
  scalar(profile);
  require(bytes(corpus) <= INPUT_LIMIT &&
    bytes(profile) <= INPUT_LIMIT, 'Each input is limited to 1 MiB.');
  fields(corpus, ['version', 'entries']);
  require(corpus.version === 1, 'Unsupported corpus version.');
  require(Array.isArray(corpus.entries) &&
    corpus.entries.length >= 1 &&
    corpus.entries.length <= 256, 'Corpus requires 1–256 entries.');
  const ids = new Set();
  for (const entry of corpus.entries) {
    fields(entry, ['id', 'value']);
    require(typeof entry.id === 'string' &&
      entry.id.length > 0, 'Entry ID must be a nonempty string.');
    require(typeof entry.value === 'string', 'Entry value must be a string.');
    require(!ids.has(entry.id), 'Duplicate entry ID.');
    ids.add(entry.id);
  }
  const resultBudget =
    2 * corpus.entries.length * corpus.entries.reduce((sum, e) => sum + bytes(e.id), 0) +
    corpus.entries.length ** 2 * 160 +
    bytes(corpus) +
    bytes(profile) +
    16384;
  require(resultBudget <=
    EXPORT_LIMIT, 'Estimated export exceeds 16 MiB. Use shorter IDs or a smaller corpus.');
  fields(profile, ['version', 'contract', 'locale', 'options']);
  require(profile.version === 1, 'Unsupported profile version.');
  require(profile.contract === 'intl.collator.v1', 'This page captures intl.collator.v1 only.');
  require(typeof profile.locale === 'string' &&
    profile.locale.length > 0, 'Locale must be a nonempty string.');
  require(profile.options &&
    typeof profile.options === 'object' &&
    !Array.isArray(profile.options), 'Options must be an object.');
}
export async function read(file) {
  require(file && file.size <= INPUT_LIMIT, 'Select a JSON file of at most 1 MiB.');
  return parse(new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer()));
}
