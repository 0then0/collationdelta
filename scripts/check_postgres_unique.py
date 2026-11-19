#!/usr/bin/env python3
"""Check a user corpus with a unique text B-tree index on two disposable PostgreSQL servers."""

import argparse
import itertools
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

from postgres_unique_index import ProbeInterrupted, checked, parse_probe_output, probe, psql_argv
from reproduce_postgres_case import ADAPTER, SHIM, docker, image_identity

from collationdelta.adapters import postgres
from collationdelta.formats import (
    DeltaError,
    canonical,
    corpus,
    decode,
    digest,
    dump,
    fields,
    load,
    require,
)
from collationdelta.observations import response
from collationdelta.transport import run

PINS = Path(__file__).with_name("postgres-pins.json")
SIDES = ("source", "target")
STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM)
MAX_CORPUS_BYTES = 1024 * 1024
MAX_TOTAL_ID_BYTES = 16 * 1024
MAX_STATEMENT_TIMEOUT_MS = 60_000


def load_corpus(path):
    document = corpus(load(path))
    require(len(canonical(document)) <= MAX_CORPUS_BYTES, "canonical corpus exceeds 1 MiB")
    entries = document["entries"]
    # The pairwise adapter repeats IDs for every comparison in its bounded response.
    require(
        sum(len(canonical(entry["id"])) for entry in entries) <= MAX_TOTAL_ID_BYTES,
        "combined JSON-encoded IDs exceed 16 KiB",
    )
    require(
        all("\x00" not in entry["value"] for entry in entries),
        "PostgreSQL text cannot contain U+0000",
    )
    return document


def default_configurations(pins):
    name = "cd_equality"
    return {
        side: {"schema": pins["schema"], "name": name, **pins["environments"][label][name]}
        for side, label in zip(SIDES, ("old", "new"), strict=True)
    }


def validate_configurations(configurations):
    fields(configurations, SIDES)
    for config in configurations.values():
        fields(config, ("schema", "name", "provider", "locale", "deterministic"))
        for key in ("schema", "name"):
            require(postgres.valid_name(config[key]), f"invalid collation {key}")
        require(config["provider"] in ("icu", "libc", "builtin"), "unsupported collation provider")
        locale = config["locale"]
        require(
            isinstance(locale, str)
            and locale
            and "\x00" not in locale
            and len(locale.encode()) <= 255,
            "locale must be nonempty, NUL-free and at most 255 UTF-8 bytes",
        )
        require(type(config["deterministic"]) is bool, "deterministic must be a boolean")
    return configurations


def start(container, reference):
    environment = dict(os.environ, POSTGRES_PASSWORD=secrets.token_hex(16))
    # Wait for the bounded Docker call to finish before acting on a cancellation.
    # This lets cleanup find the container by name even if the signal arrived during creation.
    mask = signal.pthread_sigmask(signal.SIG_BLOCK, STOP_SIGNALS)
    try:
        docker(
            "run",
            "-d",
            "--pull",
            "never",
            "--network",
            "none",
            "--tmpfs",
            "/var/lib/postgresql:rw",
            "--name",
            container,
            "-e",
            "POSTGRES_PASSWORD",
            reference,
            timeout=30,
            env=environment,
        )
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, mask)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        # The image's bootstrap server only listens on the Unix socket.
        ready = docker(
            "exec",
            container,
            "pg_isready",
            "-h",
            "127.0.0.1",
            "-q",
            check=False,
            timeout=5,
        )
        if ready.returncode == 0:
            return
        time.sleep(0.25)
    raise DeltaError("disposable PostgreSQL server did not become ready")


def stand_sql(container, statement):
    return docker(
        *psql_argv(container),
        "-v",
        "ON_ERROR_STOP=1",
        "-f",
        "-",
        input=statement.encode("utf-8"),
        timeout=15,
    ).stdout.decode("utf-8")


def configure(container, configuration, pins, *, result=None):
    server = stand_sql(container, "SHOW server_version_num; SHOW server_encoding;").splitlines()
    if result is not None and len(server) == 2 and server[0].isdigit():
        result["provenance"] = {
            "postgresql": {"server_version_num": int(server[0]), "server_encoding": server[1]},
            "collation": None,
        }
    expected = pins["expected"]
    require(
        server == [str(expected["server_version_num"]), expected["server_encoding"]],
        "server version or encoding differs from the pinned expectation",
    )
    schema, name = (postgres.uident(configuration[key]) for key in ("schema", "name"))
    locale = postgres.literal(configuration["locale"])
    provider = configuration["provider"]
    deterministic = str(configuration["deterministic"]).lower()
    # psql quotes the decoded locale as a SQL string literal; names use identifier quoting.
    statements = (
        "BEGIN;",
        "SET LOCAL search_path = pg_catalog, pg_temp;",
        "SET LOCAL statement_timeout = 10000;",
        rf"SELECT {locale} AS locale \gset",
        f"CREATE SCHEMA {schema};",
        f"CREATE COLLATION {schema}.{name} "
        f"(provider = {provider}, locale = :'locale', deterministic = {deterministic});",
        "COMMIT;",
    )
    script = ["\\set ON_ERROR_STOP off", "\\set VERBOSITY sqlstate"]
    for statement in statements:
        script.extend(checked(statement, "collation_setup"))
    script.extend(("\\echo OK", ""))
    output = stand_sql(container, "\n".join(script))
    if output != "OK\n":
        failure = parse_probe_output(output.encode("utf-8"), schema, name)
        if result is not None:
            result.update(sqlstate=failure["sqlstate"], stage="collation_setup")
        raise DeltaError(failure["reason"])


