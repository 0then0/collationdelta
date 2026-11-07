# Changelog

## Unreleased

## 0.4.0

- Add a PostgreSQL 15–18 capture adapter (`postgresql.text.v1`, `collationdelta
  postgres-adapter`). It runs `psql` in one read-only transaction and records the server's
  `<`, `=` and `>` for every ordered pair under an explicit schema-qualified collation,
  with the corpus sent as data and no objects created. Server version, encoding and
  collation properties (provider, locale, deterministic, stored and actual version) are
  recorded as effective/runtime metadata; unavailable facts carry reasons. Refusals,
  U+0000 strings, timeouts and truncated output stay explicit and incomplete.
- Add a reproducible two-server configuration-control stand with pinned image digest,
  saved captures/reports/direct SQL confirmation, and a 15–18 provider matrix.
  Capture, report and protocol formats are unchanged.
- Refine the project icon.

## 0.3.0

- Add a responsive static browser capture page with one example, exact JSON inputs,
  native Dedicated Worker Intl observations, bounded time/output, cancellation and
  explicit unsupported exports. Build from the shared evaluator without duplicating it.
- Add strict offline `import-browser` for browser export v1, capture v2 with versioned
  browser/importer provenance, existing relation validation and atomic output. Preserve
  capture v1 reading, executable capture output and historical evidence.
- Verify Chromium/Firefox page download → import → compare, unsupported controls,
  Unicode, input/run invalidation, narrow layout and static-only network requests;
  save a reproducible acceptance case. Document unverified Safari/mobile devices.
- Prepare a manual GitHub Pages workflow with project-subpath acceptance and a separate
  opt-in deploy job. No site or release is published.

- Add contributor, conduct and security policies, GitHub issue forms and a pull request
  template; link participation and reporting guidance from the README.
- Define UTF-8/LF editor and Git text settings and replace the generic ignore template
  with rules for Python, uv, the optional browser toolchain and local credentials.
- Run lint and packaging once, reduce the macOS test matrix to Python 3.10 and 3.14,
  reuse checked release archives and avoid duplicate checks on version tags.

## 0.2.0

Native browser capture with portable evidence and strict locale support.

- Add an optional headless Chromium executable adapter using Playwright over local
  CDP. Comparisons and strict validation run inside the browser; runtime selection
  and installation are explicit, with no capture-time downloads.
- Share `intl.collator.v1` negotiation and option validation with the Node adapter.
  Preserve supported lookup negotiation and refuse ignored explicit requests.
- Preserve known resolved options and locale-support observations for unsupported
  requests, without reporting fallback comparisons or complete drift.
- Record browser version/user agent, automation version, host platform/architecture,
  execution mode and explicitly separated caller labels in existing metadata containers.
- Include pinned Node 24.21.0 / Chrome for Testing 156.0.8078.4 macOS arm64 artifacts,
  repeated captures, supported controls, unsupported Icelandic outcome, archive and
  executable provenance, and offline reanalysis.
- Add native integration, deadline/closed-page/process-group cleanup checks and a
  separate browser CI/release gate. Keep Python core free of runtime dependencies and
  the Node reference adapter free of npm dependencies.
- Isolate browser credential storage from system Keychain/keyring services and reject
  missing toolchain installations without searching ancestor packages.
- Check process cleanup even when timeout occurs before browser startup and wait for
  complete CDP endpoint data during native startup.
- Preserve completed adapter results when macOS denies signalling a departed process
  group; keep signalling errors visible for unfinished adapters and other platforms.
- Support Python 3.10+; exercise Python 3.10–3.14 in core CI and Python 3.10 in native browser CI.
- Keep capture/report/protocol formats, core comparison, corpus limits, atomic output
  and exit codes unchanged. No application fallback contract is added.

See [the browser guide](docs/browser-capture.md) and
[validation report](docs/validation.md) for tested environments and limitations.

## 0.1.0

First release of the local capture and offline comparison CLI.

- Observe all ordered pairs in a corpus of up to 256 records through an executable application adapter.
- Detect equality merges, equality splits, and order reversals with deterministic pair witnesses and explicit coverage.
- Preserve original Unicode scalar strings and validate finite-order consistency, capture digests, and corpus/profile compatibility.
- Keep confirmed findings from partial observations, including opposite observed pair directions, without claiming complete coverage.
- Bound subprocess time and output, and write JSON files atomically.
- Include a Node `Intl.Collator` reference adapter and a custom application adapter example.
- Include a reproducible Node 18.20.8 to 24.21.0 upgrade experiment, saved evidence, and same-runtime controls.
- Support Python 3.12+ on Linux and macOS, with no Python runtime dependencies.

See the [validation report](https://github.com/0then0/collationdelta/blob/main/docs/validation.md) for tested environments and limitations.
