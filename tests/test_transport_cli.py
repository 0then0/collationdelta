import json
import sys

import pytest

from collationdelta.cli import main
from collationdelta.evidence import capture
from collationdelta.formats import DeltaError, dump
from collationdelta.transport import run


def command(code):
    return [sys.executable, "-c", code]


@pytest.mark.parametrize(
    "code,match,limits",
    [
        ("import sys;sys.stderr.write('boom');sys.exit(7)", "exited 7", {}),
        ("import time;time.sleep(10)", "timeout", {"timeout": 0.1}),
        ("import sys;sys.stdout.write('x'*5000)", "stdout exceeds", {"stdout_limit": 100}),
        ("import sys;sys.stderr.write('x'*5000)", "stderr exceeds", {"stderr_limit": 100}),
        (
            "import sys,time;sys.stdin.close();sys.stdout.close();sys.stderr.close();time.sleep(10)",
            "timeout",
            {"timeout": 0.1},
        ),
    ],
)
def test_process_failures(code, match, limits):
    with pytest.raises(DeltaError, match=match):
        run(command(code), b"{}", **limits)


def test_missing_executable():
    with pytest.raises(DeltaError, match="launch failed"):
        run(["/nonexistent/collationdelta-adapter"], b"{}")


def test_no_stderr_deadlock_and_bidirectional_io():
    code = "import sys;sys.stderr.buffer.write(b'e'*200000);sys.stderr.flush();data=sys.stdin.buffer.read();sys.stdout.buffer.write(data)"
    out, err = run(command(code), b"s" * 300000)
    assert out == b"s" * 300000 and err == b"e" * 200000


def test_descendant_held_pipes_are_bounded():
    code = "import os,time;pid=os.fork();time.sleep(10) if pid==0 else None"
    with pytest.raises(DeltaError, match="timeout"):
        run(command(code), b"{}", timeout=0.2)


def test_argv_without_shell_interpolation(tmp_path):
    marker = tmp_path / "SHOULD_NOT_EXIST"
    literal = f"$(touch {marker})"
    out, _ = run([*command("import sys;sys.stdin.read();print(sys.argv[1])"), literal], b"{}")
    assert literal.encode() in out and not marker.exists()


@pytest.mark.parametrize("reply", ["not json", "{}", '{"protocol_version":1}', '"\\ud800"'])
def test_malformed_adapter_output(profile, reply):
    with pytest.raises(DeltaError):
        capture(
            {"version": 1, "entries": [{"id": "a", "value": "a"}]},
            profile,
            command("import sys;sys.stdin.read();sys.stdout.write(" + repr(reply) + ")"),
        )


@pytest.mark.parametrize(
    "limits", [{"timeout": 0}, {"timeout": float("nan")}, {"stdout_limit": -1}, {"stderr_limit": 0}]
)
def test_invalid_limits(limits):
    with pytest.raises(DeltaError):
        run(command("pass"), b"{}", **limits)


def test_cli_offline_without_executable(make_capture, tmp_path, capsys):
    old = make_capture()
    # Remove availability of the recorded adapter without changing observations.
    from collationdelta.formats import digest

    old["run"]["argv"] = ["/no/longer/installed/old/runtime"]
    old["digest"] = digest({k: v for k, v in old.items() if k != "digest"})
    baseline = tmp_path / "baseline.json"
    output = tmp_path / "report.json"
    dump(baseline, old)
    assert (
        main(
            [
                "compare",
                str(baseline),
                str(baseline),
                "--format",
                "json",
                "--json-output",
                str(output),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "STABLE" and json.loads(output.read_text()) == report


def test_cli_error_and_exit_codes(make_capture, tmp_path, capsys):
    old, changed, partial = tmp_path / "old.json", tmp_path / "new.json", tmp_path / "partial.json"
    dump(old, make_capture())
    dump(changed, make_capture(comparator=lambda a, b: (b > a) - (b < a)))
    dump(partial, make_capture(mutate=lambda r: r["results"].pop()))
    assert main(["compare", str(old), str(changed)]) == 1
    assert main(["compare", str(old), str(partial)]) == 2
    assert main(["compare", str(old), str(partial), "--limit", "-1"]) == 3
    assert main(["unknown"]) == 3
    assert main(["compare", "/absent", str(old)]) == 3
    assert "ERROR:" in capsys.readouterr().err


def test_capture_error_preserves_existing_destination(profile, tmp_path):
    corpus, requested, output = [
        tmp_path / name for name in ("corpus.json", "profile.json", "old.json")
    ]
    dump(corpus, {"version": 1, "entries": [{"id": "a", "value": "a"}]})
    dump(requested, profile)
    output.write_text("existing baseline")
    assert (
        main(
            [
                "capture",
                "--corpus",
                str(corpus),
                "--profile",
                str(requested),
                "--output",
                str(output),
                "--",
                *command("import sys;sys.exit(7)"),
            ]
        )
        == 3
    )
    assert output.read_text() == "existing baseline"
