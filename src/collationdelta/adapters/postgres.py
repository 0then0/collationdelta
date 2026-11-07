#!/usr/bin/env python3
"""Observe PostgreSQL ``text`` comparisons on the server through the ``psql`` client.

Contract ``postgresql.text.v1``: every requested ordered pair is evaluated by the
server's built-in ``<``, ``=`` and ``>`` operators on ``text`` with an explicitly named,
schema-qualified collation. Equality is the server's ``=`` result, not a provider-only
``compare() == 0`` result: with a deterministic collation PostgreSQL resolves ties by
bytes. The corpus is sent as data inside one read-only transaction; no table is created.

Standard library only. Connection and authentication come from libpq's standard
environment (``PGHOST``, ``PGSERVICE``, ``PGPASSFILE`` ...) and ``psql`` itself; the
adapter never puts connection data in argv and never prints it.

Environment: ``COLLATIONDELTA_PSQL`` (client executable, default ``psql``) and
``COLLATIONDELTA_PG_STATEMENT_TIMEOUT_MS`` (server statement timeout, default 10000).
"""

import json
import os
import re
import shutil
import subprocess
import sys

CONTRACT = "postgresql.text.v1"
# Server majors checked against REL_15..REL_18 catalogs and the integration stand.
MIN_VERSION_NUM, MAX_VERSION_NUM = 150000, 189999
NAMEDATALEN_BYTES = 63
PROVIDERS = {"d": "default", "c": "libc", "i": "icu", "b": "builtin"}
DEFAULT_TIMEOUT_MS = 10_000
ADAPTER = {"name": "collationdelta-postgresql", "version": "1", "contract": CONTRACT}


class AdapterError(Exception):
    """Failure without a trustworthy server observation; reported on stderr, exit 1."""


def quote_json(value):
    return json.dumps(value, ensure_ascii=True)


def redact(message):
    for name in ("PGPASSWORD", "PGSSLPASSWORD"):
        secret = os.environ.get(name)
        if secret:
            message = message.replace(secret, "***")
    message = re.sub(r"(?i)(password|passfile|sslpassword)\s*=\s*\S+", r"\1=***", message)
    message = re.sub(r"(?i)([a-z][a-z0-9+.-]*://)[^/@\s]*@", r"\1***@", message)
    return ascii(message.strip())[:400]


def first_line(stderr):
    lines = [line for line in stderr.decode("utf-8", errors="replace").splitlines() if line.strip()]
    return redact(lines[0] if lines else "no diagnostic")


def uident(value):
    """Quoted identifier written only with ASCII Unicode escapes (server encoding UTF8)."""
    return 'U&"' + "".join(f"\\+{ord(char):06X}" for char in value) + '"'


def literal(value):
    """Text expression built from hex bytes: independent of quoting and client encoding."""
    hexed = value.encode("utf-8").hex()
    return f"pg_catalog.convert_from(pg_catalog.decode('{hexed}', 'hex'), 'UTF8')"


def valid_name(value):
    return (
        isinstance(value, str)
        and value != ""
        and "\x00" not in value
        and len(value.encode("utf-8")) <= NAMEDATALEN_BYTES
    )


def requested_collation(profile):
    """Return ((schema, name), None) or (None, reason)."""
    if profile.get("contract") != CONTRACT:
        return None, f"requires contract {CONTRACT}"
    if profile.get("locale") != "und":
        return None, 'locale must be "und": the named collation defines the locale'
    options = profile.get("options")
    if not isinstance(options, dict) or set(options) != {"collation"}:
        return None, 'options must be exactly {"collation": {"schema": ..., "name": ...}}'
    collation = options["collation"]
    if not isinstance(collation, dict) or set(collation) != {"schema", "name"}:
        return None, "options.collation must contain exactly schema and name"
    for key in ("schema", "name"):
        if not valid_name(collation[key]):
            return None, (
                f"collation {key} must be a nonempty string without U+0000, "
                f"at most {NAMEDATALEN_BYTES} UTF-8 bytes"
            )
    return (collation["schema"], collation["name"]), None


