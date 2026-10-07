// Demonstration application: sort, then remove adjacent collation-equal values.
const collator = new Intl.Collator('en', { sensitivity: 'base' });
const input = ['₨', 'Rs'];
const sorted = [...input].sort(collator.compare);
const distinct = sorted.filter(
  (value, i) => i === 0 || collator.compare(sorted[i - 1], value) !== 0,
);
console.log(
  JSON.stringify({
    runtime: {
      node: process.version,
      icu: process.versions.icu,
      cldr: process.versions.cldr,
      unicode: process.versions.unicode,
    },
    effective: collator.resolvedOptions(),
    input,
    sorted,
    distinct,
    rupeeToLetters: Math.sign(collator.compare('₨', 'Rs')),
    rupeeToZero: Math.sign(collator.compare('₨', '0')),
  }),
);