def observe_pairs(container, document, configuration, timeout_ms, provenance):
    collation = {key: configuration[key] for key in ("schema", "name")}
    profile = {
        "version": 1,
        "contract": postgres.CONTRACT,
        "locale": "und",
        "options": {"collation": collation},
    }
    # Set every forwarded connection variable explicitly. No user libpq configuration
    # or optional shim log is consulted on this disposable path.
    argv = [
        "env",
        "-u",
        "CD_SHIM_LOG",
        f"CD_CONTAINER={container}",
        "PGHOST=/var/run/postgresql",
        "PGPORT=5432",
        "PGUSER=postgres",
        "PGDATABASE=postgres",
        "PGPASSWORD=",
        "PGSSLMODE=disable",
        "PGOPTIONS=",
        "PGCONNECT_TIMEOUT=5",
        f"COLLATIONDELTA_PSQL={SHIM}",
        f"COLLATIONDELTA_PG_STATEMENT_TIMEOUT_MS={timeout_ms}",
        sys.executable,
        str(ADAPTER),
    ]
    try:
        request = canonical({"protocol_version": 1, "corpus": document, "profile": profile})
        stdout, _ = run(argv, request, timeout=process_timeout(timeout_ms))
        observed, coverage, relations = response(
            decode(stdout, exact_results=True), document["entries"]
        )
        require(
            provenance is not None
            and observed["effective"] is not None
            and observed["effective"]["collation"] == provenance["collation"]
            and observed["runtime"]["postgresql"] == provenance["postgresql"],
            "comparison provenance differs from the index probe",
        )
    except DeltaError:
        return {
            "complete": False,
            "reason": "read-only pair observation failed or was unavailable",
        }, {}
    summary = dict(coverage)
    if not summary["complete"]:
        summary["reason"] = "read-only pair observation was incomplete"
    return summary, relations


def process_timeout(timeout_ms):
    return max(30, timeout_ms / 1000 + 10)


def initial_sides(configurations):
    return {
        side: {
            "configuration": configurations[side],
            "index_status": "incomplete",
            "sqlstate": None,
            "provenance": None,
            "comparison": None,
            "witness": None,
            "reason": "index probe did not run",
        }
        for side in SIDES
    }


def equal_pairs(document, relations):
    ids = sorted(entry["id"] for entry in document["entries"])
    return [
        (left, right)
        for left, right in itertools.combinations(ids, 2)
        if relations.get((left, right), relations.get((right, left))) == 0
    ]


def check_indexes(containers, document, configurations, timeout_ms, *, sides=None):
    if sides is None:
        sides = initial_sides(configurations)
    for side, container in containers.items():
        config = configurations[side]
        result = sides[side]
        result.pop("reason", None)
        known_provenance = result["provenance"]
        try:
            result.update(
                probe(
                    container,
                    document["entries"],
                    config["schema"],
                    config["name"],
                    timeout_ms,
                    process_timeout_s=process_timeout(timeout_ms),
                )
            )
        except ProbeInterrupted as exc:
            result.update(exc.result)
            raise
        except KeyboardInterrupt:
            result["reason"] = "index probe interrupted"
            raise
        finally:
            if result["provenance"] is None:
                result["provenance"] = known_provenance

    source = sides["source"]["index_status"]
    target = sides["target"]["index_status"]
    new_conflict = source == "built" and target == "unique_violation"
    relations = {}
    for side in reversed(SIDES):
        result = sides[side]
        violation = result["index_status"] == "unique_violation"
        if not (violation or (side == "source" and new_conflict)):
            continue
        if violation:
            result["witness"] = {"status": "unconfirmed", "reason": "no equal pair confirmed"}
        result["comparison"], relations[side] = observe_pairs(
            containers[side],
            document,
            configurations[side],
            timeout_ms,
            result["provenance"],
        )
        if violation:
            pairs = equal_pairs(document, relations[side])
            if pairs:
                result["witness"] = {"status": "confirmed", "ids": list(pairs[0]), "relation": 0}

    explanation = None
    if new_conflict:
        explanation = {
            "status": "unconfirmed",
            "reason": "no target-equal pair confirmed unequal on source",
        }
        for left, right in equal_pairs(document, relations["target"]):
            before = relations["source"].get((left, right))
            if before is None and (right, left) in relations["source"]:
                before = -relations["source"][right, left]
            if before in (-1, 1):
                ids = [left, right]
                sides["target"]["witness"] = {"status": "confirmed", "ids": ids, "relation": 0}
                explanation = {
                    "status": "confirmed",
                    "ids": ids,
                    "source_relation": before,
                    "target_relation": 0,
                }
                break
    return summarize(sides, explanation)