def lookup_clause(schema, name):
    return (
        "FROM pg_catalog.pg_collation AS c "
        "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.collnamespace "
        f'WHERE n.nspname::pg_catalog.text COLLATE pg_catalog."C" = {literal(schema)} '
        f'COLLATE pg_catalog."C" '
        f'AND c.collname::pg_catalog.text COLLATE pg_catalog."C" = {literal(name)} '
        f'COLLATE pg_catalog."C" '
        "AND c.collencoding IN (-1, pg_catalog.pg_char_to_encoding("
        "pg_catalog.current_setting('server_encoding'))) "
        "ORDER BY (c.collencoding = -1) LIMIT 1"
    )


def script(schema, name, values, timeout_ms):
    """psql script. Rows are tagged ``R<index>:<codes>``; metadata is one ``M{json}`` line."""
    lookup = lookup_clause(schema, name)
    metadata = (
        "SELECT 'M' || (pg_catalog.json_build_object("
        "'version', pg_catalog.version(), "
        "'server_version', pg_catalog.current_setting('server_version'), "
        "'server_version_num', pg_catalog.current_setting('server_version_num'), "
        "'server_encoding', pg_catalog.current_setting('server_encoding'), "
        "'client_encoding', pg_catalog.current_setting('client_encoding'), "
        "'read_only', pg_catalog.current_setting('transaction_read_only'), "
        "'collation', (SELECT pg_catalog.json_build_object("
        "'row', pg_catalog.to_jsonb(c), "
        "'actual_version', pg_catalog.pg_collation_actual_version(c.oid)) "
        f"{lookup})"
        ")::pg_catalog.text);"
    )
    guard = (
        f"SELECT coalesce((SELECT true {lookup}), false) "
        "AND pg_catalog.current_setting('server_version_num')::pg_catalog.int4 "
        f"BETWEEN {MIN_VERSION_NUM} AND {MAX_VERSION_NUM} "
        "AND pg_catalog.current_setting('server_encoding') = 'UTF8' "
        "AND pg_catalog.current_setting('transaction_read_only') = 'on' AS cd_ok \\gset"
    )
    lines = [
        "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;",
        "SET LOCAL search_path = pg_catalog, pg_temp;",
        f"SET LOCAL statement_timeout = {timeout_ms};",
        metadata,
        guard,
        "\\if :cd_ok",
    ]
    if values:
        collate = f"COLLATE {uident(schema)}.{uident(name)}"

        def operator(symbol):
            return (
                f"(CASE WHEN (a.v {collate}) OPERATOR(pg_catalog.{symbol}) (b.v {collate}) "
                "THEN {weight} ELSE 0 END)"
            )

        code = " + ".join(
            operator(symbol).replace("{weight}", str(weight))
            for symbol, weight in (("<", 1), ("=", 2), (">", 4))
        )
        rows = ", ".join(f"({index}, {literal(value)})" for index, value in enumerate(values))
        lines.append(
            "DECLARE cd_cursor NO SCROLL CURSOR FOR "
            f"WITH c(i, v) AS MATERIALIZED (VALUES {rows}) "
            "SELECT 'R' || a.i::pg_catalog.text || ':' || (SELECT pg_catalog.string_agg("
            f"({code})::pg_catalog.text, '' ORDER BY b.i) FROM c AS b) FROM c AS a;"
        )
        lines.extend("FETCH 1 FROM cd_cursor;" for _ in values)
    lines += ["\\endif", "ROLLBACK;"]
    return ("\n".join(lines) + "\n").encode("ascii")


def run_psql(argv, data):
    env = dict(os.environ)
    env["PGCLIENTENCODING"] = "UTF8"
    env["PGAPPNAME"] = "collationdelta"
    env.setdefault("PGCONNECT_TIMEOUT", "10")
    try:
        return subprocess.run(argv, input=data, capture_output=True, env=env, check=False)
    except FileNotFoundError:
        raise AdapterError(
            f"{argv[0]!a} not found; install the PostgreSQL client or set COLLATIONDELTA_PSQL"
        ) from None
    except OSError as exc:
        raise AdapterError(f"cannot run psql: {exc.strerror}") from None


def client_version(psql):
    done = run_psql([psql, "--version"], b"")
    line = done.stdout.decode("utf-8", errors="replace").strip()
    if done.returncode != 0 or not line:
        raise AdapterError("psql --version failed")
    return line.splitlines()[0]


