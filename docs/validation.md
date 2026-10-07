# v0.1 validation

This report records checks actually completed on **7 October 2026**. GitHub Actions is configured, but no hosted CI run was performed during this local validation.

## Verified environments

- macOS arm64: Python **3.12.15**, **3.13.15**, **3.14.8**, with Node **24.21.0 / ICU 78.3 / CLDR 48.0 / Unicode 17.0**. The full suite passed on each interpreter.
- Linux arm64, Debian bookworm: Python **3.14.8**, with the official Node **24.21.0** binary and the same provider versions. The full suite passed against the installed wheel in a disposable container.
- The Node adapter's **20 integration tests** also passed against official Node **18.20.8 / ICU 74.2 / CLDR 44.1 / Unicode 15.1** on macOS arm64.

The full suite contains **102 tests**. Linux execution used the existing Python image `python@sha256:c8137f4c460908c8763f281c8f22c431eb5c538514ba9553fc3a89c06b7cfb88`. The checkout was mounted read-only. The wheel was installed without dependencies in a fresh environment; pytest was added only after exercising the installed CLI.

## Core and adapter verification

Ruff **0.16.10** was added as a development dependency. Python sources were formatted and lint findings corrected. The following checks passed after these changes:

```sh
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -q
# 102 passed on macOS arm64 / Python 3.12.15.
```

The configuration targets Python 3.12 and 100 columns, with rules `E`, `F`, `I`, `UP`, `B`, and `RUF`. `E501` is excluded so that long strings and comments do not conflict with the formatter's wrapping policy. CI runs both lint and format checks before tests.

The source environment was established with `uv sync --python 3.12`; later runs used the resulting lockfile:

```sh
uv run --locked pytest -q
UV_PROJECT_ENVIRONMENT=/tmp/collationdelta-py313 uv sync --locked --python 3.13
UV_PROJECT_ENVIRONMENT=/tmp/collationdelta-py313 uv run --locked pytest -q
UV_PROJECT_ENVIRONMENT=/tmp/collationdelta-py314 uv sync --locked --python 3.14
UV_PROJECT_ENVIRONMENT=/tmp/collationdelta-py314 uv run --locked pytest -q
PATH=/tmp/collationdelta-node/node-v18.20.8-darwin-arm64/bin:$PATH \
  uv run --locked pytest tests/test_node.py -q
```

Local runs used equivalent `/private/tmp` directories and `UV_CACHE_DIR=/private/tmp/collationdelta-uv-cache` to keep disposable files outside the user-wide cache. Path choices do not affect the comparator.

Tests protect drift types, unchanged relations, sorted-snapshot blind spots, distinct collation-equal values, duplicate values under different IDs, Unicode/control preservation, incompatible profiles/corpora, strict response mapping/types, unsupported configuration, malformed output, launch/crash/timeout/output limits, concurrent stdin/stderr I/O, descendant-held pipes, finite-order contradictions, corrupted or misleading captures, partial evidence without diagonals or reciprocal results, exact comparator signs for underflow/overflow magnitudes, private-use locale subtags, atomic writes under file-size and replacement failures, bounded allocations for large reports, stable finding IDs, deterministic reports, and offline operation. The maximum corpus exercises all **65,536** comparisons. Recomputing an invalid capture's digest cannot bypass consistency validation.

## Packaging and offline operation

`uv build` produced a wheel and source distribution. The wheel includes the Node adapter and has no `Requires-Dist` runtime dependencies. The source distribution includes documentation, examples, reproduction script, pins, saved evidence, lockfile, and tests.

The wheel was installed with `uv pip install --no-deps` into a fresh macOS Python 3.12 environment. These commands ran from outside the checkout:

```sh
collationdelta --help
collationdelta capture --corpus /path/to/examples/corpus.json \
  --profile /path/to/examples/profile.json --output /tmp/installed.capture.json \
  -- node "$(collationdelta node-adapter)"
collationdelta compare /tmp/installed.capture.json /tmp/installed.capture.json \
  --json-output /tmp/installed.report.json
```

All returned exit **0**: capture completed **9/9** comparisons and comparison returned `STABLE`. The same installed-wheel workflow passed on Linux.

Offline analysis used `PATH=/nonexistent`, the absolute installed CLI path, and the saved old/new capture paths. It returned exit **1**, `DRIFT`, **2 findings**, and wrote the full JSON report. No Node executable could be resolved through PATH. A unit test also compares a baseline whose recorded adapter path does not exist.

## Historical experiment

```sh
uv run --locked python scripts/reproduce_case.py \
  --runtime-dir /tmp/collationdelta-node --output /tmp/collationdelta-evidence
```

The experiment passed on **macOS arm64 and Linux arm64**, using official pinned archives. Actual Node, ICU, CLDR, and Unicode versions matched the pins. All nine comparisons completed in every capture. Both platforms produced the same two stable finding IDs:

- Equality merge for `letters` / `rupee`: +1 → 0.
- Order reversal for `rupee` / `zero`: -1 → +1.

Each runtime was captured twice and its normalized observations matched on repeat. Both controls returned `STABLE`. Deserialized old/new capture comparison returned `DRIFT`. Sorted output remained `["₨", "Rs"]`; the demonstration application's adjacent-equality deduplication changed `["₨", "Rs"]` to `["₨"]`.

Complete compact macOS evidence is in [evidence/node-upgrade](../evidence/node-upgrade). The [Linux experiment summary](../evidence/node-upgrade/linux-experiment.json) records official Linux archive hashes and actual application outputs. These are separate binary artifacts with the same verified runtime/provider versions, not interchangeable checksum claims.

## Architecture and tradeoffs

The implementation separates strict formats, bounded subprocess transport, finite-model validation, capture/report evidence, and argparse CLI. The Python core uses only the standard library. A single-batch protocol keeps adapters small, at the cost of rejecting truncated stdout rather than recovering results after a process crash. Valid partial responses are saved and reported with exit 2.

Union-find constructs equality components; a strict-order graph validates the finite total preorder. Partial captures check only known constraints and cannot produce `STABLE`. Captures store relation signs instead of sort keys. Reports preserve the comparator's equality and never add a bytewise tiebreaker.

## Limits of verification

Support is verified for the environments listed above. **Linux x64, macOS x64, Linux Python 3.12/3.13, other provider builds, and hosted CI execution were not validated locally.** CI targets Linux/macOS with Python 3.12–3.14. Windows adapter execution is unsupported. `requires-python >=3.12` is an interpreter requirement, not a claim that every future version has been tested.

Finite-corpus stability is not universal Unicode stability. Custom adapter metadata is self-reported and the content digest is not runtime authentication. The whole-Node experiment does not isolate ICU alone, demonstrate a production incident, or establish SQL/database-index behavior. v0.1 ends at local capture and offline drift reporting; it does not manage runtimes, publish packages, modify databases, or accept a new baseline automatically.
