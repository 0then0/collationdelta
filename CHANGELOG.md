# Changelog

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
