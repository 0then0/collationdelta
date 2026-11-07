# Adapter protocol v1

An adapter is an executable argv supplied after `capture ... --`. A single process reads one UTF-8 JSON document from stdin to EOF and returns one UTF-8 JSON document on stdout, then exits 0. Stdout is reserved for the protocol; diagnostics go to stderr. No shell is involved. The runtime containing the application comparator must be available for capture only.

## Request

```json
{
  "protocol_version": 1,
  "corpus": {
    "version": 1,
    "entries": [
      { "id": "a", "value": "A" },
      { "id": "b", "value": "a" }
    ]
  },
  "profile": {
    "version": 1,
    "contract": "intl.collator.v1",
    "locale": "en",
    "options": { "sensitivity": "base" }
  }
}
```

The request asks for every ordered pair of stable IDs, including self comparisons. There is no sampling and no separate process per pair. The profile contract identifies the application's comparator semantics. An adapter must explicitly reject an unsupported contract/configuration or report unresolved configuration. It must never invent a comparison for a caught exception.

## Response

```json
{
  "protocol_version": 1,
  "status": "ok",
  "effective": { "locale": "en", "sensitivity": "base" },
  "runtime": { "node": "v24.21.0", "icu": "78.3", "cldr": "48.0", "unicode": "17.0" },
  "adapter": { "name": "example", "version": "1" },
  "results": [
    { "left": "a", "right": "a", "status": "ok", "value": 0 },
    { "left": "a", "right": "b", "status": "ok", "value": 0 },
    { "left": "b", "right": "a", "status": "ok", "value": 0 },
    { "left": "b", "right": "b", "status": "ok", "value": 0 }
  ]
}
```

The metadata numbers above illustrate the response shape; actual capture metadata comes from the running adapter.

Global `status` is `ok`, `unsupported`, or `unresolved`. `effective` is an object or null; `ok` and any successful comparisons require a nonempty effective object. `runtime` and `adapter` are nonempty objects with implementation-specific metadata. Non-ok global responses require a nonempty string `reason`. `unsupported` returns no pair results. `unresolved` may include successful comparisons with known effective settings, but the capture remains incomplete.

Each pair result contains string `left`/`right` IDs and one of:

- `status: "ok"`, with a finite JSON number `value`. Booleans and strings are rejected. The core converts any magnitude to integer -1, 0, or +1 using exact decimal signs, including values such as `1e-400`. Configuration and metadata numbers that overflow finite floats or underflow to zero are rejected.
- `status: "error"` or `"unresolved"`, with a nonempty string `reason` and no `value`.

Pairs may arrive in any order. Duplicate, unrequested, malformed, or extra responses are errors. Missing pairs are counted explicitly and make the capture incomplete. Unknown top-level and result fields are rejected; implementation-specific metadata is allowed inside `effective`, `runtime`, and `adapter`. Duplicate JSON object keys and non-finite JSON numbers are errors. All JSON strings, including metadata and keys, must be valid scalar strings. JSON allows escaped controls and paired surrogate escapes.

## Transport limits

Default limits are a 30-second whole-process deadline, 16 MiB stdout, and 1 MiB stderr. Set `--timeout`, `--stdout-limit`, or `--stderr-limit` to positive values when needed. Stdin, stdout, and stderr are serviced concurrently with nonblocking I/O; stderr cannot fill an unread pipe and stall the process. The deadline includes writing stdin, reading both output streams, and waiting for process exit. On timeout, output-limit failure, or completion, the process group is terminated to avoid leaving descendants behind. This POSIX implementation targets Linux and macOS.

Nonzero process exit, timeout, oversized output, launch failure, malformed JSON, and contradictory observations return exit 3 and do not produce a new capture. JSON output is streamed into a temporary file beside the destination, flushed and atomically replaced only after successful serialization. Already-existing destination files are preserved on transport, serialization, size-limit, and write failures; temporary files are removed. A valid response with failed/missing results is saved with exit 2, preserving usable observations. Single-batch mode cannot recover protocol results from truncated stdout after a crash.

