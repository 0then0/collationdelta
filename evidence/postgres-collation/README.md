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
