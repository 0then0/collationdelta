"""Disposable PostgreSQL unique-index checks, including independent SQL witnesses."""

import importlib
import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

from collationdelta.formats import DeltaError, dump, load

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
EXAMPLES = ROOT / "examples/postgres"
NEEDS_STAND = pytest.mark.skipif(
    os.environ.get("COLLATIONDELTA_POSTGRES_STAND") != "1",
    reason="set COLLATIONDELTA_POSTGRES_STAND=1 (needs Docker and the pinned image)",
)


@pytest.fixture(scope="module")
def driver():
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.syspath_prepend(str(SCRIPTS))
        yield importlib.import_module("check_postgres_unique")


@pytest.fixture(scope="module")
def stand(driver):
    pins = load(SCRIPTS / "postgres-pins.json")
    reference = f"{pins['image']}@{pins['digest']}"
    driver.image_identity(reference)
    configurations = driver.default_configurations(pins)
    containers = {
        side: f"collationdelta-unique-test-{side}-{secrets.token_hex(6)}" for side in configurations
    }
    try:
        for side, container in containers.items():
            driver.start(container, reference)
            driver.configure(container, configurations[side], pins)
        yield containers, configurations
    finally:
        for container in containers.values():
            driver.docker("rm", "-fv", container, check=False)


