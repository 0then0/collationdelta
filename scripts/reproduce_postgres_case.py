#!/usr/bin/env python3
"""Reproduce the PostgreSQL configuration-control case with two disposable servers.

Two containers start from one pinned PostgreSQL image. Each defines collations with the
same schema-qualified names but different, recorded parameters. This is a configuration
control, not a PostgreSQL upgrade or a production incident. Containers publish no ports,
are removed on exit, and the image must already be present (nothing is pulled).

The psql client used for capture is the one inside each server container, reached through
scripts/psql-docker-exec.sh (set as COLLATIONDELTA_PSQL for the adapter).
"""

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

from collationdelta.evidence import capture, compare, human_report
from collationdelta.formats import DeltaError, dump, load, require

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "src/collationdelta/adapters/postgres.py"
SHIM = ROOT / "scripts/psql-docker-exec.sh"
SCENARIOS = {"order": "cd_order", "equality": "cd_equality"}


def docker(*args, input=None, check=True, timeout=120):
    done = subprocess.run(
        ["docker", *args], input=input, capture_output=True, timeout=timeout, check=False
    )
    if check and done.returncode != 0:
        detail = done.stderr.decode("utf-8", errors="replace").strip()
        raise DeltaError(f"docker {args[0]} failed ({done.returncode}): {detail}")
    return done


def image_identity(reference):
    done = docker("image", "inspect", reference, check=False)
    require(
        done.returncode == 0, f"image {reference} is not present locally; pull it explicitly first"
    )
    info = json.loads(done.stdout)[0]
    return {
        "reference": reference,
        "id": info["Id"],
        "repo_digests": info.get("RepoDigests", []),
        "os": info["Os"],
        "architecture": info["Architecture"],
        "created": info["Created"],
    }


def start(name, reference):
    docker("rm", "-f", name, check=False)
    # Name-only -e: the generated password is not placed in any argv.
    os.environ["POSTGRES_PASSWORD"] = secrets.token_hex(16)
    docker("run", "-d", "--name", name, "-e", "POSTGRES_PASSWORD", reference)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        logs = docker("logs", name, check=False)
        text = (logs.stdout + logs.stderr).decode("utf-8", errors="replace")
        # The entrypoint runs a temporary server first, then the final one.
        if text.count("database system is ready to accept connections") >= 2:
            if sql(name, "SELECT 1").strip() == "1":
                return
        time.sleep(0.5)
    raise DeltaError(f"{name} did not become ready")


def sql(container, statement, *variables):
    """Run SQL as the superuser; variables are passed as psql variables (data, not SQL)."""
    argv = ["exec", "-i", container, "psql", "-U", "postgres", "-X", "-At", "-v", "ON_ERROR_STOP=1"]
    for key, value in variables:
        argv += ["-v", f"{key}={value}"]
    return docker(*argv, "-f", "-", input=statement.encode("utf-8")).stdout.decode("utf-8")


def create_collations(container, pins, definitions):
    statements = [f"CREATE SCHEMA {pins['schema']};"]
    for name, spec in definitions.items():
        statements.append(
            f"CREATE COLLATION {pins['schema']}.{name} (provider = {spec['provider']}, "
            f"locale = '{spec['locale']}', deterministic = {str(spec['deterministic']).lower()});"
        )
    sql(container, "\n".join(statements))
    return statements


def catalog(container, pins):
    query = (
        "SELECT pg_catalog.json_agg(pg_catalog.json_build_object("
        "'name', c.collname, 'row', pg_catalog.to_jsonb(c) - 'oid' - 'collnamespace' - 'collowner', "
        "'actual_version', pg_catalog.pg_collation_actual_version(c.oid)) ORDER BY c.collname) "
        "FROM pg_catalog.pg_collation c WHERE c.collnamespace = "
        f"'{pins['schema']}'::pg_catalog.regnamespace;"
    )
    return json.loads(sql(container, query))


