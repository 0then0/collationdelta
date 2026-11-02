# Open-browser capture acceptance

Actual native browser Worker observations saved on 2026-11-02, macOS arm64. This is
new milestone evidence; `evidence/node-browser/` remains the historical 0.2.0 case.

The one main corpus/profile are `examples/browser-page/corpus.json` and
`examples/browser-page/profile.json`: eight exact strings, `en`, sensitivity `base`.
The page's built-in example uses the same inputs. It includes empty, control,
combining, precomposed, supplementary and duplicate values. No DRIFT was required.

The harness tested the production artifact under `/collationdelta/` in actual Chrome
for Testing **156.0.8078.4** and Firefox **157.0** through playwright-core **1.64.0**.
These versions are harness observations. The page records only its native Worker
user agent/platform, context, timestamp and caller label, with no inferred engine,
version, architecture or ICU/CLDR. Node **v26.13.0** supplied the CLI baseline.

- `{chromium,firefox}.browser-export.json`: downloaded JSON from the real page.
- `{chromium,firefox}.capture.json`: CLI import output, capture v2.
- `*-repeat.browser-export.json` / `*-repeat.capture.json`: actual same-browser repeat.
- `node.capture.json` / `node-repeat.capture.json`: executable Node captures, v1.
- `*-node.report.json`: ordinary offline Node/browser comparison, STABLE, 64/64 each.
- `*-control.report.json`: same-runtime controls, STABLE, zero findings.
- `*-unsupported*`: separate support-negative check (`zz-ZZ`), no comparisons,
  INCOMPLETE even when compared with itself. Not fallback collation evidence.
- `*-files*`: separately labelled input-preservation check, with long/supplementary
  IDs, controls and an HTML-looking string. Not the main corpus or a drift fixture.
- `*-after-cancel*`: actual example capture after controlled stalled-Worker UI checks.
  The stalled Worker returns no exported observations and is not runtime evidence.
- `browser-checks.json`: exact automation/browser versions and full static-request
  audit. Every observed page/context request was a same-origin GET of a fixed static
  asset, without a request body. No corpus/profile/result upload was observed.
- `experiment.json`: executed commands, Node/Python versions, input/shared-evaluator
  SHA-256 and confirmation that offline comparisons ran with empty PATH/NODE_PATH.

Complete observations passed the existing consistency validator. New CLI imports
validate every export rather than trusting its coverage. The export has no digest;
imported captures use the Python canonicalization and SHA-256 rule. Neither metadata
nor digests authenticate the runtime or sender. The absolute paths and ephemeral
server port document the acceptance machine and are not used during offline analysis.

Reproduce with the installed optional toolchain and installed automation browsers:

```sh
PLAYWRIGHT_BROWSERS_PATH=/tmp/collationdelta-page-browsers \
  uv run --locked python scripts/reproduce_page_case.py --node "$(command -v node)" \
  --toolchain "$PWD/scripts/browser-toolchain" --output /tmp/cd-page-evidence
```

The exact invocation for these artifacts used the same options with
`--output evidence/browser-page`. The command manifest expands the executable paths.
New runtime builds may legitimately produce different support or comparison results.

Offline reanalysis of these saved files:

```sh
uv run --locked collationdelta compare evidence/browser-page/node.capture.json \
  evidence/browser-page/chromium.capture.json
uv run --locked collationdelta compare evidence/browser-page/firefox.capture.json \
  evidence/browser-page/firefox-repeat.capture.json
uv run --locked collationdelta import-browser \
  evidence/browser-page/chromium.browser-export.json --output /tmp/reimported.capture.json
uv run --locked collationdelta compare evidence/browser-page/chromium.capture.json \
  /tmp/reimported.capture.json
```

Desktop/narrow screenshots were visually inspected at 1100px and 360px. File input,
download, keyboard focus, long text, unsupported/error states, cancellation, input
invalidation and a real 15-second timeout of a controlled stuck Worker were exercised.
Narrow viewport testing does not establish physical mobile behavior. Safari 26.6.1
WebDriver refused a session because Allow remote automation is disabled. No real
Safari/iOS/Android acceptance or WebKit automation is claimed. Follow the browser
guide's short manual-device instructions for those environments.
