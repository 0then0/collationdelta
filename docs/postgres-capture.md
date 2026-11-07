# PostgreSQL text comparison capture

`postgres.py` observes what a PostgreSQL **server** returns for `text` comparisons under
one named collation, so a corpus can be captured on an old and a new server and compared
offline. It is an ordinary executable adapter for contract `postgresql.text.v1`.

## What is observed

For every ordered pair the adapter asks the server for the built-in operators `<`, `=`
and `>` on `text`, with the collation written explicitly on both operands. Exactly one
must be true; the sign is `-1`, `0` or `+1`. Any other combination is a pair failure,
never an invented value.

This is deliberately not a provider-only comparison. In PostgreSQL
([`varlena.c`, REL_18](https://github.com/postgres/postgres/blob/REL_18_STABLE/src/backend/utils/adt/varlena.c#L1695))
`varstr_cmp` breaks a provider tie by bytes when the collation is deterministic, and
`texteq` for a deterministic collation compares bytes without calling the provider. So:

- with a **deterministic** collation, `0` means identical bytes. Canonically equivalent
  strings such as `é` and `e` + U+0301 stay different, ordered by bytes where the provider
  ties. Only order can change between servers.
- with a **nondeterministic** collation (ICU only), `0` is the provider's equality, so
  equality merges and splits are possible.

Equality here is SQL `=` under the named collation, not byte equality and not
`Intl`-style `compare() == 0`.

## Supported servers

- PostgreSQL **15 through 18**, checked against the `pg_collation` catalogs of
  `REL_15`..`REL_18` and run on the official images for each major
  ([matrix](../evidence/postgres-collation/version-matrix.json): ICU, libc and, from 17,
  builtin collations). Servers outside the range are refused with a reason; 14 and below
  or newer majors need their own verification.
- `server_encoding` must be `UTF8`. Other encodings are refused.
- The collation must be visible for that encoding (`pg_collation.collencoding` is `-1` or
  the database encoding), as for any `COLLATE` clause.
- The PostgreSQL client `psql` is the only extra requirement; Python needs no packages.
  The tests and the saved case used the `psql` shipped in each server image (same major as
  the server); other client versions are not separately verified.

## Profile

```json
{
  "version": 1,
  "contract": "postgresql.text.v1",
  "locale": "und",
  "options": { "collation": { "schema": "app", "name": "text_order" } }
}
```

`locale` must be `"und"`: the named collation defines the locale, and its actual settings
are recorded as observations. `options` contains exactly `collation.schema` and
`collation.name`: nonempty, no U+0000, at most 63 UTF-8 bytes (`NAMEDATALEN - 1`). Schema
and name are separate fields, so dots and quotes in names are data. Keep the profile
identical on both sides: `compare` requires identical requested profiles, and the profile
contains nothing environment specific.

Anything else (other contract or options, a missing collation, an unsupported server
version or encoding, an unknown provider) produces `unsupported` with a reason and no
comparisons. A missing collation is a refusal; nothing falls back to another collation.

## Capture and compare

```sh
export PGSERVICE=old-server            # or PGHOST/PGPORT/PGUSER/PGDATABASE/PGPASSFILE ...
uv run --locked collationdelta capture \
  --corpus examples/postgres/corpus.json --profile examples/postgres/order.profile.json \
  --output /tmp/old.json -- python "$(uv run --locked collationdelta postgres-adapter)"
export PGSERVICE=new-server
uv run --locked collationdelta capture \
  --corpus examples/postgres/corpus.json --profile examples/postgres/order.profile.json \
  --output /tmp/new.json -- python "$(uv run --locked collationdelta postgres-adapter)"
uv run --locked collationdelta compare /tmp/old.json /tmp/new.json
```

Only the two capture files are needed for the comparison. Run the same corpus twice
against one server to get a control capture.

Environment read by the adapter:

- standard libpq/`psql` variables and files for connection and authentication;
- `COLLATIONDELTA_PSQL`: client executable (default `psql` from `PATH`);
- `COLLATIONDELTA_PG_STATEMENT_TIMEOUT_MS`: server statement timeout, 1..3600000
  (default 10000). Raise it for large corpora with long strings; the adapter also runs
  inside the usual `--timeout`, `--stdout-limit` and `--stderr-limit` of `capture`.

## What is recorded

`effective` holds the settings that determined the result:

- `contract`, `operators`;
- `collation`: `schema`, `name`, `provider` (`libc`, `icu`, `builtin`, `default`),
  `deterministic`, `locale`, `icu_rules`, `lc_collate`, `lc_ctype`.

`runtime.postgresql` holds the server and its versions:

- `version` (full `version()` string), `server_version`, `server_version_num`,
  `server_encoding`, `client_encoding`;
- `collation`: `stored` (`pg_collation.collversion`), `actual`
  (`pg_collation_actual_version()`), and `match` when both are known. They are different
  facts: `stored` is what the catalog remembers, `actual` is what the running server's
  provider reports now;
- `unavailable`: for every `null` fact, the reason (not applicable to the provider, column
  absent in this major, or the server returned NULL).

`runtime.client` names the `psql` program and its version. Client-side ICU or libc
versions are never recorded: they say nothing about the server.

These values explain a finding; they are not findings. Two captures with different server
versions, locales or collation versions but identical relations compare as `STABLE`. A
finding is always a concrete pair with its old and new sign.

## Safety

- One `psql` run, one transaction: `BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY`,
  ended by `ROLLBACK`. The adapter refuses a session that is not read-only UTF8. No table,
  temporary object or other object is created.
- `SET LOCAL search_path = pg_catalog, pg_temp` and operators written as
  `OPERATOR(pg_catalog.<)` so nothing in the application's schemas can replace them.
  `SET LOCAL statement_timeout` bounds each statement.
- The corpus travels as data inside the script: every string is hex-encoded bytes decoded
  by `convert_from(decode(..., 'hex'), 'UTF8')`. Strings are not normalized, trimmed or
  otherwise changed. Schema and collation names are written as ASCII-only `U&"\+XXXXXX"`
  identifiers, so quotes, backslashes, semicolons, newlines and non-ASCII characters are
  inert. The lookup of the collation in `pg_collation` uses the same hex literals.
- Rows come from a server-side cursor, one `FETCH` per left entry, so after a timeout or a
  server error the rows `psql` had already returned are kept. The first `FETCH` also pays
  for decoding the corpus, so very large corpora need a larger statement timeout.
- Connection data and credentials are not in argv, the script, captures or diagnostics:
  `psql` reads them from the standard environment and files, runs with `-w` (never
  prompts) and `-X` (no `psqlrc`), and the adapter redacts known secret values and
  `password=` / URL userinfo patterns from the one diagnostic line it keeps. Captures still
  contain the corpus, the adapter argv, the working directory and server version strings;
  review them before sharing.

## Failures

- U+0000 in a corpus value: PostgreSQL `text` cannot hold it. Every pair with that entry
  fails with an explicit reason; other pairs are observed. Capture exits 2.
- Missing collation, unsupported server version/encoding/profile: `unsupported`, exit 2,
  server facts that are known are kept.
- Statement timeout or error after the server was reached, a killed `psql`, truncated
  or malformed output: `unresolved`. Complete rows that reached the adapter are kept (a
  `psql` killed by a signal may lose rows it had not yet flushed), the remaining pairs fail
  with the reason, exit 2. An unterminated final line is ignored. A row of the wrong length or
  with inconsistent operators fails only its pairs. The server may word a timeout that
  fires during planning as "canceling statement due to user request"; the adapter notes
  the configured statement timeout in such cases. That note is recognized from English
  server messages; with another `lc_messages` the verbatim diagnostic is kept without it.
- Connection failure, authentication failure, missing `psql`, no server metadata,
  duplicate or unexpected output lines: adapter error, `capture` exit 3, no capture and an
  existing destination is untouched.

Incomplete captures never turn unknown pairs into equality.

## Reproducible test stand

[`scripts/reproduce_postgres_case.py`](../scripts/reproduce_postgres_case.py) starts two
disposable containers from the image pinned by digest in
[`scripts/postgres-pins.json`](../scripts/postgres-pins.json) (pull it first; the script
never pulls), publishes no ports, uses each container's own `psql` through
[`scripts/psql-docker-exec.sh`](../scripts/psql-docker-exec.sh), and removes the
containers at the end:

```sh
docker pull postgres@sha256:e3d24f6906d0760bf4da0dae872415391ededefad23fd471c47dc53b0ddf3c42
uv run --locked python scripts/reproduce_postgres_case.py --output /tmp/postgres-case
uv run --locked python scripts/reproduce_postgres_case.py --matrix --output /tmp/postgres-case
```

This is a **configuration control**: both servers are the same image, and the schema
`cd_stand` has collations with the same qualified names but different definitions
(`und-u-kf-upper` versus `und-u-kf-lower` for order; `und-u-ks-level3` versus
`und-u-ks-level1`, nondeterministic, for equality). The difference is created on purpose.
It is not a PostgreSQL, ICU or libc upgrade and not evidence about one.
The [saved case](../evidence/postgres-collation/README.md) records image identity,
creation statements, catalog rows, captures, controls and reports.

Integration tests run with `COLLATIONDELTA_POSTGRES_STAND=1`; they need Docker and the
pinned image already present and fail if it is missing. Without the variable they skip
visibly.

## Limits

- A finite corpus says nothing about all strings. Metadata does not authenticate a server.
- Only `text` comparison under one explicit collation is observed. Indexes, `UNIQUE`,
  `GROUP BY`, `varchar`/`char(n)` padding rules, `citext` and the database default
  collation are out of scope.
- ICU/libc/builtin behavior of each provider is whatever the server reports. Nothing is
  verified against Unicode or CLDR data.
