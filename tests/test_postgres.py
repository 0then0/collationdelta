"""PostgreSQL adapter: protocol behavior with a scripted psql, then real servers on request.

The scripted client checks what the adapter sends and how it treats incomplete or hostile
replies. Server behavior is only claimed by the integration tests at the end, which need
Docker and an already present pinned image (``COLLATIONDELTA_POSTGRES_STAND=1``).
"""

import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import collationdelta
from collationdelta.cli import main
from collationdelta.evidence import capture, compare
from collationdelta.formats import DeltaError, dump, load

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = Path(collationdelta.__file__).parent / "adapters" / "postgres.py"
SECRET = "S3cr3t-sentinel-0451"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


adapter = load_module("cd_postgres_adapter", ADAPTER)


def requested(schema="app", name="text_order"):
    return {
        "version": 1,
        "contract": "postgresql.text.v1",
        "locale": "und",
        "options": {"collation": {"schema": schema, "name": name}},
    }


def document(values):
    return {
        "version": 1,
        "entries": [{"id": f"e{i}", "value": value} for i, value in enumerate(values)],
    }


def metadata(**changes):
    row = {
        "collname": "text_order",
        "collprovider": "i",
        "collisdeterministic": True,
        "collencoding": -1,
        "collcollate": None,
        "collctype": None,
        "colllocale": "und-u-kf-upper",
        "collicurules": None,
        "collversion": "153.128",
    }
    value = {
        "version": "PostgreSQL 18.6 (fake) on test",
        "server_version": "18.6 (fake)",
        "server_version_num": "180006",
        "server_encoding": "UTF8",
        "client_encoding": "UTF8",
        "read_only": "on",
        "collation": {"row": row, "actual_version": "153.128"},
    }
    value.update(changes)
    return value


def reply(meta, rows):
    """psql -A -t output: one metadata line, then rows of codes 1 (<), 2 (=), 4 (>)."""
    lines = ["M" + json.dumps(meta)] + [f"R{i}:{codes}" for i, codes in rows]
    return "\n".join(lines) + "\n"


