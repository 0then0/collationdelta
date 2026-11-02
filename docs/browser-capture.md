# Browser capture

## Capture in an open browser (0.3.0)

Use the static page when the runtime is the browser you can open: Chromium, Firefox,
Safari or a mobile browser with module Worker support. No Node, Playwright, backend
or browser executable selection is needed by the page. This path observes native
`Intl.Collator` in that browser's **Dedicated Worker**, not its Window realm. It checks
the Worker context and records it in every export. If your application depends on
Window-specific modifications, use an application adapter for that context instead.
The shared `src/collationdelta/adapters/intl.mjs` remains the only Intl evaluator.

Use the executable adapter below for automated Chromium runs, explicit executable
selection, CDP metadata and process supervision. Neither path infers browser ICU/CLDR
versions. The page is a capture tool; offline comparison stays in Python.

### Build and open locally

From the source checkout, using the existing environment:

```sh
uv run --locked python scripts/build_browser_page.py --output build/preview/collationdelta
uv run --locked python -m http.server 8000 --bind 127.0.0.1 --directory build/preview
```

Open `http://127.0.0.1:8000/collationdelta/`. Serve HTTP rather than opening
`index.html` as a file: module Workers need a same-origin HTTP(S) environment. The
build copies five static files plus the actual shared evaluator; it installs nothing.
All asset URLs are relative and work at the project subpath or server root. The build
directory is disposable and excluded from Git.

1. Choose corpus/profile JSON, or select **Load small example**. The example is also
   saved in `examples/browser-page/` for a matching CLI baseline.
2. Review string count, locale and options. An optional runtime label is your claim.
3. Select **Run capture**. Review completion, coverage, supported locales, resolved
   settings and any unsupported reason or errors. Download browser export JSON.
4. Import with this source build and compare against a capture of the same inputs:

```sh
uv run --locked collationdelta import-browser collationdelta.browser-export.json \
  --output /tmp/browser.capture.json
uv run --locked collationdelta capture \
  --corpus examples/browser-page/corpus.json --profile examples/browser-page/profile.json \
  --output /tmp/node.capture.json -- node "$(uv run --locked collationdelta node-adapter)"
uv run --locked collationdelta compare /tmp/node.capture.json /tmp/browser.capture.json \
  --json-output /tmp/browser.report.json
```

An unsupported export is valid evidence: import saves it and returns 2; compare stays
`INCOMPLETE`, including a refusal compared with itself. Invalid evidence returns 3 and
preserves an existing destination. The released 0.2.0 CLI does not include
`import-browser`; these commands require version 0.3.0 or newer. Existing executable
captures stay v1; imported browser captures are v2 and compare with v1 offline.

### Limits, provenance and privacy

Exact scalar strings, empty strings, controls, supplementary/combining characters and
duplicate values are preserved. Unpaired surrogates, duplicate JSON keys, invalid UTF-8
and unsafe numeric underflow/overflow are rejected. There are 1–256 entries and all
ordered pairs, including diagonals. Each input file is limited to 1 MiB; exports to
16 MiB. Conservative preflight sizing may require shorter IDs or a smaller corpus.
The Worker has a 15-second deadline while the tab is active. Cancellation, timeout,
input/label changes and errors revoke previous downloads and discard unfinished work.
Background-tab timer throttling can delay deadline delivery; the Worker is terminated
when the page handles it. A suspended tab cannot promise wall-clock scheduling.