## Node reference adapter

The bundled adapter contract is `intl.collator.v1`. It calls `new Intl.Collator(locale, options)` and compares through `collator.compare`. It reports Node, ICU, CLDR, Unicode, architecture, platform, and `resolvedOptions()`.

Supported option values:

- `sensitivity`: `base`, `accent`, `case`, `variant`.
- `numeric`, `ignorePunctuation`: JSON booleans.
- `caseFirst`: `upper`, `lower`, `false` (the last is a string, as required by Intl).
- `usage`: `sort`, `search`.
- `collation`: a string accepted and actually resolved by the installed Intl provider.

`localeMatcher` is fixed to `lookup`, not configurable in this contract. Supported locale matching is checked and resolved settings are observed by construction; an unsupported locale never produces comparisons. The adapter accepts canonical locale spelling and normal lookup negotiation; it does not require literal requested/resolved equality. Explicit `collation` or locale `co` requests must resolve to the requested collation. Explicit options override Unicode extensions. The recognized `kn` and `kf` requests must also resolve; other locale extensions are outside this adapter contract. The Unicode extension ends at the next singleton introducing another locale extension. Private-use subtags following `-x-` are not interpreted as Unicode extension requests. An unavailable locale, invalid/unknown option, unsupported collation, or ignored supported request becomes `unsupported` with a reason and any known resolved options, never a silently substituted valid capture.

## Browser reference adapter

`collationdelta browser-adapter` locates the optional Chromium script. Node and
browser share one self-contained `intl.mjs` evaluator with identical strict option
validation, negotiation and pair failure behavior. The browser evaluates it through
structured Playwright arguments in `about:blank`. Executable captures remain v1;
user-opened page import uses the separately versioned formats below.

Both adapters add `runtime.intl` with `canonical_locale`, `supported_locales` (the
lookup `supportedLocalesOf` result), and `resolved_options`. Unknown information is
null. Unsupported locale responses retain resolved options when construction is
possible but always have empty results. Browser runtime metadata uses the existing
containers to separate browser, automation, host, selected executable/caller labels,
and execution mode. No browser ICU/CLDR/Unicode versions are inferred.

The browser adapter loads Playwright only from the selected installation prefix and
uses isolated credential storage in its temporary profile. See
[browser-capture.md](browser-capture.md) for optional installation,
executable selection, supported environment, additional adapter limits, process-group
cleanup, provenance and the pinned acceptance case.

## PostgreSQL reference adapter

`collationdelta postgres-adapter` locates `postgres.py`, a standard-library adapter for
contract `postgresql.text.v1`. It drives the installed `psql` client and records the
server's own `<`, `=` and `>` results for `text` under a named, schema-qualified
collation, so deterministic collations keep PostgreSQL's byte tie-break and equality is
SQL `=`. The profile is `locale: "und"` with exactly
`options.collation: {"schema": ..., "name": ...}`. Server and collation facts go into
`effective` (collation provider, locale, rules, deterministic) and `runtime.postgresql`
(server version and encoding, stored and actual collation version, explicit
`unavailable` reasons), never into the requested profile. Supported servers are
PostgreSQL 15 through 18 with UTF8 encoding. Unsupported profiles, servers and missing
collations return `unsupported`; a server failure after contact returns `unresolved`
with the completed rows; no server contact is an adapter error. See
[postgres-capture.md](postgres-capture.md).

## Custom application adapter

[application_adapter.py](../examples/application_adapter.py) is a runnable example showing where to import and call a real application comparator, return exceptions as pair failures, and supply runtime/effective metadata. Its demonstration contract is `demo.scalar-order.v1`, locale `und`, options `{}`. The example comparator uses Python scalar lexicographic order and is not a linguistic implementation.

Create a matching profile and invoke it with:

```sh
collationdelta capture --corpus examples/corpus.json --profile /path/to/demo-profile.json \
  --output /tmp/demo.json -- python examples/application_adapter.py
```

## Capture format v1

A capture contains `format_version: 1`, original `corpus`, `requested` profile, normalized `observation` response, recomputed `coverage`, `run` information, and `digest`. Coverage fields are `entries`, `expected_comparisons`, `completed_comparisons`, `failed_comparisons`, `missing_comparisons`, `complete`, and `consistency`. Identical string values under distinct IDs belong to one equality component; the original records and IDs are retained. Complete observations use `consistency: "verified"`; partial observations use `"consistent_partial"`.

`run` records `argv`, `cwd`, `platform`, `captured_at` (UTC ISO timestamp), `tool_version`, `timeout_seconds`, `stdout_limit_bytes`, `stderr_limit_bytes`, and decoded `stderr`. Non-UTF-8 diagnostics use replacement characters; protocol output itself requires strict UTF-8.

The digest is `sha256:` plus lowercase hexadecimal SHA-256 over the entire capture object with only `digest` removed, serialized using Python `json.dumps(ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)` and ASCII encoding. There is no trailing newline in the hashed bytes. Object order/indentation do not matter; array order does. This is the capture format v1 canonicalization rule, not a general cross-language JSON canonicalization standard. The digest is not authentication.

## Report format v1

The root contains `report_version: 1`, `status`, `complete`, `requested`, `sides`, `finding_count`, and `findings`. Each side contains its capture digest, effective settings, runtime/adapter metadata, global status/reason, and explicit coverage. Findings contain `id`, `kind`, two `records`, `old_relation`, and `new_relation`. Record representations are constructed once per ID and reused in memory; JSON serialization is streamed while preserving the full evidence for every finding. Each record has original `id`/`value`, JSON `escaped` text, and `code_points` in `U+XXXX` notation, using more digits when needed.

Findings sort by the Unicode scalar order of the ID pair. Each unordered pair appears once. Finding IDs use `cd1-` plus the full SHA-256 of requested profile, records, change kind, and signs, so they remain stable across repeated captures despite invocation timestamps. Coverage must be complete on both sides for `STABLE` or `DRIFT`. For partial captures, a finding requires the pair to be observed successfully in either direction on each side. Missing diagonals or reciprocal results do not discard that witness. Each side is independently oriented by stable IDs using the comparator's reciprocal sign rule. Opposite observed directions are sufficient; this normalization does not mark missing comparisons as completed. Known findings with any incomplete side produce `DRIFT_INCOMPLETE`; otherwise incomplete observations produce `INCOMPLETE`. Schema/compatibility/consistency errors have no valid comparison report and are printed to stderr with exit 3.

## Browser export v1

This is an observation from a user-opened static page, **not executable adapter
stdout or a capture**. `collationdelta import-browser EXPORT --output CAPTURE` accepts
it without launching a browser, executing commands, fetching URLs or resolving paths
from the file. The existing strict UTF-8/Unicode JSON decoder is unchanged. Duplicate
object keys (including escaped aliases), unpaired surrogates, non-finite/overflowing
numbers and nonzero numeric underflow are errors.

The exact root fields are:

- `browser_export_version`: integer `1`.
- `corpus` and `requested`: existing corpus/profile v1 documents. This path requires
  `intl.collator.v1`. Each compact UTF-8 document is at most 1 MiB; the complete export
  file is at most 16 MiB. The page additionally limits each uploaded file to 1 MiB.
- `observation`: protocol v1 response from the shared `observeIntl()`. Successful
  result values must already be integer signs `-1`, `0`, `1`, never booleans, floats,
  strings or arbitrary magnitudes. The page normalizes the native comparator return
  before JSON serialization. This intentionally differs from raw executable stdout,
  where the existing exact-decimal normalization still applies.
- `coverage`: the existing coverage object. The CLI recomputes it and requires exact
  agreement, including types. All ordered pairs must be present for status `ok`;
  individual `error` results remain incomplete. Timeouts/cancellations do not export
  a truncated prefix. `unsupported` has no results and remains incomplete.