def codes_for(values, key=lambda value: value):
    def code(a, b):
        return "1" if key(a) < key(b) else "2" if key(a) == key(b) else "4"

    return [(i, "".join(code(a, b) for b in values)) for i, a in enumerate(values)]


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """A scripted psql; returns a function that configures its next replies."""
    program = tmp_path / "fake-psql"
    program.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "config = json.load(open(os.environ['FAKE_PSQL_CONFIG']))\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    print(config.get('version', 'psql (PostgreSQL) 18.6 (fake)'))\n"
        "    sys.exit(0)\n"
        "data = sys.stdin.buffer.read()\n"
        "with open(config['log'], 'a') as log:\n"
        "    log.write(json.dumps({'argv': sys.argv[1:], 'stdin': data.decode('ascii'),\n"
        "        'env': {k: v for k, v in os.environ.items() if k.startswith('PG')}}) + '\\n')\n"
        "sys.stdout.write(config['stdout'])\n"
        "sys.stdout.flush()\n"
        "sys.stderr.write(config['stderr'])\n"
        "sys.exit(config['code'])\n",
        encoding="utf-8",
    )
    program.chmod(program.stat().st_mode | stat.S_IXUSR)
    log, config = tmp_path / "calls.jsonl", tmp_path / "fake.json"
    monkeypatch.setenv("COLLATIONDELTA_PSQL", str(program))
    monkeypatch.setenv("FAKE_PSQL_CONFIG", str(config))

    def configure(stdout="", stderr="", code=0):
        config.write_text(
            json.dumps({"stdout": stdout, "stderr": stderr, "code": code, "log": str(log)})
        )
        return lambda: (
            [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        )

    return configure


def run_capture(values, profile=None):
    return capture(document(values), profile or requested(), [sys.executable, str(ADAPTER)])


def test_script_sends_corpus_as_inert_data_in_a_read_only_transaction(fake):
    values = ["a", "A", "x'); DROP TABLE t; --", 'q"\\', "line\nbreak", "e\u0301", "é"]
    calls = fake(reply(metadata(), codes_for(values)))
    cap = run_capture(values)
    assert cap["coverage"]["complete"] and cap["observation"]["status"] == "ok"
    (call,) = calls()
    assert call["argv"] == ["-X", "-w", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-f", "-"]
    script = call["stdin"]
    assert script.isascii()
    for fragment in ("DROP TABLE", "line\nbreak", "é", "it's"):
        assert fragment not in script
    assert b"x'); DROP TABLE t; --".hex() in script
    assert script.startswith("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;")
    assert "SET LOCAL search_path = pg_catalog, pg_temp;" in script
    assert "SET LOCAL statement_timeout = 10000;" in script
    assert script.rstrip().endswith("ROLLBACK;")
    for operator in ("<", "=", ">"):
        assert f"OPERATOR(pg_catalog.{operator})" in script
    assert script.count("FETCH 1 FROM cd_cursor;") == len(values)
    statements = re.findall(r"\b[A-Z]+\b", script.upper())
    for word in ("CREATE", "INSERT", "UPDATE", "DELETE", "COPY", "ALTER", "DROP", "TEMPORARY"):
        assert word not in statements


def test_hostile_identifiers_and_values_never_appear_as_sql_text():
    schema, name = 'a"b;\n\\--', "x'); DROP TABLE users; --\u00e9\U0001f600"
    data = adapter.script(schema, name, ["it's", "a\x01b"], 1000).decode("ascii")
    assert "DROP" not in data and "users" not in data
    assert adapter.uident('"') == 'U&"\\+000022"'
    assert adapter.uident("\u00e9\n") == 'U&"\\+0000E9\\+00000A"'
    assert adapter.literal("a'b") == (
        "pg_catalog.convert_from(pg_catalog.decode('612762', 'hex'), 'UTF8')"
    )


def test_server_facts_are_recorded_with_stored_and_actual_versions_separate(fake):
    meta = metadata()
    meta["collation"]["row"]["collversion"] = "152.0"
    fake(reply(meta, codes_for(["a", "b"])))
    cap = run_capture(["a", "b"])
    observation = cap["observation"]
    collation = observation["effective"]["collation"]
    assert observation["effective"]["contract"] == "postgresql.text.v1"
    assert collation == {
        "schema": "app",
        "name": "text_order",
        "provider": "icu",
        "deterministic": True,
        "locale": "und-u-kf-upper",
        "icu_rules": None,
        "lc_collate": None,
        "lc_ctype": None,
    }
    server = observation["runtime"]["postgresql"]
    assert server["server_version_num"] == 180006 and server["server_encoding"] == "UTF8"
    assert server["collation"] == {"stored": "152.0", "actual": "153.128", "match": False}
    assert set(server["unavailable"]) == {
        "collation.icu_rules",
        "collation.lc_collate",
        "collation.lc_ctype",
    }
    assert observation["runtime"]["client"]["version"].startswith("psql (PostgreSQL)")
    # Only the client program and version are recorded; its ICU/libc are not server facts.
    assert set(observation["runtime"]["client"]) == {"program", "version"}


def test_unavailable_catalog_facts_are_explicit(fake):
    meta = metadata()
    row = meta["collation"]["row"]
    del row["collicurules"]
    row["collversion"] = None
    meta["collation"]["actual_version"] = None
    fake(reply(meta, codes_for(["a"])))
    server = run_capture(["a"])["observation"]["runtime"]["postgresql"]
    assert server["collation"] == {"stored": None, "actual": None, "match": None}
    assert "absent" in server["unavailable"]["collation.icu_rules"]
    assert "NULL" in server["unavailable"]["collation.stored_version"]
    assert "NULL" in server["unavailable"]["collation.actual_version"]


def test_metadata_difference_alone_is_not_drift(fake):
    values = ["a", "A", "b"]
    fake(reply(metadata(), codes_for(values)))
    old = run_capture(values)
    changed = metadata(server_version_num="170009", version="PostgreSQL 17.9 (other)")
    changed["collation"]["row"]["colllocale"] = "und-u-kf-lower"
    changed["collation"]["row"]["collversion"] = "999.1"
    fake(reply(changed, codes_for(values)))
    new = run_capture(values)
    assert old["observation"]["effective"] != new["observation"]["effective"]
    assert old["observation"]["runtime"] != new["observation"]["runtime"]
    report = compare(old, new)
    assert report["status"] == "STABLE" and report["finding_count"] == 0


def test_pair_evidence_is_the_finding(fake):
    values = ["a", "A"]
    fake(reply(metadata(), codes_for(values, key=lambda v: v.swapcase())))
    old = run_capture(values)
    fake(reply(metadata(), codes_for(values)))
    new = run_capture(values)
    report = compare(old, new)
    assert report["status"] == "DRIFT"
    assert [(f["kind"], f["old_relation"], f["new_relation"]) for f in report["findings"]] == [
        ("order_reversal", -1, 1)
    ]


def test_timeout_keeps_completed_rows_and_marks_the_rest(fake):
    values = ["a", "b", "c", "d"]
    stderr = "psql:<stdin>:9: ERROR:  canceling statement due to statement timeout\n"
    fake(reply(metadata(), codes_for(values)[:2]), stderr=stderr, code=3)
    cap = run_capture(values)
    observation = cap["observation"]
    assert observation["status"] == "unresolved"
    assert "stopped after 2 of 4 rows" in observation["reason"]
    assert "statement_timeout 10000 ms" in observation["reason"]
    assert "statement timeout" in observation["reason"]
    assert cap["coverage"]["completed_comparisons"] == 8 and not cap["coverage"]["complete"]
    missing = [r for r in observation["results"] if r["status"] == "error"]
    assert len(missing) == 8 and all("statement timeout" in r["reason"] for r in missing)


def test_unterminated_or_malformed_output_is_not_trusted(fake):
    values = ["a", "b", "c"]
    good = codes_for(values)
    text = reply(metadata(), good[:2]) + "R2:12"  # killed mid-line
    fake(text)
    cap = run_capture(values)
    assert cap["observation"]["status"] == "unresolved"
    assert cap["coverage"]["completed_comparisons"] == 6
    fake(reply(metadata(), [good[0], (1, "12"), good[2]]))
    cap = run_capture(values)
    assert cap["coverage"]["completed_comparisons"] == 6
    assert (
        "malformed"
        in next(r for r in cap["observation"]["results"] if r["status"] == "error")["reason"]
    )
    fake(reply(metadata(), [good[0], (1, "423"), good[2]]))
    cap = run_capture(values)
    assert (
        "inconsistent"
        in next(r for r in cap["observation"]["results"] if r["status"] == "error")["reason"]
    )


@pytest.mark.parametrize(
    "stdout",
    [
        "R0:2\n",
        reply(metadata(), [(0, "2"), (0, "2")]),
        reply(metadata(), [(9, "2")]),
        "unexpected\n",
        reply(metadata(), []) + "M{}\n",
        "M{bad\n",
    ],
)
def test_protocol_violations_are_errors(fake, stdout):
    fake(stdout)
    with pytest.raises(DeltaError, match="postgresql adapter error"):
        run_capture(["a"])


def test_unrepresentable_string_is_a_pair_failure(fake):
    values = ["a", "x\x00y", "b"]
    calls = fake(reply(metadata(), codes_for(["a", "b"])))
    cap = run_capture(values)
    assert cap["observation"]["status"] == "ok" and not cap["coverage"]["complete"]
    assert cap["coverage"]["completed_comparisons"] == 4
    errors = [r for r in cap["observation"]["results"] if r["status"] == "error"]
    assert len(errors) == 5 and all("U+0000" in r["reason"] for r in errors)
    assert b"x\x00y".hex() not in calls()[0]["stdin"]
    assert calls()[0]["stdin"].count("FETCH 1") == 2


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.update(contract="intl.collator.v1"),
        lambda p: p.update(locale="en"),
        lambda p: p["options"].update(sensitivity="base"),
        lambda p: p.update(options={}),
        lambda p: p["options"].update(collation="app.text_order"),
        lambda p: p["options"]["collation"].update(extra=1),
        lambda p: p["options"]["collation"].update(schema=""),
        lambda p: p["options"]["collation"].update(name="x" * 64),
        lambda p: p["options"]["collation"].update(name="é" * 32),
        lambda p: p["options"]["collation"].update(name="a\x00b"),
    ],
)
def test_unsupported_profiles_never_contact_the_server(fake, change):
    calls = fake(reply(metadata(), codes_for(["a"])))
    profile = requested()
    change(profile)
    cap = run_capture(["a"], profile)
    assert cap["observation"]["status"] == "unsupported" and not cap["coverage"]["complete"]
    assert cap["observation"]["results"] == [] and cap["observation"]["reason"]
    assert calls() == []


