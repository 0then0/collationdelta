<p align="center"><img src="https://raw.githubusercontent.com/0then0/collationdelta/main/docs/icon.svg" width="88" height="88" alt="CollationDelta: two string relations joined by a delta" /></p>

# CollationDelta

**Detect string ordering and equality changes before a runtime upgrade.**

[![PyPI](https://img.shields.io/pypi/v/collationdelta)](https://pypi.org/project/collationdelta/)
![Python requirement](https://img.shields.io/badge/requires-Python%203.12%2B-blue)
![Runtime dependencies](https://img.shields.io/badge/core-runtime%20dependencies%200-green)
![License](https://img.shields.io/badge/license-Apache%202.0-blue)

CollationDelta records the actual comparison results for your finite string corpus through an executable adapter. Capture a baseline in the old environment, capture the same corpus and requested profile in the new environment, then compare the two files offline. The old runtime is no longer needed.

It reports equality merges, equality splits, and order reversals as individual pair witnesses. **Equality means `compare(a, b) == 0`**, not matching bytes, Unicode identity, or SQL equality. A runtime version change alone is not drift; a changed relation is drift even when version labels stay the same.

## Install and try

Python 3.12 or newer is required. Node is needed only to capture through the included `Intl.Collator` adapter. There are no Python runtime dependencies and no npm dependencies.

For a published release, install from PyPI:

```sh
pip install collationdelta==0.1.0
collationdelta --help
```

To try the source checkout, including the example input files:

```sh
git clone https://github.com/0then0/collationdelta.git
cd collationdelta
```

Then run:

```sh
uv sync --locked --python 3.12
uv run collationdelta --help
uv run collationdelta capture \
  --corpus examples/corpus.json --profile examples/profile.json \
  --output /tmp/baseline.json -- node "$(uv run collationdelta node-adapter)"
uv run collationdelta capture \
  --corpus examples/corpus.json --profile examples/profile.json \
  --output /tmp/current.json -- node "$(uv run collationdelta node-adapter)"
uv run collationdelta compare /tmp/baseline.json /tmp/current.json \
  --json-output /tmp/report.json
```

The same-runtime control returns `STABLE`. Use the old environment for the first command and the upgraded environment for the second to check an upgrade. The shell substitution above locates the installed adapter; CollationDelta itself runs the supplied argv without shell interpolation.

To build and install locally:

```sh
uv build
uv venv /tmp/collationdelta-install --python 3.12
uv pip install --python /tmp/collationdelta-install/bin/python dist/collationdelta-0.1.0-py3-none-any.whl
/tmp/collationdelta-install/bin/collationdelta --help
```

The Node adapter ships inside the wheel; `collationdelta node-adapter` prints its location after installation.

## Inputs and guarantees

Corpus JSON:

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

Profile JSON:

```json
{
  "version": 1,
  "contract": "intl.collator.v1",
  "locale": "en",
  "options": { "sensitivity": "base" }
}
```

IDs are unique, nonempty, stable strings. Duplicate values under different IDs are allowed. Values are preserved exactly: no trimming, case folding, normalization, control-character removal, or deduplication. Empty strings, embedded U+0000, newlines, combining marks, and supplementary characters are supported. Invalid UTF-8 and unpaired surrogates are rejected. JSON-escaped valid surrogate pairs decode to their scalar character.

The corpus must have **1–256 entries**. Each capture requests all `n²` ordered comparisons, including the diagonal, in a single process. A complete capture of 256 entries contains 65,536 comparisons. No sampling is used. JSON input/output files are limited to 32 MiB; long strings may reach transport or file limits before the entry limit.

The requested profile is distinct from adapter-reported effective settings and runtime/provider metadata. The Node adapter reports `process.version`, ICU, CLDR and Unicode versions when available, and `resolvedOptions()`. A custom adapter's version claim is evidence supplied by that adapter, not independent verification of its environment.

Supported Node options are `sensitivity`, `numeric`, `caseFirst`, `ignorePunctuation`, `usage`, and `collation`. The adapter delegates every comparison to `Intl.Collator`. It allows locale canonicalization and lookup negotiation, such as `EN-us` or a supported language with an unavailable region. Unsupported locales and silently ignored explicit collations are reported as unsupported. Explicit options and the recognized `co`, `kn`, `kf` locale extensions must resolve; explicit options take precedence over extensions. Other locale extensions do not define this adapter's comparison contract. See [the protocol guide](https://github.com/0then0/collationdelta/blob/main/docs/protocol.md) for the exact option values and custom adapters.

## Results and exit codes

Human reports begin with status and coverage: entries, expected/completed comparisons, missing/failed comparisons, and completeness. Each finding contains both IDs, safely escaped original values, Unicode code points, old/new relation signs, runtime metadata, and effective settings. Reciprocal comparisons validate the observation; findings appear once per unordered pair. A pair is a direct witness, not a claim of global minimization.

`compare --format json` emits a versioned, deterministic full report. `--json-output FILE` also saves it alongside human output. `--limit N` affects only the number of findings shown in human output; total counts and JSON evidence remain complete. The full JSON report contains shared old/new runtime and effective metadata in `sides`, referenced by every finding's old/new relations.

- **0:** `STABLE` for complete, valid, compatible captures; `CAPTURED` for a successful complete capture; informational commands.
- **1:** `DRIFT`, with complete observations and one or more findings.
- **2:** `INCOMPLETE` or `DRIFT_INCOMPLETE`. Capture also returns 2 for unsupported/unresolved configuration or missing/failed comparisons and saves the valid partial evidence.
- **3:** `ERROR`: invalid input, incompatible captures, inconsistent relations, digest failure, launch/crash/timeout/output limit failure, or malformed protocol. No new capture is written on a transport/protocol error.

Incomplete comparison preserves findings for a pair observed successfully in either direction on each side, even when diagonal or reciprocal observations are missing. Each side is independently oriented by stable IDs; the inferred reverse sign does not increase completed coverage. Unknown results are never equality. A successful process with missing pair responses produces explicit incomplete coverage; duplicate or unrequested pair responses are protocol errors. A crash with partial stdout is a transport error because a single-batch response cannot be trusted as a finished protocol document.

## Real runtime upgrade evidence

The [reproducible case study](https://github.com/0then0/collationdelta/blob/main/docs/case-study.md) compares the official Node **18.20.8 / ICU 74.2 / CLDR 44.1** and **24.21.0 / ICU 78.3 / CLDR 48.0** binaries with the same `en` / `sensitivity: base` profile. Saved captures and reports are in [evidence/node-upgrade](https://github.com/0then0/collationdelta/tree/main/evidence/node-upgrade). They show an equality merge for `₨` / `Rs` and an order reversal for `₨` / `0`, a same-runtime control, repeated observations, and offline analysis.

The two-element sorted snapshot `["₨", "Rs"]` stays the same while equality changes. The included **demonstration application example** sorts and removes adjacent collation-equal strings; its result changes from two records to one. This is a demonstration, not an external production incident. The experiment upgrades the entire Node runtime and does not isolate the effect of ICU alone.

## Evidence and consistency

Captures embed corpus, requested profile, effective settings, normalized signs, explicit failures, coverage, runtime/adapter metadata, invocation argv, working directory, platform, UTC timestamp, limits, diagnostics, and a SHA-256 content digest. The digest detects accidental or uncoordinated content alteration; anyone able to edit a capture can recompute it. It is not a signature or proof of runtime authenticity. Environment variables, application configuration files, and executable contents are not bundled; preserve them separately when needed for reproduction. Captures may contain sensitive corpus values and command arguments.

On load, CollationDelta validates the schema, digest, observations, and recomputed coverage. Corpus ID/value mappings must match exactly, although record order may differ. Requested profiles must match exactly, including locale spelling; canonicalization is an adapter operation during capture. Effective settings may differ and are exposed for interpretation rather than silently requiring agreement.

The consistency check treats identical string values under different IDs as equal and rejects nonzero comparisons between them, nonzero self comparisons, inconsistent reciprocal results, contradictions in equality components, and cycles of strict order. Union-find constructs equality components, then topological traversal checks the graph of strict relations. Time is `O(n² α(n))` and memory `O(n²)` for a full corpus; `α(n)` is the near-constant inverse Ackermann cost of union-find. For partial observations this checks whether known relations can extend to a total preorder; it cannot verify unknown relations. Contradictory observations are errors, never equivalence classes or stability claims.

## Related work and boundaries

[Unicode Conformance](https://github.com/unicode-org/conformance) provides data-driven testing against Unicode/CLDR specifications across implementations. CollationDelta shares the idea of executable comparison observations, but its reference is your saved application baseline rather than specification conformance.

[glibc-unicode-sorting](https://github.com/ardentperf/glibc-unicode-sorting) studies sorting changes across OS/ICU versions through PostgreSQL, including sorted-output checksums over large datasets. CollationDelta uses a bounded user corpus and explicit equality/order pair witnesses. The distinction is the combination of **your corpus, your actual application comparator, a portable baseline, and separate equality drift detection**. It does not imply that other tools cannot compare pairs or accept custom data.

[ICU 76 release notes](https://unicode-org.github.io/icu/download/76.html) document root-collation changes, including currency-symbol ordering; [the ICU Collation API guide](https://unicode-org.github.io/icu/userguide/collation/api.html) describes direct string comparisons and warns that keys from different collators are not comparable. CollationDelta compares observed relation signs, never persisted sort-key bytes, and adds no bytewise tiebreaker. The release notes provide context for the case, not proof of its isolated cause.

Stability on a finite corpus says nothing about all Unicode strings. Drift means a change relative to the selected baseline, not an error in the new implementation. Node comparison evidence does not establish SQL `UNIQUE`, `GROUP BY`, or any database collation's behavior. This tool checks neither physical database index correctness nor provider/database rebuild requirements.

v0.1 is a local capture/compare CLI. It does not implement UCA, offer a universal conformance suite, fuzz all Unicode, scan production databases, manage runtimes/Docker, migrate databases, run `REINDEX`, accept new baselines automatically, or recommend remediation without application evidence. It has one reference Node adapter and one custom-adapter example; no web UI, daemon, SaaS, or plugin registry.

## Development and validation

```sh
uv sync --locked --python 3.12
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest
uv build
```

Tests cover drift types, Unicode preservation, finite-order consistency, strict protocol/transport failures, partial evidence, corruption, deterministic reports, offline comparison, and the actual Node adapter. Unit tests use synthetic fixtures only for controlled core and failure cases; the historical upgrade uses official binaries. Unit tests never download historical runtimes.

Ruff checks Python errors, imports, Python 3.12 modernization, and common bug patterns with a 100-column formatting target. To apply formatting, run `uv run --locked ruff format .`. The formatter controls wrapping; long strings and comments are exempt from the linter's line-length check.

The CLI's POSIX process transport targets Linux and macOS. CI is configured for both with Python 3.12–3.14 and Node 24.21.0, including clean-wheel installation. Local verification results and unverified platform claims are recorded in the [validation report](https://github.com/0then0/collationdelta/blob/main/docs/validation.md). Windows adapter execution is unsupported in v0.1.

The existing [Apache-2.0 license](https://github.com/0then0/collationdelta/blob/main/LICENSE) applies to this project. Node downloads remain separate, external artifacts with their own licensing.

## Releases

Release notes are in the [changelog](https://github.com/0then0/collationdelta/blob/main/CHANGELOG.md). Maintainers can follow the [release guide](https://github.com/0then0/collationdelta/blob/main/docs/releasing.md) to publish a version through PyPI Trusted Publishing.
