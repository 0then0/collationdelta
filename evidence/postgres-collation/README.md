# PostgreSQL configuration-control case

Two disposable servers started from one image, `postgres@sha256:e3d24f69…` (PostgreSQL
18.6, linux/arm64; full identity in `experiment.json`). Each has schema `cd_stand` with
two collations of the same qualified names and **different definitions, created on
purpose**. This is a configuration control. It is not a PostgreSQL, ICU or libc upgrade.

- `cd_stand.cd_order`: ICU, deterministic. `und-u-kf-upper` (old) versus
  `und-u-kf-lower` (new). Case-only pairs reverse order.
- `cd_stand.cd_equality`: ICU, nondeterministic. `und-u-ks-level3` (old) versus
  `und-u-ks-level1` (new). Strings that differ only in case, accents or quote shape merge.

The corpus is `examples/postgres/corpus.json`: 25 unchanged entries including case
pairs, composed and decomposed `é`/`ä`, quotes, backslashes, a literal backslash-n, LF and
CRLF, an empty string, an emoji and SQL-looking text. Each scenario has 625/625 comparisons
per capture.

Files, for `{old,new}` × `{order,equality}`:

- `*.capture.json` and `*-repeat.capture.json`: two independent captures per server;
  `*-control.report.json`: their `STABLE` comparison.
- `order.report.json` / `.txt`: `DRIFT`, two `order_reversal` findings (`a`/`A`, `b`/`B`).
- `equality.report.json` / `.txt`: `DRIFT`, nine `equality_merge` findings.
- `experiment.json`: image identity, `CREATE` statements, `pg_collation` rows and
  `pg_collation_actual_version` per server, offline results, and for every finding the
  sign returned by a direct `SELECT a < b, a = b, a > b` with `COLLATE` run in `psql`,
  with the strings passed as psql variables rather than through the adapter.
- `version-matrix.json`: a small capture for each of PostgreSQL 15, 16, 17 and 18 (image
  digests in `scripts/postgres-pins.json`) with ICU and libc collations, plus builtin from
  17. It supports the documented 15–18 range; it compares nothing across versions.

Reanalyze without Docker, PostgreSQL or `psql`:

```sh
collationdelta compare evidence/postgres-collation/old.order.capture.json \
  evidence/postgres-collation/new.order.capture.json
# Exit 1: DRIFT, two order reversals.
collationdelta compare evidence/postgres-collation/old.equality.capture.json \
  evidence/postgres-collation/new.equality.capture.json
# Exit 1: DRIFT, nine equality merges.
collationdelta compare evidence/postgres-collation/old.order.capture.json \
  evidence/postgres-collation/old.order-repeat.capture.json
# Exit 0: STABLE.
```

Regenerate with `scripts/reproduce_postgres_case.py`; see
[the guide](../../docs/postgres-capture.md#reproducible-test-stand). Captures record the
local interpreter and checkout paths of the machine that created them.

## Unique index experiment

The index experiment uses the same pinned PostgreSQL image and the two definitions of
`cd_stand.cd_equality`. The source uses ICU `und-u-ks-level3` and the target uses ICU
`und-u-ks-level1`, both with `deterministic = false`. This changes the collation
configuration while keeping the server image fixed.

[`unique-index.json`](unique-index.json) records the result for the two entries
`lower-a` (`a`) and `upper-a` (`A`) from the recorded comparison corpus. The earlier
equality report observes an equality merge for these IDs. The index experiment loads
them into a temporary `text NOT NULL` column on each server and issues
`CREATE UNIQUE INDEX ... USING btree` with `COLLATE cd_stand.cd_equality` on the index key.
The source index builds (`00000`), and the target returns `23505`. A separate `SELECT`
with the collation returns `false` on the source and `true` on the target.

The clean control (`a`, `b`) builds both indexes. The source-duplicate control stores
`a` under two IDs and returns `23505` on both sides.

Run these commands from the repository root with Docker running.

```sh
docker pull postgres@sha256:e3d24f6906d0760bf4da0dae872415391ededefad23fd471c47dc53b0ddf3c42
uv run --locked python scripts/check_postgres_unique.py \
  --corpus examples/postgres/unique-conflict.json \
  --output /tmp/postgres-unique-conflict.json
uv run --locked python scripts/check_postgres_unique.py \
  --corpus examples/postgres/unique-clean.json \
  --output /tmp/postgres-unique-clean.json
uv run --locked python scripts/check_postgres_unique.py \
  --corpus examples/postgres/unique-source-duplicate.json \
  --output /tmp/postgres-unique-source-duplicate.json
```

The opt-in integration tests exercise the three corpora, an independent equality query,
a connection failure and a server-side index timeout (`57014`).

```sh
COLLATIONDELTA_POSTGRES_STAND=1 uv run --locked pytest -q tests/test_postgres_unique.py
```

Run this standalone equality query on each configured server to check the conflict pair.

```sql
SELECT ('a'::text COLLATE cd_stand.cd_equality)
     = ('A'::text COLLATE cd_stand.cd_equality);
```

The script runs `psql` inside instances it starts for the check. The instances run
without network access, keep PostgreSQL data in temporary memory-backed storage and
are removed on exit, including after SIGINT or SIGTERM. `--configuration FILE`
accepts a JSON object with `source` and `target` definitions. Each definition has
`schema` and `name` identifier strings, a `provider` (`icu`, `libc`, or `builtin`),
a `locale`, and a Boolean
`deterministic`. Omit the option to use the pinned ICU definitions above. The corpus
uses the regular JSON format and permits duplicate values with distinct IDs. It is
limited to 1–256 entries, a 32 MiB JSON input file, a 1 MiB canonical JSON document, and
16 KiB of combined JSON-encoded IDs. U+0000 is rejected in key values.
`--statement-timeout-ms` defaults to 10000 and accepts 1–60000.

Per-side `index_status` is `built`, `unique_violation`, or `incomplete`. `23505` is
evidence that the index rejected the keys. PostgreSQL comparisons under the same
collation confirm the pair. `witness_entries` copies the associated values from the
input corpus, so treat the report as data from that corpus. The report preserves a
rejection if witness confirmation is incomplete. The top-level result is `no_conflict`,
`new_conflict`, `source_conflict`, or `incomplete`, with a separate completeness flag.
A client failure after an index outcome preserves the SQLSTATE and sets `complete` to
false. The side records that failure in `process_failure`.
Exit 0 means the check finished, including a confirmed conflict. Exit 2 with a report
means the check was incomplete, exit 130 means interrupted, and exit 1 means input
validation or file I/O failed. Results apply to the supplied keys and index definition.
