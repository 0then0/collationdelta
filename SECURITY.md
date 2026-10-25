# Security policy

## Supported versions

Security fixes target the latest stable release published on PyPI. Older releases
are not maintained as separate security branches. Upgrade to the latest stable release
before checking whether a suspected issue persists. Release history is in the
[changelog](CHANGELOG.md).

## Report a vulnerability

Do not disclose exploit details, credentials, private corpora or application captures
in public issues or pull requests.

Use GitHub's **Report a vulnerability** option on the repository's Security page if it
is available. Private vulnerability reporting is not currently enabled for this
repository, and there is no published security email address. Until a private channel
is available, use the [private contact request form](https://github.com/0then0/collationdelta/issues/new?template=private_contact.yml)
with no technical details or attachments, and ask the maintainer for a private
reporting channel. This is a request for contact, not the vulnerability report itself.

Once a private channel is agreed, provide the affected version and platform, a minimal
synthetic reproduction, expected and observed behavior, potential impact and any
suggested mitigation. Include relevant Python, Node, browser and toolchain versions.
Coordinate public disclosure with the maintainer. Response and fix times depend on
availability; the project does not promise a response deadline or a bounty.

## Trust boundaries

- Executable adapters run as subprocesses with the invoking user's permissions.
  Only run adapters and runtime binaries you trust. Process-group cleanup and resource
  limits do not provide a security sandbox for untrusted programs.
- Captures contain the original corpus, command arguments, runtime metadata and
  diagnostics. A SHA-256 digest detects alteration; it does not authenticate a runtime
  or make captured data safe to share. Generate a synthetic reproduction instead of
  manually editing a capture whose digest is expected to remain valid.
- Browser capture uses an explicit native executable and optional Playwright toolchain.
  No runtime is downloaded during capture. Keep selected runtimes current for your
  environment; the pinned historical experiments are reproducibility fixtures, not a
  recommendation to use those builds on untrusted content.
- Report suspected validation bypasses, unsafe file handling, unexpected command
  execution or failures of resource bounds privately. A collation difference alone
  is not a security vulnerability in CollationDelta.