def parse_output(stdout, count):
    """Return (metadata or None, {row index: codes}); incomplete final lines are ignored."""
    try:
        decoded = stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise AdapterError("psql output is not valid UTF-8") from None
    lines = decoded.split("\n")[:-1]  # the last element is empty or an unterminated line
    metadata, rows = None, {}
    for line in lines:
        if line.startswith("M"):
            if metadata is not None:
                raise AdapterError("duplicate metadata line from psql")
            try:
                metadata = json.loads(line[1:])
            except ValueError:
                raise AdapterError("malformed metadata line from psql") from None
            continue
        match = re.fullmatch(r"R(\d+):(.*)", line)
        if not match or int(match.group(1)) >= count:
            raise AdapterError("unexpected output line from psql")
        index = int(match.group(1))
        if index in rows:
            raise AdapterError(f"duplicate result row {index} from psql")
        rows[index] = match.group(2)
    return metadata, rows


def collation_facts(metadata):
    """Normalize the catalog row into effective settings and explicit unavailable reasons."""
    found = metadata["collation"]
    row, actual = found["row"], found["actual_version"]
    provider = PROVIDERS.get(row.get("collprovider"))
    if provider is None:
        return None, None, f"unknown collation provider {row.get('collprovider')!a}"
    unavailable = {}

    def field(label, key, missing):
        if key is None or key not in row:
            unavailable[label] = missing
            return None
        value = row[key]
        if value is None:
            unavailable[label] = f"NULL in pg_collation (unset or not applicable to {provider})"
        return value

    locale_key = next((k for k in ("colllocale", "colliculocale") if k in row), None)
    collation = {
        "provider": provider,
        "deterministic": row["collisdeterministic"],
        "locale": field("locale", locale_key, "no locale column in this pg_collation"),
        "icu_rules": field("icu_rules", "collicurules", "pg_collation.collicurules is absent"),
        "lc_collate": field("lc_collate", "collcollate", "pg_collation.collcollate is absent"),
        "lc_ctype": field("lc_ctype", "collctype", "pg_collation.collctype is absent"),
    }
    stored = field("stored_version", "collversion", "pg_collation.collversion is absent")
    if actual is None:
        unavailable["actual_version"] = "pg_collation_actual_version() returned NULL"
    versions = {
        "stored": stored,
        "actual": actual,
        "match": None if stored is None or actual is None else stored == actual,
    }
    return collation, versions, unavailable


def pair_results(entries, usable, rows, failure):
    """Every ordered pair: an observed sign or an explicit reason; never an invented value."""
    signs = {"1": -1, "2": 0, "4": 1}
    position = {entry["id"]: index for index, entry in enumerate(usable)}
    results = []
    for left in entries:
        for right in entries:
            base = {"left": left["id"], "right": right["id"]}
            reason = None
            if "\x00" in left["value"] or "\x00" in right["value"]:
                reason = "entry contains U+0000, which PostgreSQL text cannot represent"
            else:
                codes = rows.get(position[left["id"]])
                if codes is None:
                    reason = failure or "server returned no row for the left entry"
                elif len(codes) != len(usable) or any(c not in "01234567" for c in codes):
                    reason = "server returned a malformed row"
                else:
                    code = codes[position[right["id"]]]
                    if code in signs:
                        results.append(dict(base, status="ok", value=signs[code]))
                        continue
                    reason = f"operators <, =, > were inconsistent (code {code})"
            results.append(dict(base, status="error", reason=reason))
    return results


def response(status, runtime, effective=None, reason=None, results=(), adapter=ADAPTER):
    output = {
        "protocol_version": 1,
        "status": status,
        "effective": effective,
        "runtime": runtime,
        "adapter": adapter,
        "results": list(results),
    }
    if reason:
        output["reason"] = reason
    return output