def test_collation_name_limit_is_utf8_bytes(fake):
    fake(reply(metadata(), codes_for(["a"])))
    assert run_capture(["a"], requested(name="é" * 31))["observation"]["status"] == "ok"


@pytest.mark.parametrize(
    "meta,text",
    [
        (metadata(collation=None), "does not exist"),
        (metadata(server_version_num="140012"), "outside supported 15..18"),
        (metadata(server_version_num="190000"), "outside supported 15..18"),
        (metadata(server_encoding="LATIN1"), "not UTF8"),
    ],
)
def test_server_refusals_keep_known_facts(fake, meta, text):
    fake(reply(meta, []))
    cap = run_capture(["a"])
    observation = cap["observation"]
    assert observation["status"] == "unsupported" and text in observation["reason"]
    assert observation["results"] == [] and not cap["coverage"]["complete"]
    assert observation["runtime"]["postgresql"]["server_version_num"] == int(
        meta["server_version_num"]
    )


def test_unknown_provider_is_refused(fake):
    meta = metadata()
    meta["collation"]["row"]["collprovider"] = "z"
    fake(reply(meta, []))
    assert "unknown collation provider" in run_capture(["a"])["observation"]["reason"]


@pytest.mark.parametrize("change", [{"read_only": "off"}, {"client_encoding": "LATIN1"}])
def test_session_must_be_read_only_utf8(fake, change):
    fake(reply(metadata(**change), []))
    with pytest.raises(DeltaError, match="refusing"):
        run_capture(["a"])


