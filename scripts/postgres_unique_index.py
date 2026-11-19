"""Probe one unique B-tree build inside a disposable PostgreSQL container."""

import json
import re
import signal
import subprocess
import tempfile

from collationdelta.adapters import postgres


class ProbeInterrupted(KeyboardInterrupt):
    """A cancellation that carries the evidence received before the interruption."""

    def __init__(self, result):
        super().__init__("index probe interrupted")
        self.result = result


def psql_argv(container):
    """Connect to the server's own Unix socket, with no host libpq configuration."""
    return [
        "exec",
        "-i",
        "-e",
        "PGCLIENTENCODING=UTF8",
        "-e",
        "PGCONNECT_TIMEOUT=5",
        container,
        "psql",
        "-h",
        "/var/run/postgresql",
        "-p",
        "5432",
        "-U",
        "postgres",
        "-d",
        "postgres",
        "-X",
        "-w",
        "-q",
        "-A",
        "-t",
    ]


def checked(statement, stage):
    """Stop setup at the first SQL error, with a machine-readable error code."""
    return [
        statement,
        "\\if :ERROR",
        f"\\echo E {stage} :SQLSTATE",
        "ROLLBACK;",
        "\\quit",
        "\\endif",
    ]


def index_script(entries, schema, name, timeout_ms):
    lookup = postgres.lookup_clause(schema, name)
    collate = f"COLLATE {postgres.uident(schema)}.{postgres.uident(name)}"
    server = (
        "WITH info AS MATERIALIZED (SELECT pg_catalog.version() AS version, "
        "pg_catalog.current_setting('server_version') AS server_version, "
        "pg_catalog.current_setting('server_version_num')::pg_catalog.int4 AS server_version_num, "
        "pg_catalog.current_setting('server_encoding') AS server_encoding, "
        "pg_catalog.current_setting('client_encoding') AS client_encoding, "
        "pg_catalog.current_setting('transaction_read_only') AS read_only) "
        "SELECT pg_catalog.row_to_json(info)::pg_catalog.text AS cd_server, "
        f"(server_version_num BETWEEN {postgres.MIN_VERSION_NUM} AND {postgres.MAX_VERSION_NUM} "
        "AND server_encoding = 'UTF8' AND client_encoding = 'UTF8' AND read_only = 'off') "
        "AS cd_supported FROM info \\gset"
    )
    collation = (
        "WITH info(catalog) AS MATERIALIZED (SELECT (SELECT pg_catalog.json_build_object("
        "'row', pg_catalog.to_jsonb(c), "
        "'actual_version', pg_catalog.pg_collation_actual_version(c.oid)) "
        f"{lookup})) "
        "SELECT coalesce(catalog::pg_catalog.text, 'null') AS cd_collation, "
        "(catalog IS NOT NULL AND catalog->'row'->>'collprovider' IN ('c', 'i', 'b', 'd')) "
        "AS cd_supported_collation FROM info \\gset"
    )
    lines = [
        "\\set ON_ERROR_STOP off",
        "\\set VERBOSITY sqlstate",
        *checked("BEGIN ISOLATION LEVEL REPEATABLE READ READ WRITE;", "transaction"),
        *checked(f"SET LOCAL statement_timeout = {timeout_ms};", "settings"),
        *checked("SET LOCAL search_path = pg_catalog, pg_temp;", "settings"),
        *checked(server, "server_provenance"),
        "\\echo P :cd_server",
        "\\if :cd_supported",
        *checked(collation, "collation_provenance"),
        "\\echo C :cd_collation",
        "\\if :cd_supported_collation",
        *checked(
            "CREATE TEMP TABLE pg_temp.cd_unique_keys (key pg_catalog.text NOT NULL) ON COMMIT DROP;",
            "create_table",
        ),
    ]
    if entries:
        rows = ",\n".join(f"({postgres.literal(entry['value'])})" for entry in entries)
        lines.extend(
            checked(f"INSERT INTO pg_temp.cd_unique_keys (key) VALUES\n{rows};", "load_keys")
        )
    lines.extend(
        [
            f"CREATE UNIQUE INDEX cd_unique_idx ON pg_temp.cd_unique_keys USING btree (key {collate});",
            "\\echo I :SQLSTATE",
            "\\endif",
            "\\endif",
            "ROLLBACK;",
        ]
    )
    return ("\n".join(lines) + "\n").encode("ascii")


def incomplete(reason, *, stage, sqlstate=None, provenance=None):
    return {
        "index_status": "incomplete",
        "sqlstate": sqlstate,
        "provenance": provenance,
        "stage": stage,
        "reason": reason,
    }