def direct_sign(container, pins, name, a, b):
    """Independent confirmation: server operators with psql-quoted variables, no adapter."""
    collate = f'COLLATE "{pins["schema"]}"."{name}"'
    query = (
        f"SELECT (:'a'::text {collate} < :'b'::text {collate})::int, "
        f"(:'a'::text {collate} = :'b'::text {collate})::int, "
        f"(:'a'::text {collate} > :'b'::text {collate})::int;"
    )
    flags = sql(container, query, ("a", a), ("b", b)).strip()
    return {"100": -1, "010": 0, "001": 1}[flags.replace("|", "")]


def run_capture(container, corpus, profile):
    environment = dict(os.environ)
    try:
        os.environ["CD_CONTAINER"] = container
        os.environ["PGUSER"] = "postgres"
        os.environ["COLLATIONDELTA_PSQL"] = str(SHIM)
        return capture(corpus, profile, [sys.executable, str(ADAPTER)])
    finally:
        os.environ.clear()
        os.environ.update(environment)


MATRIX_COLLATIONS = {
    "cd_icu": ("icu", "und-u-kf-upper", True, 15),
    "cd_libc": ("libc", "en_US.utf8", True, 15),
    "cd_builtin": ("builtin", "C.UTF-8", True, 17),
}


def version_matrix(output, pins):
    """Capture one small corpus per supported major and provider; record what was observed."""
    corpus = {
        "version": 1,
        "entries": [
            {"id": str(i), "value": value}
            for i, value in enumerate(["a", "A", "b", "\u00e9", "e\u0301", "it's", "x\ny", ""])
        ],
    }
    rows = []
    for major, digest in pins["matrix"].items():
        reference = f"{pins['image']}@{digest}"
        identity = image_identity(reference)
        container = f"collationdelta-pg-matrix-{major}-{secrets.token_hex(3)}"
        try:
            start(container, reference)
            statements = [f"CREATE SCHEMA {pins['schema']};"]
            for name, (provider, locale, deterministic, since) in MATRIX_COLLATIONS.items():
                if int(major) >= since:
                    statements.append(
                        f"CREATE COLLATION {pins['schema']}.{name} (provider = {provider}, "
                        f"locale = '{locale}', deterministic = {str(deterministic).lower()});"
                    )
            sql(container, "\n".join(statements))
            for name, (provider, _, _, since) in MATRIX_COLLATIONS.items():
                if int(major) < since:
                    continue
                profile = {
                    "version": 1,
                    "contract": "postgresql.text.v1",
                    "locale": "und",
                    "options": {"collation": {"schema": pins["schema"], "name": name}},
                }
                cap = run_capture(container, corpus, profile)
                observed = cap["observation"]
                server = observed["runtime"]["postgresql"]
                rows.append(
                    {
                        "major": int(major),
                        "image_id": identity["id"],
                        "server_version": server["server_version"],
                        "server_version_num": server["server_version_num"],
                        "provider": provider,
                        "complete": cap["coverage"]["complete"],
                        "effective_collation": observed["effective"]["collation"],
                        "collation_versions": server["collation"],
                        "unavailable": server["unavailable"],
                    }
                )
                require(cap["coverage"]["complete"], f"{major}/{name} incomplete")
        finally:
            docker("rm", "-f", container, check=False)
    dump(output / "version-matrix.json", {"matrix_version": 1, "rows": rows})
    for row in rows:
        print(row["major"], row["provider"], row["server_version"], row["collation_versions"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="evidence directory")
    parser.add_argument(
        "--matrix", action="store_true", help="only record a per-major, per-provider matrix"
    )
    args = parser.parse_args()
    if args.matrix:
        args.output.mkdir(parents=True, exist_ok=True)
        version_matrix(args.output, load(ROOT / "scripts/postgres-pins.json"))
        return 0
    args.output.mkdir(parents=True, exist_ok=True)
    pins = load(ROOT / "scripts/postgres-pins.json")
    reference = f"{pins['image']}@{pins['digest']}"
    identity = image_identity(reference)
    corpus = load(ROOT / "examples/postgres/corpus.json")
    containers = {
        label: f"collationdelta-pg-{label}-{secrets.token_hex(3)}" for label in ("old", "new")
    }
    experiment = {
        "experiment_version": 1,
        "scope": pins["scope"],
        "image": identity,
        "environments": {},
    }
    try:
        for label, container in containers.items():
            start(container, reference)
            definitions = pins["environments"][label]
            statements = create_collations(container, pins, definitions)
            facts = catalog(container, pins)
            experiment["environments"][label] = {
                "create_statements": statements,
                "pg_collation": facts,
                "server_version": sql(container, "SHOW server_version;").strip(),
            }
            require(
                int(sql(container, "SHOW server_version_num;"))
                == pins["expected"]["server_version_num"],
                "server version differs from the pinned expectation",
            )
            for scenario in SCENARIOS:
                profile = load(ROOT / f"examples/postgres/{scenario}.profile.json")
                first = run_capture(container, corpus, profile)
                second = run_capture(container, corpus, profile)
                require(first["coverage"]["complete"], f"{label}/{scenario} capture incomplete")
                require(
                    first["observation"]["effective"] == second["observation"]["effective"]
                    and first["observation"]["results"] == second["observation"]["results"],
                    f"{label}/{scenario} captures not repeatable",
                )
                dump(args.output / f"{label}.{scenario}.capture.json", first)
                dump(args.output / f"{label}.{scenario}-repeat.capture.json", second)
                control = compare(
                    load(args.output / f"{label}.{scenario}.capture.json"),
                    load(args.output / f"{label}.{scenario}-repeat.capture.json"),
                )
                require(control["status"] == "STABLE", f"{label}/{scenario} control not stable")
                dump(args.output / f"{label}.{scenario}-control.report.json", control)
        # Direct SQL confirmation of every finding, before the servers are removed.
        reports = {}
        for scenario, name in SCENARIOS.items():
            report = compare(
                load(args.output / f"old.{scenario}.capture.json"),
                load(args.output / f"new.{scenario}.capture.json"),
            )
            require(report["status"] == "DRIFT", f"{scenario}: expected DRIFT")
            confirmations = []
            for finding in report["findings"]:
                a, b = (record["value"] for record in finding["records"])
                observed = {
                    label: direct_sign(containers[label], pins, name, a, b)
                    for label in ("old", "new")
                }
                require(
                    observed == {"old": finding["old_relation"], "new": finding["new_relation"]},
                    f"direct SQL disagrees for {finding['id']}",
                )
                confirmations.append({"finding": finding["id"], "direct_sql": observed})
            reports[scenario] = report
            experiment[f"{scenario}_direct_sql"] = confirmations
    finally:
        for container in containers.values():
            docker("rm", "-f", container, check=False)
    # Containers are gone: only saved artifacts are used from here on.
    for scenario in SCENARIOS:
        report = compare(
            load(args.output / f"old.{scenario}.capture.json"),
            load(args.output / f"new.{scenario}.capture.json"),
        )
        require(report == reports[scenario], f"{scenario}: offline report changed")
        dump(args.output / f"{scenario}.report.json", report)
        (args.output / f"{scenario}.txt").write_text(human_report(report), encoding="utf-8")
        experiment[f"{scenario}_offline"] = {
            "status": report["status"],
            "finding_count": report["finding_count"],
            "kinds": sorted({f["kind"] for f in report["findings"]}),
        }
    dump(args.output / "experiment.json", experiment)
    for scenario in SCENARIOS:
        print(human_report(load(args.output / f"{scenario}.report.json"), 5), end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DeltaError, OSError, subprocess.SubprocessError) as exc:
        print(f"Experiment failed: {exc}", file=sys.stderr)
        raise SystemExit(3) from None
