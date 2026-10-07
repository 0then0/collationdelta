# Releasing CollationDelta

The package version is **0.1.0**, and its release tag is **v0.1.0**. Publication uses GitHub Actions OIDC and PyPI Trusted Publishing, without a stored PyPI API token.

## One-time configuration

Create the `pypi` environment under [repository Settings → Environments](https://github.com/0then0/collationdelta/settings/environments). Restrict deployment to release tags such as `v*`; use required reviewers when appropriate for the repository's maintainers.

For the first publication, add a pending publisher under [PyPI account publishing settings](https://pypi.org/manage/account/publishing/):

- **PyPI Project Name:** `collationdelta`
- **Owner:** `0then0`
- **Repository name:** `collationdelta`
- **Workflow name:** `release.yml`
- **Environment name:** `pypi`

Workflow name is the filename, without `.github/workflows/`; it is not the workflow's display name. The environment name must match the publishing job exactly. A pending publisher creates the project on the first successful upload and does not reserve the project name beforehand. See the [PyPI pending publisher guide](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).

## Prepare and validate

Keep `pyproject.toml` and `src/collationdelta/__init__.py` versions equal. Update the changelog and record relevant validation results before creating a release.

```sh
uv sync --locked --python 3.12
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -q
uv build
uvx --from twine==6.2.0 twine check --strict dist/*
```

Use a fresh checkout or an empty build output directory so that `dist/` contains only the intended wheel and source archive. Twine is an isolated release-check tool, not a runtime or project dependency.

Commit and push the prepared files before creating the tag. Wait for CI to pass. In [GitHub Releases](https://github.com/0then0/collationdelta/releases/new), create a release using tag `v0.1.0` on the prepared commit, title `v0.1.0`, and the 0.1.0 changelog entry as its description. Publishing a non-prerelease GitHub Release starts `release.yml`; creating only a tag or saving a draft does not publish to PyPI.

## Publication

The workflow reruns the Linux/macOS Python matrix, verifies the tag against both version declarations, builds and checks distributions, then uploads the same artifacts in a separate `pypi` environment job. Only that job receives `id-token: write`. Approve the environment deployment if required by its settings.

Verify the workflow result, uploaded files, and version on [PyPI](https://pypi.org/project/collationdelta/). Then install the published version in a clean environment:

```sh
pip install collationdelta==0.1.0
collationdelta --version
```

PyPI release files cannot be replaced. If publication partially succeeds, inspect the uploaded files before retrying; the workflow deliberately does not silently skip existing files. Fix a faulty published release with a new version rather than moving the old tag or overwriting its artifacts.