def summarize(sides, explanation=None):
    source, target = (sides[side]["index_status"] for side in SIDES)
    if "incomplete" in (source, target):
        status = "incomplete"
    elif source == "unique_violation":
        status = "source_conflict"
    elif target == "unique_violation":
        status = "new_conflict"
        if explanation is None:
            explanation = {"status": "unconfirmed", "reason": "source comparison did not finish"}
    else:
        status = "no_conflict"
    for side in sides.values():
        if side["index_status"] == "unique_violation" and side["witness"] is None:
            side["witness"] = {"status": "unconfirmed", "reason": "comparison did not run"}
    complete = (
        status != "incomplete"
        and (explanation is None or explanation["status"] == "confirmed")
        and all(
            "process_failure" not in side
            and (
                side["index_status"] != "unique_violation"
                or (side["witness"] or {}).get("status") == "confirmed"
            )
            and (side["comparison"] is None or side["comparison"]["complete"])
            for side in sides.values()
        )
    )
    return {
        "status": status,
        "complete": complete,
        "sides": sides,
        "new_conflict_witness": explanation,
    }


def cleanup(containers):
    # Allow cleanup to finish even if a second SIGINT or SIGTERM arrives.
    previous = [signal.signal(signum, signal.SIG_IGN) for signum in STOP_SIGNALS]
    failures = []
    try:
        for container in containers:
            try:
                result = docker("rm", "-fv", container, check=False, timeout=20)
                if result.returncode and b"No such container" not in result.stderr:
                    failures.append(container)
            except (OSError, subprocess.TimeoutExpired):
                failures.append(container)
    finally:
        for signum, handler in zip(STOP_SIGNALS, previous, strict=True):
            signal.signal(signum, handler)
    return failures


def run_check(document, configurations, pins, timeout_ms):
    sides = initial_sides(configurations)
    containers = {}
    attempted = []
    report = {
        "report_version": 1,
        "corpus_digest": digest(document),
        "entry_count": len(document["entries"]),
        "index": {"method": "btree", "unique": True, "column_type": "text", "not_null": True},
        "image": None,
        "statement_timeout_ms": timeout_ms,
        "process_timeout_seconds": process_timeout(timeout_ms),
    }
    reference = f"{pins['image']}@{pins['digest']}"
    try:
        report["image"] = image_identity(reference)
        for side in SIDES:
            container = f"collationdelta-unique-{side}-{secrets.token_hex(12)}"
            attempted.append(container)
            try:
                start(container, reference)
                configure(container, configurations[side], pins, result=sides[side])
            except (DeltaError, OSError, subprocess.TimeoutExpired) as exc:
                sides[side]["reason"] = f"stand setup failed: {exc}"
            else:
                containers[side] = container
        report.update(check_indexes(containers, document, configurations, timeout_ms, sides=sides))
    except KeyboardInterrupt:
        report.update(summarize(sides), complete=False, interrupted=True)
    except (DeltaError, OSError, subprocess.TimeoutExpired) as exc:
        report.update(summarize(sides), complete=False, reason=f"stand failed: {exc}")
    finally:
        failures = cleanup(attempted)
        if failures:
            report.update(complete=False, cleanup_failed=failures)
    witness_ids = {
        entry_id for side in sides.values() for entry_id in (side["witness"] or {}).get("ids", ())
    }
    report["witness_entries"] = [
        entry for entry in document["entries"] if entry["id"] in witness_ids
    ]
    return report


def interrupt(signum, frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--configuration", type=Path, help="JSON collation definitions for source and target"
    )
    parser.add_argument("--statement-timeout-ms", type=int, default=postgres.DEFAULT_TIMEOUT_MS)
    args = parser.parse_args()
    try:
        require(
            1 <= args.statement_timeout_ms <= MAX_STATEMENT_TIMEOUT_MS,
            "statement timeout must be 1..60000 ms",
        )
        document = load_corpus(args.corpus)
        pins = load(PINS)
        configurations = validate_configurations(
            load(args.configuration) if args.configuration else default_configurations(pins)
        )
        handler = signal.signal(signal.SIGTERM, interrupt)
        try:
            report = run_check(document, configurations, pins, args.statement_timeout_ms)
        finally:
            signal.signal(signal.SIGTERM, handler)
        dump(args.output, report)
    except (DeltaError, OSError) as exc:
        print(f"PostgreSQL unique index check: {exc}", file=sys.stderr)
        return 1
    print(f"{report['status']} (complete={str(report['complete']).lower()})")
    if report.get("interrupted"):
        return 130
    return 0 if report["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
