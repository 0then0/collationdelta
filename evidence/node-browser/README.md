# Node/browser comparison evidence

This dataset records native `Intl.Collator` observations for eight Icelandic names in
Node 24.21.0 and Google Chrome for Testing 156.0.8078.4 on macOS arm64. Both adapters
use the strict `intl.collator.v1` contract with `en` or `is`, empty options and lookup
locale matching.

## Files

- `node-LOCALE.capture.json` and `browser-LOCALE.capture.json`: initial captures.
- `*-repeat.capture.json`: independent repeated captures with the same runtime/profile.
- `*-control.report.json`: offline comparison of each initial/repeated capture pair.
- `en.report.json`, `is.report.json`: offline Node/browser comparisons.
- `en.txt`, `is.txt`: human-readable versions of the cross-runtime reports.
- `experiment.json`: input/capture/source hashes, runtime observations, executable and
  archive provenance, commands and experiment scope.

Supported captures contain all 64 ordered comparisons. `en` is supported in both
runtimes and the cross-runtime report is `STABLE`, zero findings. Node supports `is`;
this browser has no supported lookup match, reports known resolved locale `en-US`, and
returns no strict comparisons. Its repeated refusal and cross-runtime report are
`INCOMPLETE`, zero findings. Missing observations are not equality or fallback drift.

## Reanalyze offline

From the repository root, with CollationDelta installed:

```sh
collationdelta compare evidence/node-browser/node-en.capture.json \
  evidence/node-browser/browser-en.capture.json
# Exit 0: STABLE.
collationdelta compare evidence/node-browser/node-is.capture.json \
  evidence/node-browser/browser-is.capture.json
# Exit 2: INCOMPLETE.
```

No Node, browser or Playwright installation is needed for these commands. Absolute
paths embedded in captures describe the original environment and are not executed
when loading evidence.

See the [browser guide](../../docs/browser-capture.md#saved-nodebrowser-case) for
pinned reproduction commands and metadata limits. This dataset establishes behavior
for the recorded builds and finite corpus, not every Chromium distribution, Unicode
conformance, Cloudflare Workers or a production incident.
