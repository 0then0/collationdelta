# Release maintenance

Version tags trigger the release workflow. It validates the source, calls the core
packaging job to build and check the wheel and source archive, creates or updates the
matching GitHub Release, and publishes the same distributions to PyPI through Trusted
Publishing.

A normal branch push runs CI only. It does not publish a package or create a release.

## Publisher configuration

The PyPI project must authorize this GitHub Trusted Publisher:

- repository: `0then0/collationdelta`;
- workflow: `.github/workflows/release.yml`;
- environment: `pypi`.

Configure the repository's `pypi` environment with the intended tag restrictions and
required reviewers. Only the publishing job receives `id-token: write`; GitHub Release
creation uses a separate job with `contents: write`. No stored PyPI API token is needed.

For a first publication, PyPI supports a
[pending publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).
For an existing project, manage its Trusted Publishers in the project's PyPI settings.

## Validate a release

Keep versions in `pyproject.toml` and `src/collationdelta/__init__.py` equal. Add the
matching `## VERSION` changelog entry and update documentation when behavior changes.

```sh
uv sync --locked --python 3.10
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -q
uv build
uvx --from twine==6.2.0 twine check --strict dist/*
```

Use a clean checkout or an empty build output directory so `dist/` contains only the
intended distributions. Twine is an isolated release-check tool, not a project runtime
dependency. Run [browser integration](validation.md#native-browser-integration) with
explicitly installed tools; skipped browser tests do not qualify as release evidence.

Check a clean wheel installation, Node capture, optional browser capture and offline
comparison. The wheel must have no Python runtime dependencies, and the source archive
must exclude `node_modules`. The [testing guide](validation.md#packaging-checks) contains
commands for these checks.

## Publish a version tag

Commit and push the release changes, then wait for both core and native browser CI to
pass. For version 0.2.0:

```sh
git tag v0.2.0
git push origin v0.2.0
```

The workflow calls the core and native browser workflows once. The core matrix tests
Python 3.10–3.14 on Linux and Python 3.10 and 3.14 on macOS. Ruff and packaging run in
separate Linux jobs; the native Chromium job includes its installed-wheel check.
Standalone core/browser workflows do not also run on tag pushes.

After all checks pass, the workflow verifies the tag against both version declarations
using Python 3.12 for its `tomllib` version guard. This does not change the installed
CLI's Python 3.10 minimum. GitHub Release and PyPI publication use the checked
`distributions` artifact from the core packaging job without rebuilding it. Release
checks and publication are excluded from cancellation of outdated branch/PR runs.

A published non-prerelease GitHub Release with a matching version tag also triggers
the workflow. Draft and prerelease events do not publish. Releases created using the
workflow's `GITHUB_TOKEN` do not trigger a second publishing run.

GitHub Release creation reads notes from the matching changelog entry and attaches the
checked distributions. PyPI receives those same artifacts in the `pypi` environment.
Approve that deployment if the environment requires review.

## Verify publication

Inspect the workflow result, GitHub Release assets and
[PyPI release files](https://pypi.org/project/collationdelta/), then install the released
version in a fresh environment:

```sh
pip install collationdelta==0.2.0
collationdelta --version
```

PyPI release files cannot be replaced. If publication partially succeeds, inspect which
files were uploaded before retrying; the workflow does not silently skip existing
files. Correct a faulty published release with a new version instead of moving the
old tag or overwriting artifacts.