def observe(request):
    if not isinstance(request, dict) or request.get("protocol_version") != 1:
        raise AdapterError("unsupported adapter protocol version")
    entries = request["corpus"]["entries"]
    pair, why = requested_collation(request["profile"])
    if pair is None:
        return response("unsupported", {"postgresql": {"contacted": False}}, reason=why)
    schema, name = pair
    label = f"{quote_json(schema)}.{quote_json(name)}"
    try:
        timeout_ms = int(
            os.environ.get("COLLATIONDELTA_PG_STATEMENT_TIMEOUT_MS", DEFAULT_TIMEOUT_MS)
        )
    except ValueError:
        timeout_ms = 0
    if not 1 <= timeout_ms <= 3_600_000:
        raise AdapterError("COLLATIONDELTA_PG_STATEMENT_TIMEOUT_MS must be 1..3600000")
    psql = os.environ.get("COLLATIONDELTA_PSQL") or "psql"
    if os.sep not in psql and shutil.which(psql) is None:
        raise AdapterError(
            "psql not found; install the PostgreSQL client or set COLLATIONDELTA_PSQL"
        )
    version = client_version(psql)
    usable = [entry for entry in entries if "\x00" not in entry["value"]]
    data = script(schema, name, [entry["value"] for entry in usable], timeout_ms)
    # Connection data is never placed in argv: libpq reads the standard environment.
    done = run_psql([psql, "-X", "-w", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-f", "-"], data)
    metadata, rows = parse_output(done.stdout, len(usable))
    if metadata is None:
        what = "cannot connect to PostgreSQL" if done.returncode == 2 else "no server metadata"
        raise AdapterError(f"{what} (psql exit {done.returncode}): {first_line(done.stderr)}")
    num = int(metadata["server_version_num"])
    runtime = {
        "postgresql": {
            "version": metadata["version"],
            "server_version": metadata["server_version"],
            "server_version_num": num,
            "server_encoding": metadata["server_encoding"],
            "client_encoding": metadata["client_encoding"],
        },
        "client": {"program": "psql", "version": version},
    }
    adapter = dict(ADAPTER, statement_timeout_ms=timeout_ms)
    known = runtime["postgresql"]
    if metadata["client_encoding"] != "UTF8" or metadata["read_only"] != "on":
        raise AdapterError("session is not UTF8 client encoding and read-only; refusing")
    if not MIN_VERSION_NUM <= num <= MAX_VERSION_NUM:
        return response(
            "unsupported",
            runtime,
            reason=f"PostgreSQL {metadata['server_version']!a} is outside supported 15..18",
            adapter=adapter,
        )
    if metadata["server_encoding"] != "UTF8":
        return response(
            "unsupported",
            runtime,
            reason=f"server_encoding {metadata['server_encoding']!a} is not UTF8",
            adapter=adapter,
        )
    if metadata["collation"] is None:
        reason = f"collation {label} does not exist for encoding UTF8"
        return response("unsupported", runtime, reason=reason, adapter=adapter)
    collation, versions, unavailable = collation_facts(metadata)
    if collation is None:
        return response("unsupported", runtime, reason=unavailable, adapter=adapter)
    known["collation"] = versions
    known["unavailable"] = {f"collation.{key}": value for key, value in unavailable.items()}
    effective = {
        "contract": CONTRACT,
        "operators": ["<", "=", ">"],
        "collation": dict(schema=schema, name=name, **collation),
    }
    failure = None
    if done.returncode != 0 or len(rows) != len(usable):
        # PostgreSQL may word a timeout that fires during planning as "user request".
        cancelled = b"canceling statement" in done.stderr
        cause = f"server canceled a statement (statement_timeout {timeout_ms} ms); " * cancelled
        failure = (
            f"observation stopped after {len(rows)} of {len(usable)} rows: {cause}"
            f"psql exit {done.returncode}: {first_line(done.stderr)}"
        )
    results = pair_results(entries, usable, rows, failure)
    status = "ok" if failure is None else "unresolved"
    return response(status, runtime, effective, failure, results, adapter)


def main():
    try:
        output = observe(json.load(sys.stdin))
        json.dump(output, sys.stdout, ensure_ascii=True, allow_nan=False)
        sys.stdout.write("\n")
        return 0
    except AdapterError as exc:
        print(f"postgresql adapter error: {exc}", file=sys.stderr)
    except (KeyError, TypeError, ValueError) as exc:
        print(
            f"postgresql adapter error: invalid request or server reply ({exc!r})", file=sys.stderr
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
