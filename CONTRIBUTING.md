# Contributing to CollationDelta

Bug reports, focused fixes, tests and documentation improvements are welcome. Read the
[Code of Conduct](CODE_OF_CONDUCT.md) before participating. Report security concerns
using the [security policy](SECURITY.md), rather than a public bug report.

## Set up a checkout

Use Python 3.10+ on Linux or macOS and [uv](https://docs.astral.sh/uv/). Node is needed
for the reference adapter tests. The Python CLI has no runtime dependencies.

```sh
git clone https://github.com/0then0/collationdelta.git
cd collationdelta
uv sync --locked --python 3.10
uv run --locked collationdelta --help
```

Keep `uv.lock` under version control. Change dependencies deliberately and update the
lockfile when a dependency change requires it. Do not replace an existing environment
just to run a check.

Native Chromium integration is optional for ordinary development. Follow the
[browser guide](docs/browser-capture.md) to install its separate toolchain and choose
an executable. Tests do not download a browser; missing integration configuration
produces explicit skips. Browser-related changes require real integration results.

## Make a change

For a large feature, protocol change or new dependency, open an issue to discuss the
use case before implementation. Keep pull requests focused and preserve unrelated
work. Match the existing code and use the standard library where practical.

- Preserve exact Unicode strings, strict locale/option handling and evidence digests.
- Preserve bounded subprocess execution, process cleanup and atomic output behavior.
- Add regression tests for changed behavior and update the relevant public docs.
- Treat saved evidence as reproducible data. Do not reformat or hand-edit captures to
  make tests pass. Record runtime provenance when regenerating an experiment.
- Keep credentials, private corpora and machine-local outputs out of commits. Use
  synthetic input when demonstrating a failure.

Read the [protocol](docs/protocol.md) before changing adapters or capture/report
formats. The [testing guide](docs/validation.md) explains runtime coverage and the
[saved experiments](evidence/node-browser/README.md).

## Validate your work

```sh
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -q
```

Use `uv run --locked ruff format .` to apply formatting. `.editorconfig` defines editor
settings; Ruff remains authoritative for Python formatting. Use UTF-8 and LF line
endings. Markdown may use trailing spaces for intentional hard line breaks.

Run packaging checks for changes to package contents, dependencies, entry points or
build configuration:

```sh
uv lock --check
uv build
uvx --from twine==6.2.0 twine check --strict dist/*
```

Use a clean build output directory. If workflow files change, run
`actionlint .github/workflows/*.yml` when available. See the testing guide for clean
wheel installation, offline comparison and native browser commands. State which
checks passed, which were skipped and why; skipped integration is not a passing test.

## Report a bug or submit a pull request

Use the GitHub issue forms. Include a minimal synthetic corpus/profile, exact command,
expected and actual behavior, package/Python versions, OS and relevant runtime versions.
Avoid uploading real application captures: they contain original strings, arguments,
paths and diagnostics.

Fork the repository if needed and submit a pull request against `main`. Describe the
problem, resulting behavior and checks actually run. Use Conventional Commits in
English, for example `fix: reject contradictory adapter output` or
`docs: explain partial capture coverage`. No contributor license agreement or sign-off
is required by this project; contributions are made under its [Apache-2.0 license](LICENSE).

CI checks Python 3.10–3.14 on Linux, Python 3.10 and 3.14 on macOS, linting, packaging
and native Chromium integration. Release publication is a maintainer action; use the
[release guide](docs/releasing.md) rather than creating a version tag in a contribution.
