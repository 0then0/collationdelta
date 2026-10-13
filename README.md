<p align="center"><img src="https://raw.githubusercontent.com/0then0/collationdelta/main/docs/icon.svg" width="88" height="88" alt="CollationDelta: two string relations joined by a delta" /></p>

# CollationDelta

**Detect string ordering and equality changes before a runtime upgrade.**

[![PyPI](https://img.shields.io/pypi/v/collationdelta)](https://pypi.org/project/collationdelta/)
![Python requirement](https://img.shields.io/badge/requires-Python%203.10%2B-blue)
![Runtime dependencies](https://img.shields.io/badge/core-runtime%20dependencies%200-green)
![License](https://img.shields.io/badge/license-Apache%202.0-blue)

CollationDelta records a comparator's results for your string corpus, saves a portable
capture, and compares captures offline. Capture a baseline in one runtime and the same
corpus and requested profile in another. The original runtimes are needed only to
create the captures.

It reports **equality merges, equality splits, and order reversals** as individual pair
witnesses. Equality means `compare(a, b) == 0`; it does not mean matching bytes or SQL
equality. A runtime version change alone is not drift.

The Python CLI has no runtime dependencies. The included Node and optional native
Chromium adapters implement the same strict `intl.collator.v1` contract. Custom
executable adapters can record an application's own comparator.

## Install

CollationDelta 0.2 requires Python **3.10+** on Linux or macOS. Node is needed for
Node capture; browser capture also requires an explicitly installed Chromium runtime
and optional Playwright toolchain. Windows adapter execution is unsupported.

### From source

```sh
git clone https://github.com/0then0/collationdelta.git
cd collationdelta
uv sync --locked --python 3.10
uv run --locked collationdelta --help
```

To install a local wheel:

```sh
uv build
uv venv /tmp/collationdelta-install --python 3.10
uv pip install --python /tmp/collationdelta-install/bin/python \
  dist/collationdelta-0.2.0-py3-none-any.whl
/tmp/collationdelta-install/bin/collationdelta --version
```

### Published releases

```sh
pip install collationdelta==0.2.0
collationdelta --version
```

Version 0.2.0 includes Node capture, optional native browser capture and Python 3.10
support. The older 0.1.0 release requires Python 3.12+ and includes Node capture only.

## Capture and compare

Node is required for this example. Run it from the source checkout:

```sh
adapter="$(uv run --locked collationdelta node-adapter)"
uv run --locked collationdelta capture \
  --corpus examples/corpus.json --profile examples/profile.json \
  --output /tmp/baseline.json -- node "$adapter"
uv run --locked collationdelta capture \
  --corpus examples/corpus.json --profile examples/profile.json \
  --output /tmp/current.json -- node "$adapter"
uv run --locked collationdelta compare /tmp/baseline.json /tmp/current.json \
  --json-output /tmp/report.json
```

Using the same runtime twice gives a control capture. To check an upgrade, run the
first capture in the old environment and the second in the new environment. Offline
comparison needs only Python and the two capture files.

For native browser capture, see the
[browser guide](https://github.com/0then0/collationdelta/blob/main/docs/browser-capture.md).
`collationdelta browser-adapter` prints the bundled browser adapter path. Browser
installation and executable selection are explicit; capture never downloads a browser.

## Inputs

Corpus JSON assigns a stable ID to each exact string:

```json
{
  "version": 1,
  "entries": [
    { "id": "rupee", "value": "₨" },
    { "id": "letters", "value": "Rs" },
    { "id": "zero", "value": "0" }
  ]
}
```

A requested profile identifies the comparator contract and configuration:

```json
{
  "version": 1,
  "contract": "intl.collator.v1",
  "locale": "en",
  "options": { "sensitivity": "base" }
}
```

IDs must be unique and nonempty. Duplicate values under different IDs are allowed.
Strings are preserved exactly: no trimming, case folding, normalization, or removal of
controls. Empty strings, U+0000, newlines, combining marks and supplementary characters
are supported. Invalid UTF-8 and unpaired surrogates are rejected.

Each capture requests **all n² ordered comparisons, including the diagonal**, for
1–256 entries. There is no sampling. JSON files are limited to 32 MiB; long strings
can reach file or transport limits before the entry limit.

The reference adapters fix `localeMatcher` to `lookup`. They support `sensitivity`,
`numeric`, `caseFirst`, `ignorePunctuation`, `usage`, and `collation`. Locale
canonicalization and supported lookup negotiation are allowed. Explicit options and
recognized `co`, `kn`, `kf` extensions must resolve, with explicit options taking
precedence. An unsupported locale or ignored explicit request returns `unsupported`,
a reason, any known resolved settings, and no comparisons.

See the [protocol specification](https://github.com/0then0/collationdelta/blob/main/docs/protocol.md)
for option values, schemas and custom adapters.

## Results and exit codes

Human reports show status, coverage and pair witnesses with IDs, escaped original
strings, Unicode code points and old/new signs. Findings appear once per unordered
pair. `--limit N` limits displayed findings only; full JSON evidence remains available.
`compare --format json` prints a deterministic report, and `--json-output FILE` saves it.

- **0:** complete `CAPTURED` or `STABLE`; informational commands.
- **1:** complete `DRIFT` with one or more findings.
- **2:** `INCOMPLETE` or `DRIFT_INCOMPLETE`. Valid partial or unsupported capture
  evidence is saved with this code.
- **3:** `ERROR`: invalid or incompatible inputs, corrupt digests, contradictory
  relations, malformed protocol, launch/crash/timeout or output-limit failure. Capture
  leaves an existing destination untouched.

Unknown comparisons are never treated as equality. Incomplete evidence can retain a
finding when either direction of the pair was successfully observed on each side;
this does not increase completed coverage or justify `STABLE`.

## Saved runtime examples

The [Node upgrade case](https://github.com/0then0/collationdelta/blob/main/docs/case-study.md)
compares official Node 18.20.8 and 24.21.0 binaries. It records an equality merge for
`₨` / `Rs` and an order reversal for `₨` / `0`, with repeated captures and offline
reports. An unchanged sorted snapshot hides the equality change; a small deduplication
example shows its application consequence.

The [Node/browser case](https://github.com/0then0/collationdelta/blob/main/docs/browser-capture.md#saved-nodebrowser-case)
uses eight Icelandic names, Node 24.21.0 and Google Chrome for Testing 156.0.8078.4 on
macOS arm64. Both support `en` and return `STABLE` on this corpus. Node supports `is`;
this browser reports no supported lookup match and known resolved locale `en-US`.
Strict offline comparison returns `INCOMPLETE`, zero findings. Fallback relations are
not substituted for missing strict observations.

These are finite comparison experiments, not production incidents or evidence about
every browser distribution. Newer builds may legitimately change locale support.

## Evidence and guarantees

Captures embed the original corpus, requested profile, effective settings, runtime and
adapter metadata, relation signs, explicit failures, coverage, invocation details,
limits, diagnostics and a SHA-256 digest. Loading revalidates the digest, schema,
coverage and finite-order consistency.

Compatible captures must have identical ID/value mappings and requested profiles,
including locale spelling. Entry order may differ. Effective settings may differ and
are reported for interpretation. Validation rejects nonzero self comparisons,
nonzero comparisons of identical strings, contradictory reciprocals/equality and
strict-order cycles. Partial validation checks only known constraints.

Transport bounds time and stdout/stderr output. The POSIX supervisor terminates the
adapter process group on completion and failure. Capture files are written through a
temporary file and atomically replaced after validation and serialization succeed.

A digest detects content alteration; it is not a signature or runtime authentication.
Version labels and user agents are observations or adapter claims. Preserve executable
provenance separately when it matters. Captures may include sensitive strings and argv.

## Scope

Stability on a finite corpus says nothing about all Unicode strings. Drift means a
change from the selected baseline, not a specification violation. CollationDelta does
not implement UCA, supply locale data, repair sorting, validate database indexes, or
establish SQL `UNIQUE`/`GROUP BY` behavior.

[Unicode Conformance](https://github.com/unicode-org/conformance) tests against
Unicode/CLDR specifications. CollationDelta uses your saved comparator baseline.
[glibc-unicode-sorting](https://github.com/ardentperf/glibc-unicode-sorting) studies
sorting changes through PostgreSQL over large datasets. CollationDelta uses a bounded
user corpus and explicit equality/order witnesses.

## Development

```sh
uv sync --locked --python 3.10
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest
uv build
```

See [testing and environments](https://github.com/0then0/collationdelta/blob/main/docs/validation.md)
for browser integration, supported-runtime coverage and packaging checks. See the
[changelog](https://github.com/0then0/collationdelta/blob/main/CHANGELOG.md) and
[release guide](https://github.com/0then0/collationdelta/blob/main/docs/releasing.md)
for release maintenance. The project uses the
[Apache-2.0 license](https://github.com/0then0/collationdelta/blob/main/LICENSE).
