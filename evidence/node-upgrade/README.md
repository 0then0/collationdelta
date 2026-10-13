# Node upgrade comparison evidence

This dataset compares official Node 18.20.8 and 24.21.0 binaries with the same
`intl.collator.v1`, `en`, `sensitivity: base` profile and three records: `₨`, `Rs`, `0`.
All nine ordered comparisons completed in every capture.

- `old.capture.json`, `new.capture.json` and their `*-repeat` files contain the
  independent observations.
- `old-control.report.json` and `new-control.report.json` are `STABLE` repeat controls.
- `upgrade.report.json` and `upgrade.txt` record an equality merge for `₨` / `Rs` and
  an order reversal for `₨` / `0`.
- `experiment.json` records macOS arm64 archive identities, actual application outputs
  and experiment results.
- `linux-experiment.json` records the corresponding Linux arm64 runtime/application
  experiment; it is separate provenance, not an interchangeable archive checksum.

## Reanalyze offline

From the repository root:

```sh
collationdelta compare evidence/node-upgrade/old.capture.json \
  evidence/node-upgrade/new.capture.json
# Exit 1: DRIFT, two findings.
collationdelta compare evidence/node-upgrade/new.capture.json \
  evidence/node-upgrade/new-repeat.capture.json
# Exit 0: STABLE.
```

The recorded runtimes are not required. The [case study](../../docs/case-study.md)
explains the application example, provider versions, archive verification and explicit
reproduction downloads. The experiment changes the whole Node runtime and does not
isolate ICU as the sole cause or establish database behavior.