Exports record Worker-observed user agent/platform, page version/time, context and
separate caller labels. Engine, executable, browser version, architecture and locale
data versions remain unknown. Automation acceptance versions are recorded separately
by the test harness, not attributed to the page. Importer version/time are also
separate. Version strings, user agent and labels cannot authenticate a runtime. Export
v1 has no digest; import applies the existing Python canonicalization/digest after
validation. A digest checks integrity, not origin. See [the format specification](protocol.md#browser-export-v1).

No file contents or comparisons are uploaded, no analytics or remote fonts/CDNs are
used, and there is no backend. Page and module/style loading still use the network.
A restrictive CSP disallows connections and form submissions. Acceptance records
context network requests and asserts that all are same-origin static GETs with no
request bodies; saved evidence includes the request audit. Native browser background
services outside this page are not covered by that audit. User strings are rendered
as text, never inserted as HTML. Downloaded exports/captures include the original
strings and should be shared accordingly.

### Browser checks and manual device check

The page acceptance was run on macOS arm64 in real **Chrome for Testing 156.0.8078.4**
and **Firefox 157.0**, using Playwright-core 1.64.0 to operate the actual page. Both
performed real Worker capture, file selection, download, strict import and offline
compare. Desktop 1100px and narrow 360px layouts, keyboard focus, unsupported input,
Unicode, cancellation, timeout and stale-result invalidation were checked. Narrow
viewport emulation is not a physical-device test.

Safari 26.6.1 is installed, but WebDriver refused a session because **Allow remote
automation** is disabled; Safari acceptance was not completed and its settings were
not changed. No actual iOS/Android device or Playwright WebKit acceptance was performed.
WebKit automation, if later run, must be described as WebKit rather than Safari.

For Safari or a physical phone: serve the built page on an accessible HTTP(S) host
(or use Pages after an authorized deployment), open it in the target browser, choose
the example, run capture and save JSON using the browser's download/share UI. Transfer
the saved file to the CLI machine, run the import and baseline commands above, then
compare. Capture twice for a same-runtime control. Record the browser/device version
manually as a caller label and report the actual status; do not require DRIFT or
assume a locale is supported.

### Saved acceptance and reproduction

[evidence/browser-page/](../evidence/browser-page/README.md) contains the small
example, actual exports, imported captures, Node baseline/repeat, controls, offline
reports, command manifest and network audit. Complete controls and cross-runtime
results on this corpus are STABLE; unsupported controls are INCOMPLETE. These facts
do not alter the historical 0.2.0 Node/browser experiment below.

To reproduce with explicitly installed automation browsers:

```sh
# Only if the optional toolchain is not installed:
npm ci --ignore-scripts --prefix scripts/browser-toolchain
# Explicit browser installation, outside capture:
PLAYWRIGHT_BROWSERS_PATH=/tmp/cd-page-browsers \
  node scripts/browser-toolchain/node_modules/playwright-core/cli.js install chromium firefox
PLAYWRIGHT_BROWSERS_PATH=/tmp/cd-page-browsers \
  uv run --locked python scripts/reproduce_page_case.py --node "$(command -v node)" \
  --toolchain "$PWD/scripts/browser-toolchain" --output /tmp/cd-page-evidence
```

The harness builds the production artifact, serves only its static resources at
`/collationdelta/`, operates the real page and downloads files. Node drives automation;
it never supplies browser comparison results. Stalled-Worker UI checks are explicitly
controlled fixtures and are not saved as runtime observations. The Python harness
then runs CLI import/compare, including offline comparison with empty PATH.

### GitHub Pages preparation

`.github/workflows/pages.yml` follows the repository's major-version action pin
convention. It runs only via `workflow_dispatch`; `deploy` defaults to **false**. The
build tests real Chromium/Firefox against the project subpath and uploads the static
Pages artifact. It does not run on push or publish by default. Deployment is a separate
job with `pages: write` and `id-token: write`, gated by an explicitly selected deploy
input and the `github-pages` environment. Other jobs have only `contents: read`.

After separate publication approval, select GitHub Actions as the Pages source,
configure environment/branch protection and dispatch with deployment enabled. The
artifact root is `build/browser-page`; Pages mounts it at `/collationdelta/`. Do not
add an extra project directory inside the uploaded artifact. No domain or repository
settings have been changed and no site has been published by this milestone.
The workflow uses [GitHub's documented Pages actions and permissions](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

## Executable Chromium adapter

The optional browser adapter runs `Intl.Collator` inside a headless Chromium page and
returns observations through the same executable protocol as the Node adapter. Its
captures use the standard schema and work with offline comparison after the browser
and automation toolchain are removed.

The reference contract is `intl.collator.v1`. Node controls startup and transport;
browser JavaScript computes every comparison and performs strict request validation.

## Install the optional toolchain

Browser capture requires Node 20+ and playwright-core. The tested versions are Node
24.21.0 and playwright-core 1.64.0. The Python CLI and Node adapter do not need npm
packages.

From a source checkout or extracted source archive:

```sh
npm ci --ignore-scripts --prefix scripts/browser-toolchain
```

This installs automation code only. To use the browser adapter from an installed wheel,
install the optional package into a separate prefix:

```sh
npm install --ignore-scripts --prefix /tmp/cd-toolchain playwright-core@1.64.0
```

`--toolchain` must point to an absolute installation prefix containing
`node_modules/playwright-core/package.json`. A missing package is an error; the adapter
does not search ancestor packages or `NODE_PATH` for an alternative installation.
The source lockfile also records npm package integrity.

## Choose a browser

`--executable` must be the absolute path of the Chromium-compatible browser to launch.
The adapter does not choose a system default, search user profiles, reuse logged-in
sessions or download a browser during capture.

To explicitly install the browser associated with the pinned automation package into
a separate directory:

```sh
PLAYWRIGHT_BROWSERS_PATH=/tmp/cd-browsers \
  node scripts/browser-toolchain/node_modules/playwright-core/cli.js install chromium
PLAYWRIGHT_BROWSERS_PATH=/tmp/cd-browsers \
  node -e "console.log(require('./scripts/browser-toolchain/node_modules/playwright-core').chromium.executablePath())"
```

The second command prints the executable path without launching it. Set `browser` to
that path for the commands below. Avoid invoking an uninstalled package through `npx`
during capture, since it may download code implicitly.

The verified browser is **Google Chrome for Testing 156.0.8078.4 on macOS arm64**, in
headless mode. Linux uses the same POSIX transport but has not been validated locally
for browser capture. Other Chrome distributions and versions require their own checks.
Firefox, Safari/WebKit, Edge, mobile browsers and Windows are not supported by this
reference adapter.

## Capture and compare

These commands use the installed CLI and source example inputs. With a source-only
installation, prefix `collationdelta` with `uv run --locked`.

```sh
browser='/absolute/path/to/browser'
toolchain="$PWD/scripts/browser-toolchain"
collationdelta capture --corpus examples/browser/corpus.json \
  --profile examples/browser/en.profile.json --output /tmp/node-en.json \
  -- node "$(collationdelta node-adapter)"
collationdelta capture --corpus examples/browser/corpus.json \
  --profile examples/browser/en.profile.json --output /tmp/browser-en.json \
  -- node "$(collationdelta browser-adapter)" \
  --toolchain "$toolchain" --executable "$browser"
collationdelta compare /tmp/node-en.json /tmp/browser-en.json \
  --json-output /tmp/en-report.json
```

Use the same corpus and requested profile on both sides. The 1–256 entry bound and
all ordered comparisons, including self comparisons, apply to browser capture as well.
Strings and IDs are preserved exactly. Offline analysis needs only Python and the
capture files, not the source inputs, Node, Chromium or Playwright.

## Strict locale support

Both adapters share option validation, canonicalization, lookup negotiation and
Unicode extension handling. `localeMatcher` is fixed to `lookup`. Correct negotiation
does not require literal equality of requested and resolved locale. Explicit options
override recognized locale extensions; ignored explicit requests are unsupported.
The exact supported option values are listed in [protocol.md](protocol.md).

The adapter records lookup `supportedLocalesOf` and any known `resolvedOptions`.
If the requested locale has no supported match, it returns `unsupported`, a reason,
known effective settings and **no comparisons**. Capture saves this evidence with exit
2. Comparing it against a complete strict capture returns `INCOMPLETE` with zero
findings, because there are no shared observations to compare.

Native application fallback requires a separate comparator contract that explicitly
permits it. Strict capture never switches contracts automatically. Strict and
permissive artifacts must not be presented as compatible requested profiles.

## Execution and limits

The adapter launches Chromium as a child in the capture supervisor's process group.
A temporary profile exposes a loopback CDP endpoint on an ephemeral port. Playwright
waits for the complete endpoint file within the adapter deadline, connects through
`connectOverCDP`, creates a disposable context, blocks page requests,
and evaluates the shared static function on `about:blank`. The corpus and profile are
structured arguments, never interpolated into executable JavaScript.

Browser launch sets `--password-store=basic` and `--use-mock-keychain` for the disposable
profile. Capture does not require access to the user's system Keychain/keyring or stored
browser credentials. Browser sandboxing remains enabled. The configured storage flags
are recorded in `runtime.execution.credential_store_flags`.

The adapter accepts these options:

- `--toolchain PATH`: absolute optional npm installation prefix, required.
- `--executable PATH`: absolute browser executable, required.
- `--deadline-ms N`: adapter deadline, default 20,000 ms; an integer from 1 through
  2,147,483,647. It covers stdin, startup, evaluation and normal teardown.
- `--distribution-label TEXT`: optional caller label recorded separately from runtime
  observations.

The outer capture deadline is 30 seconds by default and remains authoritative over
the whole process. Failure cleanup adds bounded attempts to stop the browser and
remove its profile. When changing deadlines, leave room between the adapter deadline
and core `--timeout` for cleanup.

Core defaults bound stdout to 16 MiB and stderr to 1 MiB. The browser adapter also
rejects stdin larger than 32 MiB. Browser output is routed to adapter stderr; stdout
contains one protocol document emitted after successful teardown.

Success closes the context, sends CDP `Browser.close`, and waits for exit. Failure uses
SIGTERM and then SIGKILL if required. The core kills the process group on completion,
timeout or output-limit failure. External SIGKILL can leave an inert temporary profile
directory because killed code cannot remove it. Arbitrary executable wrappers that
detach descendants are outside this cleanup guarantee.

Launch/crash/timeout, closed-context, malformed-response, output-limit and consistency
errors return exit 3 and preserve an existing destination capture. A valid unsupported
or partial response is saved with exit 2.

## Metadata and provenance

Existing metadata containers distinguish:

- connected browser version, user agent, navigator platform and execution-context
  observations;
- automation package name/version and host Node/platform/architecture;
- selected executable, caller-supplied distribution label and configured execution mode;
- canonical locale, supported lookup locales and resolved settings in `runtime.intl`.

The engine label identifies the configured Chromium/CDP adapter path. Browser ICU,
CLDR and Unicode versions are not inferred. User agent and navigator platform can
report Intel/MacIntel on an arm64 host; they are separate observations, not architecture
or authenticity checks.

The experiment manifest records download URLs/archive hashes, selected executable
hashes, adapter source hashes, corpus/profile hashes and commands. Executable hashes
cover selected files, not every linked library or locale-data file. Version strings,
user agents, caller labels and capture digests are not authentication. Absolute paths
in saved artifacts describe the capture machine; offline comparison does not resolve
or execute them.

## Saved Node/browser case

The [saved experiment](../evidence/node-browser/experiment.json) captures these exact
strings under `en` and `is`, with empty profile options and lookup negotiation:

```text
Aðalheiður
Ásta
Bjarni
Örn
Úlfur
Ýrr
Þórður
Ævar
```

Each Node/browser and locale combination was captured twice. Supported captures have
64/64 comparisons. Repeated observations within each runtime match exactly.

- `en`: both runtimes support the locale. Both same-runtime controls and the
  Node/browser report are `STABLE`, zero findings.
- `is`: Node supports and resolves `is`, with a `STABLE` repeat control. This browser
  reports empty supported locales, known resolved `en-US` and no comparisons. Its
  repeat control and Node/browser report are `INCOMPLETE`, zero findings.

Repeated refusal is not comparator stability. The case establishes a support gap for
these builds, not complete fallback drift or universal Chromium behavior.

### Reproduce the pinned case

The historical archive pins cover macOS arm64. The downloader needs tar extraction
filters: Python 3.10.12+, 3.11.4+ or 3.12+. Use a fresh disposable runtime directory:

```sh
uv run --locked python scripts/obtain_browser_case.py --runtime-dir /tmp/cd-pinned
npm ci --ignore-scripts --prefix scripts/browser-toolchain
uv run --locked python scripts/reproduce_browser_case.py \
  --node /tmp/cd-pinned/node-v24.21.0-darwin-arm64/bin/node \
  --browser '/tmp/cd-pinned/browser-156.0.8078.4/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing' \
  --toolchain "$PWD/scripts/browser-toolchain" \
  --provenance /tmp/cd-pinned/provenance.json \
  --expect-pinned --output /tmp/cd-evidence
```

The downloader verifies archive SHA-256 before extraction and does not alter global
installations. It refuses to overlay an existing browser extraction. Hash verification
is an integrity check, not a publisher signature.

For an installed current build, run `reproduce_browser_case.py` with your selected
executables and omit `--expect-pinned`. Newer builds may legitimately support `is`;
current-runtime acceptance does not require the historical gap or universal relation
equality between providers.

The script saves eight captures, four control reports, two cross-runtime reports,
human reports and a manifest. It reanalyzes saved files and runs a fresh offline CLI
with empty `PATH`. See [testing](validation.md) for integration and release checks.

## References

[workerd issue 64](https://github.com/cloudflare/workerd/issues/64) and
[cldr-is](https://github.com/gudrodur/cldr-is) describe locale-support concerns that
motivated this case. Their claims do not establish behavior for these executables,
all Chromium builds or Cloudflare Workers.
[ECMA-402](https://tc39.es/ecma402/#sec-intl.collator) defines locale negotiation with
implementation-dependent available locales. A provider difference alone is not a
specification violation. Browser control uses the documented
[Playwright CDP](https://playwright.dev/docs/api/class-browsertype#browser-type-connect-over-cdp)
and [structured evaluation](https://playwright.dev/docs/evaluating) APIs.
