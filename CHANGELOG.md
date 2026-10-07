# Changelog

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
