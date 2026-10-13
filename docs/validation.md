# Testing and supported environments

The core CLI requires Python 3.10+ on Linux or macOS and has no runtime dependencies.
Node and browser runtimes are required only for their respective capture adapters.
Windows adapter execution is unsupported.

## Run the checks

From the repository root:

```sh
uv sync --locked --python 3.10
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -q
uv build
```

The suite checks Unicode preservation, input/protocol validation, complete and partial
observations, equality/order changes, finite-order consistency, capture digests,
deterministic reports, atomic output, process deadlines and offline comparison.
Node integration runs when Node is installed. Unit tests do not download runtimes.

Ruff targets Python 3.10, uses a 100-column layout and checks errors, imports, compatible
syntax and common bug patterns. Apply formatting with `uv run --locked ruff format .`.

## Native browser integration

Install the optional toolchain and choose an existing browser as described in the
[browser guide](browser-capture.md), then run:

```sh
export COLLATIONDELTA_BROWSER_TOOLCHAIN="$PWD/scripts/browser-toolchain"
export COLLATIONDELTA_BROWSER_EXECUTABLE='/absolute/path/to/browser'
uv run --locked pytest -q tests/test_browser.py
```

Both paths must identify the intended installations. Missing environment configuration
produces visible skip reasons; invalid configured paths fail. A skipped test is not
browser compatibility evidence.

Browser tests run comparisons in a real `about:blank` context. They check exact strings,
all ordered pairs, repeated observations, strict option/extension handling, refusal of
unsupported requests, actual runtime metadata and protocol stdout. Failure cases cover
closed pages, stalled evaluation, pair exceptions, incomplete/invalid startup endpoints,
launch/crash/output-limit failures,
and preservation of an existing capture destination.

Lifecycle tests inspect the supervisor process group and temporary browser profile
path after success and failure. A lingering descendant exercises cleanup even after the
main browser exits. Startup timeout before browser spawn is checked separately from
cleanup of an active browser. Credential-storage tests inspect actual launch arguments
before allowing the native executable to run. Toolchain-selection tests ensure an
absent installation cannot fall back to packages in ancestor directories or `NODE_PATH`.

The [native browser workflow](../.github/workflows/browser.yml) explicitly installs its
pinned toolchain/browser, requires real integration, runs the current-runtime experiment
and exercises the adapter from a clean wheel. Release builds depend on this job.

## Runtime coverage

The saved browser case uses:

- macOS arm64, Google Chrome for Testing **156.0.8078.4**, headless;
- Node **24.21.0**, ICU **78.3**, CLDR **48.0**, Unicode **17.0**;
- playwright-core **1.64.0**.

Local verification includes Python **3.10.22** and **3.12.15** on macOS arm64. The
[core workflow](../.github/workflows/ci.yml) covers Linux and macOS with Python
3.10–3.14; browser CI runs on macOS with Python 3.10. CI configuration describes the
checks to run, not a claim that every configured environment has been verified locally.

The [Node upgrade example](case-study.md) also has saved Linux arm64 experiment
metadata. That evidence concerns the Node case, not browser compatibility.

Linux browser execution, macOS x64 browser builds, other engines/distributions and
mobile browsers have not been validated locally. Firefox, Safari/WebKit and Edge are
not supported by the reference browser adapter. Future Python/runtime versions need
their own verification.

## Saved evidence

The ordinary suite reanalyzes [Node upgrade artifacts](../evidence/node-upgrade) and
[Node/browser artifacts](../evidence/node-browser) without launching their recorded
runtimes. It checks digests, complete report contents, repeat observations and expected
supported/unsupported outcomes.

For the browser case, supported `en` captures contain 64/64 comparisons and the report
is `STABLE`. The browser's strict `is` response is unsupported with zero observations,
known effective locale `en-US`, and an `INCOMPLETE` report. Missing results do not
become equality or a complete drift report.

The [reproduction instructions](browser-capture.md#saved-nodebrowser-case) describe
pinned archive downloads, executable/input hashes, repeated captures and offline
reanalysis. The separate archive downloader requires tar extraction data filters,
available in Python 3.10.12+, 3.11.4+ and 3.12+. Normal CLI operations require Python 3.10+.

## Packaging checks

Build a wheel and source archive, check their metadata, then install the wheel without
adding runtime dependencies:

```sh
uv build
uvx --from twine==6.2.0 twine check --strict dist/*
uv venv /tmp/collationdelta-install --python 3.10
uv pip install --no-deps --python /tmp/collationdelta-install/bin/python \
  dist/collationdelta-0.2.0-py3-none-any.whl
cli=/tmp/collationdelta-install/bin/collationdelta
"$cli" --version
"$cli" node-adapter
"$cli" browser-adapter
PATH='' "$cli" compare evidence/node-browser/node-en.capture.json \
  evidence/node-browser/browser-en.capture.json
```

The last command returns `STABLE` without resolving Node or browser executables.
Repeat with the `is` files to get exit 2, `INCOMPLETE`. The wheel bundles all three
adapter modules and declares no `Requires-Dist` dependencies. The source archive
includes examples, scripts, pins, evidence, documentation and tests, while excluding
`node_modules`.

To check the installed browser adapter, install its npm toolchain separately and run
`capture` using the adapter path printed by the installed CLI. The ordinary wheel and
Node adapter remain usable without that toolchain. Neither wheel installation nor
capture downloads a browser.

Workflow syntax can be checked with `actionlint .github/workflows/*.yml`. Publishing
credentials and OIDC permissions are covered in the [release guide](releasing.md).

## Interpretation limits

Finite-corpus stability is not universal Unicode stability. Version strings, user agents,
caller labels and capture digests are not proof of runtime authenticity. Executable
hashes do not identify every linked library or locale-data file. Browser ICU, CLDR and
Unicode versions are not inferred from its version number.

Whole-group SIGKILL can leave an inert temporary profile directory because adapter
cleanup cannot run after SIGKILL. The process cleanup guarantee applies to the tested
native executable and descendants that retain the supervisor group. Arbitrary wrappers
which detach processes are outside that guarantee.