def parse_probe_output(stdout, schema, name, *, returncode=0, timed_out=False):
    try:
        markers = {}
        # Ignore an unterminated last line if psql was interrupted while writing it.
        for raw_line in stdout.split(b"\n")[:-1]:
            line = raw_line.decode("utf-8")
            marker, _, value = line.partition(" ")
            if marker not in {"P", "C", "E", "I"} or marker in markers or not value:
                raise ValueError
            markers[marker] = value
        facts = json.loads(markers["P"]) if "P" in markers else None
        catalog = json.loads(markers["C"]) if "C" in markers else None
        if facts is not None:
            if not isinstance(facts, dict):
                raise ValueError
            facts.pop("read_only")
        provenance = {"postgresql": facts, "collation": None} if facts is not None else None
        if catalog is not None:
            if (
                facts is None
                or not isinstance(catalog, dict)
                or not isinstance(catalog.get("row"), dict)
            ):
                raise ValueError
            settings, versions, unavailable = postgres.collation_facts({"collation": catalog})
            if settings is not None:
                facts["collation"] = versions
                facts["unavailable"] = {
                    f"collation.{key}": value for key, value in unavailable.items()
                }
                provenance["collation"] = {"schema": schema, "name": name, **settings}
        sqlstate = markers.get("I")
        stage = "create_index"
        if "E" in markers:
            if sqlstate is not None:
                raise ValueError
            stage, sqlstate = markers["E"].split(" ")
        if sqlstate is not None and not re.fullmatch(r"[0-9A-Z]{5}", sqlstate):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return incomplete("Unrecognized psql output", stage="psql")

    process_failure = None
    if timed_out:
        process_failure = "The psql process timed out"
    elif returncode in {-signal.SIGINT, -signal.SIGTERM, 128 + signal.SIGINT, 128 + signal.SIGTERM}:
        process_failure = "The psql process was canceled"
    elif returncode == 2:
        process_failure = "psql could not establish or keep its connection"
    elif returncode != 0:
        process_failure = f"Disposable psql exited with code {returncode}"

    if sqlstate is not None:
        if (
            "I" in markers
            and sqlstate in {"00000", "23505"}
            and provenance
            and provenance["collation"]
        ):
            result = {
                "index_status": "built" if sqlstate == "00000" else "unique_violation",
                "sqlstate": sqlstate,
                "provenance": provenance,
            }
            if process_failure:
                result["process_failure"] = process_failure
            return result
        reason = (
            "PostgreSQL canceled the statement (timeout or cancellation)"
            if sqlstate == "57014"
            else f"PostgreSQL returned an error at {stage}"
        )
        return incomplete(reason, stage=stage, sqlstate=sqlstate, provenance=provenance)
    if process_failure:
        return incomplete(
            process_failure,
            stage="connection" if returncode == 2 else "psql",
            provenance=provenance,
        )
    if returncode == 0 and facts is not None:
        if "C" not in markers:
            reason = "The server must be PostgreSQL 15 through 18 with a read-write UTF8 session"
        elif catalog is None:
            reason = "The requested collation does not exist for UTF8"
        elif provenance["collation"] is None:
            reason = "The requested collation provider is unsupported"
        else:
            return incomplete(
                "The index outcome marker is missing", stage="psql", provenance=provenance
            )
        return incomplete(reason, stage="preflight", provenance=provenance)
    return incomplete("The index outcome marker is missing", stage="psql", provenance=provenance)


def probe(container, entries, schema, name, timeout_ms, *, process_timeout_s=30):
    """Build one index and classify only a confirmed CREATE INDEX 23505 as a conflict."""
    data = index_script(entries, schema, name, timeout_ms)
    try:
        # A file retains flushed markers even when subprocess.run is interrupted.
        # PostgreSQL diagnostics may contain keys, so they are discarded.
        with tempfile.TemporaryFile() as stdout:
            try:
                done = subprocess.run(
                    ["docker", *psql_argv(container), "-f", "-"],
                    input=data,
                    stdout=stdout,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=process_timeout_s,
                )
            except KeyboardInterrupt:
                stdout.seek(0)
                result = parse_probe_output(stdout.read(), schema, name, returncode=-signal.SIGINT)
                raise ProbeInterrupted(result) from None
            except subprocess.TimeoutExpired:
                stdout.seek(0)
                return parse_probe_output(stdout.read(), schema, name, timed_out=True)
            stdout.seek(0)
            return parse_probe_output(stdout.read(), schema, name, returncode=done.returncode)
    except OSError:
        return incomplete("The disposable psql process could not start", stage="psql")