@pytest.mark.parametrize(
    "values,error",
    [
        (["a\x00b"], "U+0000"),
        (["a"] * 257, "1..256"),
        (["a" * (1024 * 1024)], "1 MiB"),
    ],
)
def test_invalid_corpus_does_not_need_docker(tmp_path, values, error):
    invalid = tmp_path / "invalid.json"
    entries = [{"id": f"key-{i}", "value": value} for i, value in enumerate(values)]
    dump(invalid, {"version": 1, "entries": entries})
    output = tmp_path / "output.json"
    done = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "check_postgres_unique.py"),
            "--corpus",
            str(invalid),
            "--output",
            str(output),
        ],
        env={**os.environ, "PATH": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert done.returncode == 1 and error in done.stderr
    assert not output.exists()


def test_observation_failure_preserves_the_index_rejection(driver, monkeypatch):
    configurations = driver.default_configurations(load(SCRIPTS / "postgres-pins.json"))
    document = load(EXAMPLES / "unique-conflict.json")

    def probe(container, *_args, **_kwargs):
        index_status, sqlstate = {
            "source": ("built", "00000"),
            "target": ("unique_violation", "23505"),
        }[container]
        return {"index_status": index_status, "sqlstate": sqlstate, "provenance": None}

    def failed_comparison(*_args, **_kwargs):
        raise DeltaError("adapter timeout after 30s")

    monkeypatch.setattr(driver, "probe", probe)
    monkeypatch.setattr(driver, "run", failed_comparison)
    report = driver.check_indexes(
        {side: side for side in configurations}, document, configurations, 10_000
    )
    assert report["status"] == "new_conflict" and not report["complete"]
    target = report["sides"]["target"]
    assert target["index_status"] == "unique_violation" and target["sqlstate"] == "23505"
    assert target["witness"]["status"] == "unconfirmed"
    assert report["new_conflict_witness"]["status"] == "unconfirmed"


@NEEDS_STAND
def test_unique_index_conflict_and_direct_sql(driver, stand):
    from postgres_unique_index import psql_argv

    containers, configurations = stand
    document = load(EXAMPLES / "unique-conflict.json")
    report = driver.check_indexes(containers, document, configurations, 10_000)
    assert report["status"] == "new_conflict" and report["complete"]
    source, target = (report["sides"][side] for side in ("source", "target"))
    assert (source["index_status"], source["sqlstate"]) == ("built", "00000")
    assert (target["index_status"], target["sqlstate"]) == ("unique_violation", "23505")
    assert source["witness"] is None
    assert target["witness"] == {
        "status": "confirmed",
        "ids": ["lower-a", "upper-a"],
        "relation": 0,
    }
    assert report["new_conflict_witness"] == {
        "status": "confirmed",
        "ids": ["lower-a", "upper-a"],
        "source_relation": -1,
        "target_relation": 0,
    }
    assert source["provenance"] and target["provenance"]

    sql = (
        "SELECT (:'a'::pg_catalog.text COLLATE cd_stand.cd_equality) "
        "OPERATOR(pg_catalog.=) (:'b'::pg_catalog.text COLLATE cd_stand.cd_equality);\n"
    )
    a, b = (entry["value"] for entry in document["entries"])
    for side, expected in (("source", b"f"), ("target", b"t")):
        observed = driver.docker(
            *psql_argv(containers[side]),
            "-v",
            "ON_ERROR_STOP=1",
            "-v",
            f"a={a}",
            "-v",
            f"b={b}",
            "-f",
            "-",
            input=sql.encode("ascii"),
        ).stdout.strip()
        assert observed == expected


@NEEDS_STAND
@pytest.mark.parametrize(
    "case,status,build,sqlstate",
    [
        ("clean", "no_conflict", "built", "00000"),
        ("source-duplicate", "source_conflict", "unique_violation", "23505"),
    ],
)
def test_unique_index_controls(driver, stand, case, status, build, sqlstate):
    containers, configurations = stand
    document = load(EXAMPLES / f"unique-{case}.json")
    report = driver.check_indexes(containers, document, configurations, 10_000)
    assert report["status"] == status and report["complete"]
    assert report["new_conflict_witness"] is None
    for side in report["sides"].values():
        assert (side["index_status"], side["sqlstate"]) == (build, sqlstate)
        if case == "source-duplicate":
            assert side["witness"] == {
                "status": "confirmed",
                "ids": ["lower-a", "lower-a-copy"],
                "relation": 0,
            }


@NEEDS_STAND
def test_custom_collations_and_keys_are_quoted_separately(driver, stand):
    containers, defaults = stand
    pins = load(SCRIPTS / "postgres-pins.json")
    configurations = {
        side: {
            **defaults[side],
            "schema": 'schema"; --é',
            "name": f"{side}'\\;\n😀",
        }
        for side in containers
    }
    for side, container in containers.items():
        driver.configure(container, configurations[side], pins)

    suffix = "'); DROP TABLE cd_unique_keys; --\n\\"
    document = {
        "version": 1,
        "entries": [{"id": text, "value": text + suffix} for text in ("a", "A")],
    }
    report = driver.check_indexes(containers, document, configurations, 10_000)
    assert report["status"] == "new_conflict" and report["complete"]
    assert set(report["new_conflict_witness"]["ids"]) == {"A", "a"}


@NEEDS_STAND
def test_failed_connection_is_incomplete(driver, stand):
    containers, configurations = stand
    document = load(EXAMPLES / "unique-clean.json")
    unavailable = f"collationdelta-missing-{secrets.token_hex(8)}"
    report = driver.check_indexes(
        {**containers, "target": unavailable}, document, configurations, 10_000
    )
    assert report["status"] == "incomplete" and not report["complete"]
    source, target = (report["sides"][side] for side in ("source", "target"))
    assert (source["index_status"], source["sqlstate"]) == ("built", "00000")
    assert (target["index_status"], target["sqlstate"]) == ("incomplete", None)


@NEEDS_STAND
def test_postgresql_statement_timeout_is_incomplete(driver, stand):
    containers, configurations = stand
    document = load(EXAMPLES / "unique-clean.json")
    target = containers["target"]
    # Delay only the test's CREATE INDEX so the server cancels that exact statement.
    driver.stand_sql(
        target,
        "CREATE FUNCTION public.cd_wait_for_index() RETURNS event_trigger LANGUAGE plpgsql AS $$ "
        "BEGIN PERFORM pg_catalog.pg_sleep(2); END $$;\n"
        "CREATE EVENT TRIGGER cd_wait_for_index ON ddl_command_start WHEN TAG IN ('CREATE INDEX') "
        "EXECUTE FUNCTION public.cd_wait_for_index();\n",
    )
    try:
        report = driver.check_indexes(containers, document, configurations, 500)
    finally:
        driver.stand_sql(
            target,
            "DROP EVENT TRIGGER cd_wait_for_index; DROP FUNCTION public.cd_wait_for_index();\n",
        )
    assert report["status"] == "incomplete" and not report["complete"]
    source, target = (report["sides"][side] for side in ("source", "target"))
    assert (source["index_status"], source["sqlstate"]) == ("built", "00000")
    assert (target["index_status"], target["sqlstate"]) == ("incomplete", "57014")
    assert target["stage"] == "create_index" and target["provenance"]


@NEEDS_STAND
@pytest.mark.parametrize(
    "case,status,index_status,sqlstate",
    [
        ("clean", "no_conflict", "built", "00000"),
        ("conflict", "new_conflict", "unique_violation", "23505"),
    ],
)
def test_psql_deadline_after_index_result(
    driver, stand, monkeypatch, case, status, index_status, sqlstate
):
    containers, configurations = stand
    document = load(EXAMPLES / f"unique-{case}.json")
    run = subprocess.run

    def expire_target_process(argv, **kwargs):
        result = run(argv, **kwargs)
        if argv[:2] == ["docker", "exec"] and containers["target"] in argv:
            # The actual psql response has already been written to the probe's file.
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return result

    monkeypatch.setattr(subprocess, "run", expire_target_process)
    report = driver.check_indexes(containers, document, configurations, 10_000)
    target = report["sides"]["target"]
    assert (target["index_status"], target["sqlstate"]) == (index_status, sqlstate)
    assert "timed out" in target["process_failure"]
    assert report["status"] == status and not report["complete"]
    if case == "conflict":
        assert report["new_conflict_witness"]["status"] == "confirmed"


@NEEDS_STAND
def test_invalid_collation_setup_preserves_sqlstate(driver):
    pins = load(SCRIPTS / "postgres-pins.json")
    configurations = driver.default_configurations(pins)
    configurations["target"].update(
        provider="builtin", locale="collationdelta-nonexistent", deterministic=True
    )
    document = load(EXAMPLES / "unique-clean.json")
    report = driver.run_check(document, configurations, pins, 10_000)
    source, target = (report["sides"][side] for side in ("source", "target"))
    assert (source["index_status"], source["sqlstate"]) == ("built", "00000")
    assert (target["index_status"], target["sqlstate"]) == ("incomplete", "42809")
    assert target["stage"] == "collation_setup" and target["provenance"]["postgresql"]
    assert report["status"] == "incomplete" and not report["complete"]
