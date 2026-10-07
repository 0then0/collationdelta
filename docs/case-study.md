# A real Node upgrade changes equality and order

The same requested comparator, `new Intl.Collator("en", { sensitivity: "base" })`, produces different relations in official Node 18.20.8 and 24.21.0 binaries. The corpus has three stable-ID records: `rupee` = `₨` (U+20A8), `letters` = `Rs` (U+0052 U+0073), and `zero` = `0` (U+0030). All nine ordered comparisons were completed and passed finite-model consistency checks on both sides.

## Verified runtime identities

The saved experiment uses official **darwin-arm64** archives:

- Node 18.20.8: `process.version` = `v18.20.8`, ICU `74.2`, CLDR `44.1`, Unicode `15.1`. Archive SHA-256: `bae4965d29d29bd32f96364eefbe3bca576a03e917ddbb70b9330d75f2cacd76`.
- Node 24.21.0: `process.version` = `v24.21.0`, ICU `78.3`, CLDR `48.0`, Unicode `17.0`. Archive SHA-256: `bed7eea5325e1108f32ce5228ddd6a5f0f08a499ee42aa7442aea583702f6057`.

The pins come from the official [18.20.8 checksums](https://nodejs.org/dist/v18.20.8/SHASUMS256.txt) and [24.21.0 checksums](https://nodejs.org/dist/v24.21.0/SHASUMS256.txt). The script checks both archive content and adapter-reported runtime/provider versions. It does not accept a version label supplied by the caller as a verified runtime.

Both effective profiles are identical:

```json
{
  "locale": "en",
  "usage": "sort",
  "sensitivity": "base",
  "ignorePunctuation": false,
  "collation": "default",
  "numeric": false,
  "caseFirst": "false"
}
```

## Findings

- **Equality merge:** `compare("₨", "Rs")` changes from -1 to 0. The report orients this witness by stable ID (`letters`, `rupee`), so its saved signs are +1 → 0.
- **Order reversal:** `compare("₨", "0")` changes from -1 to +1. The saved witness is (`rupee`, `zero`).

The full report contains exactly two findings, each once per unordered pair, with escaped strings, code points, stable finding IDs, runtime metadata, and effective settings. See [upgrade.report.json](../evidence/node-upgrade/upgrade.report.json) and [upgrade.txt](../evidence/node-upgrade/upgrade.txt).

Two independent captures were made on each runtime. Their normalized observations, effective settings, and runtime metadata matched exactly. Capture files differ in run timestamps and digests, as expected. Both saved same-runtime control reports are `STABLE`, with 9/9 comparisons. Offline comparison deserializes the saved old/new artifacts and requires no executable adapter.

## Why a sorted snapshot misses the equality change

On both binaries:

```js
const collator = new Intl.Collator('en', { sensitivity: 'base' });
['₨', 'Rs'].sort(collator.compare); // ['₨', 'Rs']
```

In the old runtime `₨` sorts before `Rs`; in the new runtime they are collation-equal and stable sorting preserves the input order. The identical output snapshot does not reveal the changed relation.

[application.mjs](../examples/application.mjs) is a **demonstration application example**. It sorts the same input and then removes adjacent values when `compare(previous, current) == 0`. Its output is `["₨", "Rs"]` on Node 18.20.8 and `["₨"]` on Node 24.21.0. The actual application outputs are saved in [experiment.json](../evidence/node-upgrade/experiment.json). This demonstrates a possible application consequence; it is not an external production incident.

The [ICU 76 release notes](https://unicode-org.github.io/icu/download/76.html) describe intervening CLDR root-collation changes and removal of currency-symbol tailoring, providing relevant historical context. This experiment changes the whole Node runtime and does **not** isolate ICU as the sole causal variable.

## Reproduce from official binaries

From the repository root:

```sh
uv sync --locked --python 3.12
uv run python scripts/reproduce_case.py \
  --runtime-dir /tmp/collationdelta-node \
  --output /tmp/collationdelta-evidence
```

This explicit experiment downloads two pinned archives, verifies their SHA-256, extracts the binaries, checks actual metadata, captures twice per runtime, evaluates both controls, compares the saved files offline, and runs the application demonstration. Its exit code is 0 when all assertions pass; the generated upgrade report itself has status `DRIFT` (a direct CLI compare returns 1).

Download pins are included for macOS arm64 and Linux arm64/x64. The committed captures were generated on macOS arm64. The same experiment passed on Linux arm64; its [compact summary](../evidence/node-upgrade/linux-experiment.json) records Linux archive identities and actual application outputs. Linux x64 pins were not executed locally. This script is independent of the normal unit suite, does not publish anything, and does not install or change system runtimes. It writes only the chosen runtime/evidence directories. Use a disposable output directory when keeping the committed evidence unchanged.

Reanalyse the committed captures without any Node executable:

```sh
uv run collationdelta compare evidence/node-upgrade/old.capture.json \
  evidence/node-upgrade/new.capture.json --json-output /tmp/upgrade-report.json
# Exit 1: DRIFT, two findings.
uv run collationdelta compare evidence/node-upgrade/new.capture.json \
  evidence/node-upgrade/new-repeat.capture.json
# Exit 0: STABLE.
```