- `metadata`: exactly `page_version: 1`, `captured_at` (UTC ISO timestamp),
  `execution_context: {"kind":"dedicated-worker","has_document":false,"has_process":false}`,
  `user_agent`, `navigator_platform`, and `caller_labels: {"label": "..."}`.
  Browser-reported user agent/platform strings are limited to 4096 scalar characters
  each, and the optional caller label to 256. Empty strings represent unavailable
  browser strings or an omitted label. No engine, architecture, ICU/CLDR, executable,
  process limits or browser version are inferred.

`observation.adapter` is exactly `{"contract":"intl.collator.v1"}`;
`observation.runtime` contains only `intl`, with exactly `canonical_locale`,
`supported_locales`, `resolved_options`. Unknown values are null. Supported locales
are null, empty, or the singleton recorded canonical locale. Known resolved options
are exactly `locale`, `usage`, `sensitivity`, `ignorePunctuation`, `collation`,
`numeric`, `caseFirst`, with the types/values defined by this contract, and must equal
`effective`. A successful observation requires supported locale metadata and resolved
settings. Explicit requested options and recognized canonical `co`/`kn`/`kf` requests
must agree with those settings. Failed negotiation is exported as `unsupported` with
its reason and any known settings; it never substitutes fallback results.

The page validates input safety and bounds. Python is the acceptance boundary for
saved evidence: it checks schemas, signs, coverage, duplicate/unrequested pairs,
identical strings, diagonal/reciprocal relations, equality transitivity and order
cycles with the existing relation validator. It does not reconstruct another
browser's Intl locale database or prove that a canonical locale/negotiation claim is
authentic. Metadata and consistent fabricated comparisons cannot establish runtime
identity. Labels are explicitly caller supplied.

There is **no digest in browser export v1**. This avoids imposing Python's
canonicalization rules on JavaScript. JSON.stringify preserves scalar strings via
UTF-8 or escapes, including controls and supplementary characters. The importer
rejects decimal spellings such as `1.0` for relation signs; there is no permissive
nested-number decoder. Ordinary profile/metadata numbers retain the existing Python
JSON semantics. Imported evidence receives the capture digest described below;
neither the export nor a digest authenticates its sender.

## Capture format v2: browser provenance

Executable `capture` continues to write v1. Browser import writes v2, containing
exactly `format_version: 2`, `corpus`, `requested`, normalized `observation`, recomputed
`coverage`, `provenance` and `digest`. There is no `run` object or invented argv/cwd.

`provenance` contains exactly:

```json
{
  "version": 1,
  "kind": "browser-export",
  "browser_export_version": 1,
  "metadata": { "page_version": 1, "captured_at": "2026-11-02T12:00:00.000Z",
    "execution_context": { "kind": "dedicated-worker", "has_document": false, "has_process": false },
    "user_agent": "browser-reported string", "navigator_platform": "browser-reported string",
    "caller_labels": { "label": "optional caller claim" } },
  "importer": { "tool_version": "0.2.0", "imported_at": "2026-11-02T12:01:00+00:00" }
}
```

The metadata above illustrates the schema, not a real browser claim. The importer
records its own tool version and UTC time separately from page-observed time and
caller labels. V2 uses the **same Python digest canonicalization** as v1, over the
whole capture except `digest`. Import validates before atomic replacement; malformed
exports and serialization failures preserve an existing output. Exit 0 means complete,
2 means valid incomplete/unsupported evidence saved, and 3 means validation/I/O error.

The updated offline compare accepts v1 and v2 together and preserves all previous
compatibility rules. V1 reports are unchanged. For a v2 side, report v1's side object
also includes its `provenance`, so JSON reports retain source context. Human output
continues to show settings and coverage; provenance is in the saved capture/report.
Older CLI versions do not understand v2; old v1 artifacts require no migration.
