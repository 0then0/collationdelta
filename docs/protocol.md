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

`localeMatcher` is fixed to `lookup`, not configurable in v0.1. Supported locale matching is checked before construction. The adapter accepts canonical locale spelling and normal lookup negotiation; it does not require literal requested/resolved equality. Explicit `collation` or locale `co` requests must resolve to the requested collation. Explicit options override Unicode extensions. The recognized `kn` and `kf` requests must also resolve; other locale extensions are outside this adapter contract. Private-use subtags following `-x-` are not interpreted as Unicode extension requests. An unavailable locale, invalid/unknown option, unsupported collation, or ignored supported request becomes `unsupported` with a reason and any known resolved options, never a silently substituted valid capture.

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

The digest is `sha256:` plus lowercase hexadecimal SHA-256 over the entire capture object with only `digest` removed, serialized using Python `json.dumps(ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)` and ASCII encoding. There is no trailing newline in the hashed bytes. Object order/indentation do not matter; array order does. This definition is intended for Python v0.1 producers, not as a general cross-language JSON canonicalization standard. The digest is not authentication.

## Report format v1

The root contains `report_version: 1`, `status`, `complete`, `requested`, `sides`, `finding_count`, and `findings`. Each side contains its capture digest, effective settings, runtime/adapter metadata, global status/reason, and explicit coverage. Findings contain `id`, `kind`, two `records`, `old_relation`, and `new_relation`. Record representations are constructed once per ID and reused in memory; JSON serialization is streamed while preserving the full evidence for every finding. Each record has original `id`/`value`, JSON `escaped` text, and `code_points` in `U+XXXX` notation, using more digits when needed.

Findings sort by the Unicode scalar order of the ID pair. Each unordered pair appears once. Finding IDs use `cd1-` plus the full SHA-256 of requested profile, records, change kind, and signs, so they remain stable across repeated captures despite invocation timestamps. Coverage must be complete on both sides for `STABLE` or `DRIFT`. For partial captures, a finding requires the same ordered pair to be observed successfully on both sides. Missing diagonals or reciprocal results do not discard that direct witness. A shared reverse pair is oriented by stable IDs; observations in opposite orientations alone are not a direct witness. Known findings with any incomplete side produce `DRIFT_INCOMPLETE`; otherwise incomplete observations produce `INCOMPLETE`. Schema/compatibility/consistency errors have no valid comparison report and are printed to stderr with exit 3.