def test_connection_failure_is_an_error_without_secrets(fake, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("PGPASSWORD", SECRET)
    stderr = (
        f'psql: error: connection to server at "db" failed: FATAL: password {SECRET} '
        f'for user "u" postgres://u:{SECRET}@db/app?password={SECRET} sslpassword={SECRET}\n'
    )
    calls = fake("", stderr=stderr, code=2)
    with pytest.raises(DeltaError) as error:
        run_capture(["a"])
    assert "cannot connect to PostgreSQL" in str(error.value) and SECRET not in str(error.value)
    # Through the CLI: exit 3 and an existing baseline is left alone.
    corpus, profile, output = (tmp_path / n for n in ("corpus.json", "profile.json", "base.json"))
    dump(corpus, document(["a"]))
    dump(profile, requested())
    output.write_text("existing baseline")
    code = main(
        [
            *("capture", "--corpus", str(corpus), "--profile", str(profile)),
            *("--output", str(output), "--", sys.executable, str(ADAPTER)),
        ]
    )
    captured = capsys.readouterr()
    assert code == 3 and output.read_text() == "existing baseline"
    assert SECRET not in captured.out + captured.err
    assert all(SECRET not in json.dumps(call["argv"]) for call in calls())


def test_credentials_stay_in_the_environment_and_out_of_artifacts(fake, monkeypatch, tmp_path):
    monkeypatch.setenv("PGPASSWORD", SECRET)
    monkeypatch.setenv("PGPASSFILE", str(tmp_path / "passfile-with-secret"))
    (tmp_path / "passfile-with-secret").write_text(f"*:*:*:*:{SECRET}\n")
    calls = fake(reply(metadata(), codes_for(["a", "b"])))
    cap = run_capture(["a", "b"])
    dump(tmp_path / "capture.json", cap)
    assert SECRET not in (tmp_path / "capture.json").read_text()
    for call in calls():
        assert SECRET not in json.dumps(call["argv"]) and SECRET not in call["stdin"]
        assert call["env"]["PGPASSWORD"] == SECRET  # reaches psql only through its environment
        assert call["env"]["PGCLIENTENCODING"] == "UTF8"
        assert call["env"]["PGCONNECT_TIMEOUT"] == "10"
    assert "-w" in calls()[0]["argv"]  # never prompts


def test_script_failure_before_metadata_is_an_error(fake):
    fake("", stderr="psql:<stdin>:3: ERROR:  permission denied\n", code=3)
    with pytest.raises(DeltaError, match=r"no server metadata.*permission denied"):
        run_capture(["a"])


def test_missing_client_and_bad_timeout(monkeypatch, fake):
    fake(reply(metadata(), codes_for(["a"])))
    monkeypatch.setenv("COLLATIONDELTA_PSQL", "/nonexistent/psql")
    with pytest.raises(DeltaError, match="not found"):
        run_capture(["a"])
    monkeypatch.setenv("COLLATIONDELTA_PSQL", "definitely-not-psql-on-path")
    with pytest.raises(DeltaError, match="not found"):
        run_capture(["a"])
    for bad in ("0", "abc", "9999999"):
        monkeypatch.setenv("COLLATIONDELTA_PG_STATEMENT_TIMEOUT_MS", bad)
        with pytest.raises(DeltaError, match="STATEMENT_TIMEOUT"):
            run_capture(["a"])


def test_cli_prints_adapter_path_inside_the_package(capsys):
    assert main(["postgres-adapter"]) == 0
    assert Path(capsys.readouterr().out.strip()) == ADAPTER and ADAPTER.is_file()


def test_incomplete_capture_exits_two_and_compares_as_incomplete(fake, tmp_path, capsys):
    values = ["a", "b", "c"]
    fake(reply(metadata(), codes_for(values)[:1]), stderr="ERROR: statement timeout\n", code=3)
    corpus, profile = tmp_path / "corpus.json", tmp_path / "profile.json"
    dump(corpus, document(values))
    dump(profile, requested())
    partial, full = tmp_path / "partial.json", tmp_path / "full.json"
    base = ["capture", "--corpus", str(corpus), "--profile", str(profile), "--output"]
    tail = ["--", sys.executable, str(ADAPTER)]
    assert main([*base, str(partial), *tail]) == 2
    fake(reply(metadata(), codes_for(values)))
    assert main([*base, str(full), *tail]) == 0
    assert main(["compare", str(partial), str(full)]) == 2
    assert "INCOMPLETE" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Real servers. Opt in with COLLATIONDELTA_POSTGRES_STAND=1; needs Docker and the pinned
# image already present locally (tests never pull). A missing image fails, not skips.
# ---------------------------------------------------------------------------

STAND_ON = os.environ.get("COLLATIONDELTA_POSTGRES_STAND") == "1"
needs_stand = pytest.mark.skipif(
    not STAND_ON, reason="set COLLATIONDELTA_POSTGRES_STAND=1 (needs Docker and the pinned image)"
)
SHIM = ROOT / "scripts/psql-docker-exec.sh"
ODD_SCHEMA = "s\"q'\\;--\u00e9"
ODD_NAME = "n\"a'\\;\n--\U0001f600"


@pytest.fixture(scope="session")
def stand():
    if not STAND_ON:
        pytest.skip("stand not enabled")
    module = load_module("cd_stand", ROOT / "scripts/reproduce_postgres_case.py")
    pins = load(ROOT / "scripts/postgres-pins.json")
    reference = f"{pins['image']}@{pins['digest']}"
    module.image_identity(reference)
    names = {label: f"collationdelta-test-{label}-{os.getpid()}" for label in ("old", "new")}
    try:
        for label, container in names.items():
            module.start(container, reference)
            module.create_collations(container, pins, pins["environments"][label])
        module.sql(
            names["old"],
            f"CREATE SCHEMA IF NOT EXISTS {module_ident(ODD_SCHEMA)};\n"
            f"CREATE COLLATION {module_ident(ODD_SCHEMA)}.{module_ident(ODD_NAME)} "
            "(provider = icu, locale = 'und-u-kf-upper', deterministic = true);",
        )
        yield module, pins, names
    finally:
        for container in names.values():
            module.docker("rm", "-f", container, check=False)


def module_ident(value):
    return '"' + value.replace('"', '""') + '"'


@pytest.fixture
def server(stand, monkeypatch):
    module, pins, names = stand

    def select(label):
        monkeypatch.setenv("CD_CONTAINER", names[label])
        monkeypatch.setenv("PGUSER", "postgres")
        monkeypatch.setenv("COLLATIONDELTA_PSQL", str(SHIM))
        return names[label]

    return module, pins, select


def sign(module, pins, container, name, a, b):
    return module.direct_sign(container, pins, name, a, b)


@needs_stand
def test_real_servers_repeat_stable_and_prove_a_configuration_change(server):
    module, pins, select = server
    corpus = load(ROOT / "examples/postgres/corpus.json")
    profile = load(ROOT / "examples/postgres/order.profile.json")
    select("old")
    first, repeat = (capture(corpus, profile, [sys.executable, str(ADAPTER)]) for _ in range(2))
    assert first["coverage"]["complete"] and compare(first, repeat)["status"] == "STABLE"
    select("new")
    new = capture(corpus, profile, [sys.executable, str(ADAPTER)])
    report = compare(first, new)
    assert report["status"] == "DRIFT" and report["finding_count"] == 2
    assert {f["kind"] for f in report["findings"]} == {"order_reversal"}
    for finding in report["findings"]:
        a, b = (record["value"] for record in finding["records"])
        observed = {
            label: sign(module, pins, select(label), "cd_order", a, b) for label in ("old", "new")
        }
        assert observed == {"old": finding["old_relation"], "new": finding["new_relation"]}
    effective = (first["observation"]["effective"], new["observation"]["effective"])
    assert effective[0]["collation"]["locale"] != effective[1]["collation"]["locale"]
    assert first["observation"]["runtime"]["postgresql"]["server_version_num"] >= 150000


@needs_stand
def test_real_equality_signs_match_direct_sql_for_hostile_strings(server):
    module, pins, select = server
    values = [
        "a",
        "A",
        "it's",
        'q"\\',
        "x\ny",
        "a\\nb",
        "e\u0301",
        "\u00e9",
        "x'); DROP TABLE t; --",
    ]
    profile = load(ROOT / "examples/postgres/equality.profile.json")
    for label in ("old", "new"):
        container = select(label)
        cap = capture(document(values), profile, [sys.executable, str(ADAPTER)])
        assert cap["coverage"]["complete"]
        relations = {(r["left"], r["right"]): r["value"] for r in cap["observation"]["results"]}
        for i, a in enumerate(values):
            for j, b in enumerate(values):
                assert relations[f"e{i}", f"e{j}"] == sign(
                    module, pins, container, "cd_equality", a, b
                ), (label, a, b)
        before = module.sql(container, "SELECT count(*) FROM pg_class WHERE relnamespace > 16383")
        assert before.strip() == "0"  # no user tables were created in the database


@needs_stand
def test_real_server_accepts_hostile_schema_and_collation_names(server):
    _, _, select = server
    select("old")
    profile = requested(ODD_SCHEMA, ODD_NAME)
    values = ["a", "A", "b"]
    cap = capture(document(values), profile, [sys.executable, str(ADAPTER)])
    assert cap["coverage"]["complete"]
    collation = cap["observation"]["effective"]["collation"]
    assert (collation["schema"], collation["name"]) == (ODD_SCHEMA, ODD_NAME)
    assert collation["locale"] == "und-u-kf-upper"
    relations = {(r["left"], r["right"]): r["value"] for r in cap["observation"]["results"]}
    assert relations["e0", "e1"] == 1  # a > A with upper-first
    # A lookalike name that does not exist is a refusal, never a different collation.
    missing = capture(
        document(values), requested(ODD_SCHEMA, ODD_NAME + "x"), [sys.executable, str(ADAPTER)]
    )
    assert missing["observation"]["status"] == "unsupported"


@needs_stand
def test_real_server_missing_collation_and_unrepresentable_string(server, tmp_path):
    _, _, select = server
    select("new")
    missing = capture(
        document(["a"]), requested("cd_stand", "nope"), [sys.executable, str(ADAPTER)]
    )
    assert missing["observation"]["status"] == "unsupported"
    assert "does not exist" in missing["observation"]["reason"]
    assert missing["observation"]["runtime"]["postgresql"]["server_version_num"] >= 150000
    assert not missing["coverage"]["complete"]
    nul = capture(
        document(["a", "b\x00", "c"]),
        load(ROOT / "examples/postgres/order.profile.json"),
        [sys.executable, str(ADAPTER)],
    )
    assert nul["coverage"]["completed_comparisons"] == 4 and not nul["coverage"]["complete"]
    assert any("U+0000" in r["reason"] for r in nul["observation"]["results"] if "reason" in r)


@needs_stand
def test_real_server_connection_failure_timeout_and_truncated_output(server, monkeypatch, tmp_path):
    _, _, select = server
    container = select("new")
    profile = load(ROOT / "examples/postgres/order.profile.json")
    monkeypatch.setenv("PGHOST", "127.0.0.1")
    monkeypatch.setenv("PGPORT", "1")
    monkeypatch.setenv("PGPASSWORD", SECRET)
    with pytest.raises(DeltaError, match="cannot connect") as error:
        capture(document(["a"]), profile, [sys.executable, str(ADAPTER)])
    assert SECRET not in str(error.value)
    monkeypatch.delenv("PGHOST")
    monkeypatch.delenv("PGPORT")
    monkeypatch.delenv("PGPASSWORD")
    heavy = ["x0", "x1"] + ["a" * 500_000 + chr(98 + i) for i in range(14)]
    monkeypatch.setenv("COLLATIONDELTA_PG_STATEMENT_TIMEOUT_MS", "30")
    slow = capture(document(heavy), profile, [sys.executable, str(ADAPTER)])
    assert slow["observation"]["status"] == "unresolved" and not slow["coverage"]["complete"]
    assert "statement_timeout 30 ms" in slow["observation"]["reason"]
    monkeypatch.delenv("COLLATIONDELTA_PG_STATEMENT_TIMEOUT_MS")
    # A real server reply cut off after three lines by a downstream consumer.
    cut = tmp_path / "psql-cut"
    cut.write_text(f'#!/bin/sh\n"{SHIM}" "$@" | head -n 3\n')
    cut.chmod(0o755)
    monkeypatch.setenv("COLLATIONDELTA_PSQL", str(cut))
    monkeypatch.setenv("CD_CONTAINER", container)
    values = ["a", "b", "c", "d", "e"]
    truncated = capture(document(values), profile, [sys.executable, str(ADAPTER)])
    assert truncated["observation"]["status"] == "unresolved"
    assert 0 < truncated["coverage"]["completed_comparisons"] < 25
    assert compare(truncated, truncated)["status"] == "INCOMPLETE"


@needs_stand
def test_real_password_authentication_keeps_the_secret_out_of_every_output(
    server, monkeypatch, tmp_path
):
    module, _, select = server
    container = select("new")
    password = "pw-" + SECRET
    module.sql(
        container,
        f"CREATE ROLE cd_probe LOGIN PASSWORD '{password}';"
        "GRANT USAGE ON SCHEMA cd_stand TO cd_probe;",
    )
    address = (
        module.docker(
            "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container
        )
        .stdout.decode()
        .strip()
    )
    log = tmp_path / "shim.log"
    monkeypatch.setenv("CD_SHIM_LOG", str(log))
    monkeypatch.setenv("PGHOST", address)  # non-loopback inside the container: scram required
    monkeypatch.setenv("PGUSER", "cd_probe")
    monkeypatch.setenv("PGDATABASE", "postgres")
    profile = load(ROOT / "examples/postgres/order.profile.json")
    monkeypatch.setenv("PGPASSWORD", "wrong-" + SECRET)
    with pytest.raises(DeltaError, match="authentication failed") as error:
        capture(document(["a"]), profile, [sys.executable, str(ADAPTER)])
    assert SECRET not in str(error.value)
    monkeypatch.setenv("PGPASSWORD", password)
    cap = capture(document(["a", "b"]), profile, [sys.executable, str(ADAPTER)])
    dump(tmp_path / "capture.json", cap)
    assert cap["coverage"]["complete"]
    assert SECRET not in (tmp_path / "capture.json").read_text() + log.read_text()


# ---------------------------------------------------------------------------
# Saved evidence is reanalyzed completely offline: no Docker, no PostgreSQL, no psql.
# ---------------------------------------------------------------------------

EVIDENCE = ROOT / "evidence/postgres-collation"


def test_saved_postgres_case_offline_without_servers_or_client(monkeypatch):
    monkeypatch.setenv("PATH", "")
    experiment = load(EVIDENCE / "experiment.json")
    assert experiment["image"]["repo_digests"]
    for scenario, kind, count in (
        ("order", "order_reversal", 2),
        ("equality", "equality_merge", 9),
    ):
        old, new = (load(EVIDENCE / f"{side}.{scenario}.capture.json") for side in ("old", "new"))
        report = compare(old, new)
        assert report == load(EVIDENCE / f"{scenario}.report.json")
        assert report["status"] == "DRIFT" and report["finding_count"] == count
        assert {f["kind"] for f in report["findings"]} == {kind}
        assert len(experiment[f"{scenario}_direct_sql"]) == count
        for side in ("old", "new"):
            first = load(EVIDENCE / f"{side}.{scenario}.capture.json")
            again = load(EVIDENCE / f"{side}.{scenario}-repeat.capture.json")
            assert first["coverage"]["completed_comparisons"] == 25 * 25
            assert first["observation"]["results"] == again["observation"]["results"]
            assert compare(first, again)["status"] == "STABLE"
            versions = first["observation"]["runtime"]["postgresql"]
            assert versions["server_version_num"] == 180006 and versions["collation"]["match"]
    cli = [sys.executable, "-m", "collationdelta"]
    done = subprocess.run(
        [
            *cli,
            "compare",
            str(EVIDENCE / "old.order.capture.json"),
            str(EVIDENCE / "new.order.capture.json"),
        ],
        capture_output=True,
        env={"PATH": "", "PYTHONPATH": str(ROOT / "src")},
        check=False,
    )
    assert done.returncode == 1 and b"order_reversal" in done.stdout
