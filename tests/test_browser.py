"""Real browser integration is opt-in; unit tests never install a browser."""

import copy
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from collationdelta.cli import main
from collationdelta.evidence import capture, compare, validate_capture
from collationdelta.formats import DeltaError, canonical, digest, dump
from collationdelta.observations import response
from collationdelta.transport import run

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "src/collationdelta/adapters/browser.mjs"
NODE_ADAPTER = ADAPTER.with_name("node.mjs")
NODE = shutil.which("node")
TOOLCHAIN = os.environ.get("COLLATIONDELTA_BROWSER_TOOLCHAIN")
EXECUTABLE = os.environ.get("COLLATIONDELTA_BROWSER_EXECUTABLE")


def document(values):
    return {
        "version": 1,
        "entries": [{"id": str(i), "value": v} for i, v in enumerate(values)],
    }


def requested(locale="en", options=None, contract="intl.collator.v1"):
    return {"version": 1, "contract": contract, "locale": locale, "options": options or {}}


@pytest.fixture(scope="module")
def browser_command():
    if not NODE or not TOOLCHAIN or not EXECUTABLE:
        pytest.skip(
            "real Chromium integration requires Node, COLLATIONDELTA_BROWSER_TOOLCHAIN "
            "and COLLATIONDELTA_BROWSER_EXECUTABLE (explicit installation; no downloads)"
        )
    # Explicit bad configuration is an error, not a skip.
    assert Path(EXECUTABLE).is_file(), "configured browser executable does not exist"
    assert (Path(TOOLCHAIN) / "node_modules/playwright-core/package.json").is_file()
    return [NODE, str(ADAPTER), "--toolchain", TOOLCHAIN, "--executable", EXECUTABLE]


@pytest.fixture(scope="module")
def browser_capture(browser_command):
    values = [
        "",
        "\x00",
        "e\u0301",
        "é",
        "😀",
        "A",
        "a",
        "A",
        "x\ny",
        "');throw Error('injection');//",
    ]
    return capture(document(values), requested(options={"sensitivity": "base"}), browser_command)


def test_real_browser_complete_metadata_and_repeat(browser_capture, browser_command):
    cap = browser_capture
    assert cap["coverage"]["complete"]
    assert cap["coverage"]["completed_comparisons"] == 100
    validate_capture(cap)
    observation = cap["observation"]
    runtime = observation["runtime"]
    assert runtime["browser"]["execution_context"] == {
        "url": "about:blank",
        "has_document": True,
        "has_process": False,
    }
    assert runtime["browser"]["engine"] == "chromium"
    assert runtime["browser"]["version"]
    assert runtime["browser"]["user_agent"]
    assert runtime["automation"]["name"] == "playwright-core"
    assert runtime["automation"]["version"]
    assert runtime["host"]["platform"] == sys.platform
    assert runtime["host"]["arch"]
    assert runtime["selection"]["executable"] == str(Path(EXECUTABLE).resolve())
    assert runtime["selection"]["caller_labels"] == {}
    assert runtime["intl"]["supported_locales"] == ["en"]
    assert runtime["intl"]["resolved_options"] == observation["effective"]
    assert not {"icu", "cldr", "unicode"} & runtime["browser"].keys()
    relations = {(r["left"], r["right"]): r["value"] for r in observation["results"]}
    assert relations["2", "3"] == relations["5", "6"] == relations["5", "7"] == 0
    repeat = capture(cap["corpus"], cap["requested"], browser_command)
    assert cap["observation"] == repeat["observation"]
    assert compare(cap, repeat)["status"] == "STABLE"


@pytest.mark.parametrize(
    "locale,options,supported",
    [
        ("zz-ZZ", {}, False),
        ("en", {"collation": "foobar"}, False),
        ("en-u-co-foobar", {}, False),
        ("en-u-kn-foobar", {}, False),
        ("en-u-kf-foobar", {}, False),
        ("en", {"numeric": "true"}, False),
        ("en", {"unknown": True}, False),
        ("en", {"toString": "x"}, False),
        ("en", {"localeMatcher": "best fit"}, False),
        ("EN-us", {}, True),
        ("en-XX", {}, True),
        ("en-u-kn-true-v-foo", {}, True),
        ("en-x-u-kn-true", {}, True),
        ("en-u-kf-upper-x-u-kn-true", {}, True),
        ("en-u-kn-true-kf-upper", {"numeric": False, "caseFirst": "lower"}, True),
        ("de-u-co-phonebk", {}, True),
        (
            "de",
            {
                "sensitivity": "variant",
                "numeric": True,
                "caseFirst": "upper",
                "ignorePunctuation": True,
                "usage": "sort",
                "collation": "phonebk",
            },
            True,
        ),
        ("en", {"usage": "search"}, True),
    ],
)
def test_strict_contract_parity(browser_command, locale, options, supported):
    corpus, profile = document(["2", "10", "A", "a"]), requested(locale, options)
    node = capture(corpus, profile, [NODE, str(NODE_ADAPTER)])
    browser = capture(corpus, profile, browser_command)
    assert node["coverage"]["complete"] is supported
    assert browser["coverage"]["complete"] is supported
    assert node["observation"]["status"] == browser["observation"]["status"]
    if not supported:
        assert browser["observation"]["reason"]
        assert browser["observation"]["results"] == []
        assert compare(node, browser)["status"] == "INCOMPLETE"


def test_locale_support_is_observed_not_assumed(browser_command):
    corpus, profile = document(["Örn", "Þórður", "Ævar"]), requested("is")
    browser = capture(corpus, profile, browser_command)
    node = capture(corpus, profile, [NODE, str(NODE_ADAPTER)])
    observation = browser["observation"]
    if observation["runtime"]["intl"]["supported_locales"]:
        assert browser["coverage"]["complete"]
    else:
        assert observation["status"] == "unsupported"
        assert observation["effective"]["locale"]
        assert observation["results"] == []
        report = compare(node, browser)
        assert report["status"] == "INCOMPLETE" and report["finding_count"] == 0
        assert report["sides"]["new"]["effective"] == observation["effective"]
        assert report["sides"]["new"]["reason"] == observation["reason"]


def test_host_intl_is_not_the_comparator(browser_command, tmp_path):
    poison = tmp_path / "poison.mjs"
    poison.write_text("Intl.Collator = function() { throw Error('HOST COMPARATOR USED'); };\n")
    command = [
        NODE,
        "--import",
        str(poison),
        *browser_command[1:],
        "--distribution-label",
        "caller test",
    ]
    cap = capture(document(["A", "a"]), requested(options={"sensitivity": "base"}), command)
    assert cap["coverage"]["complete"]
    assert cap["observation"]["runtime"]["selection"]["caller_labels"] == {
        "distribution": "caller test"
    }


def test_protocol_stdout_and_browser_atomic_failure(browser_command, tmp_path):
    corpus, profile = document(["a", "b"]), requested()
    out, _ = run(
        browser_command, canonical({"protocol_version": 1, "corpus": corpus, "profile": profile})
    )
    assert json.loads(out)["status"] == "ok"  # One document, no logs or banner.
    corpus_path, profile_path, destination = [
        tmp_path / n for n in ("corpus.json", "profile.json", "cap.json")
    ]
    dump(corpus_path, corpus)
    dump(profile_path, profile)
    destination.write_text("existing capture")
    for command, limits in [
        ([*browser_command, "--executable", str(tmp_path / "absent")], []),
        (browser_command, ["--stdout-limit", "10"]),
        (browser_command, ["--timeout", "0.1"]),
        ([*browser_command, "--deadline-ms", "1"], []),
    ]:
        assert (
            main(
                [
                    "capture",
                    "--corpus",
                    str(corpus_path),
                    "--profile",
                    str(profile_path),
                    "--output",
                    str(destination),
                    *limits,
                    "--",
                    *command,
                ]
            )
            == 3
        )
        assert destination.read_text() == "existing capture"
        assert not list(tmp_path.glob(".collationdelta-*"))


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda r: r["results"].append(r["results"][0]), "too many results"),
        (lambda r: r["results"].__setitem__(1, r["results"][0]), "duplicate"),
        (lambda r: r["results"][0].__setitem__("left", "unrequested"), "unrequested"),
        (lambda r: r["results"][0].__setitem__("value", True), "finite number"),
        (lambda r: r["results"][0].__setitem__("value", 1), "self comparison"),
    ],
)
def test_browser_observations_use_existing_validation(browser_capture, mutation, match):
    observed = copy.deepcopy(browser_capture["observation"])
    mutation(observed)
    with pytest.raises(DeltaError, match=match):
        response(observed, browser_capture["corpus"]["entries"])


def test_browser_missing_and_pair_failure_are_explicit(browser_capture):
    observed = copy.deepcopy(browser_capture["observation"])
    observed["results"].pop()
    item = observed["results"][0]
    item.pop("value")
    item.update(status="error", reason="explicit comparator failure")
    _, coverage, _ = response(observed, browser_capture["corpus"]["entries"])
    assert coverage["missing_comparisons"] == coverage["failed_comparisons"] == 1
    assert not coverage["complete"]


def test_incompatible_contract_and_offline_without_toolchain(browser_capture, tmp_path):
    saved = tmp_path / "capture.json"
    dump(saved, browser_capture)
    result = subprocess.run(
        [sys.executable, "-m", "collationdelta", "compare", str(saved), str(saved)],
        env={**os.environ, "PATH": "", "NODE_PATH": ""},
        capture_output=True,
        check=True,
    )
    assert b"STABLE" in result.stdout
    other = copy.deepcopy(browser_capture)
    other["requested"]["contract"] = "demo.fallback.v1"
    other["digest"] = digest({k: v for k, v in other.items() if k != "digest"})
    with pytest.raises(DeltaError, match="incompatible requested profiles"):
        compare(browser_capture, other)


def test_browser_rejects_other_contract(browser_command):
    cap = capture(document(["a"]), requested(contract="demo.fallback.v1"), browser_command)
    assert cap["observation"]["status"] == "unsupported"
    assert not cap["observation"]["results"]


def live_pids(group, profile_directory=""):
    output = subprocess.check_output(["ps", "-axo", "pid=,pgid=,stat=,command="], text=True)
    return [
        line
        for line in output.splitlines()
        if len(line.split()) >= 3
        and (line.split()[1] == str(group) or (profile_directory and profile_directory in line))
        and not line.split()[2].startswith("Z")
    ]


@pytest.mark.parametrize(
    "failure",
    [
        "success",
        "unsupported",
        "deadline",
        "outer-timeout",
        "outer-timeout-before-browser",
        "output-limit",
        "crash",
    ],
)
def test_real_process_group_cleanup(browser_command, tmp_path, monkeypatch, failure):
    marker = f"collationdelta-lifecycle-{tmp_path.name}"
    wrapper = tmp_path / marker
    group_file = tmp_path / "group.txt"
    profile_file = tmp_path / "browser-profile.txt"
    # A deliberately lingering descendant proves that the outer supervisor also runs on success.
    wrapper.write_text(
        f"#!{sys.executable}\nimport os,sys,time\n"
        f"open({str(group_file)!r}, 'w').write(str(os.getpgrp()))\n"
        f"open({str(profile_file)!r}, 'w').write(next(arg.split('=', 1)[1] for arg in sys.argv[1:] if arg.startswith('--user-data-dir=')))\n"
        "pid=os.fork()\n"
        "if pid==0:\n time.sleep(60)\n os._exit(0)\n"
        + ("time.sleep(60)\n" if failure in ("deadline", "outer-timeout") else "")
        + ("os._exit(7)\n" if failure == "crash" else "")
        + f"os.execv({EXECUTABLE!r}, [{EXECUTABLE!r}, *sys.argv[1:]])\n"
    )
    wrapper.chmod(0o755)
    command = [*browser_command, "--executable", str(wrapper)]
    limits = {}
    if failure == "deadline":
        command += ["--deadline-ms", "200"]
    if failure in ("outer-timeout", "outer-timeout-before-browser"):
        limits["timeout"] = 0.2
    if failure == "outer-timeout-before-browser":
        preload = tmp_path / "slow-start.mjs"
        preload.write_text("Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 500);\n")
        command = [NODE, "--import", str(preload), *command[1:]]
    if failure == "output-limit":
        limits["stdout_limit"] = 10
    processes = []
    original_popen = subprocess.Popen

    def track_process(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        if kwargs.get("start_new_session"):
            processes.append(process)
        return process

    # Record the supervisor group before Node or the browser can time out.
    with monkeypatch.context() as patch:
        patch.setattr("collationdelta.transport.subprocess.Popen", track_process)
        if failure in ("success", "unsupported"):
            cap = capture(
                document(["a", "b"]),
                requested("zz-ZZ" if failure == "unsupported" else "en"),
                command,
            )
            assert cap["coverage"]["complete"] is (failure == "success")
        else:
            with pytest.raises(DeltaError):
                capture(document(["a", "b"]), requested(), command, **limits)
    assert len(processes) == 1
    group = processes[0].pid
    if group_file.exists():
        assert int(group_file.read_text()) == group
    elif failure not in ("deadline", "outer-timeout", "outer-timeout-before-browser"):
        pytest.fail("expected browser wrapper to start")
    if failure == "outer-timeout-before-browser":
        assert not group_file.exists()
    profile_directory = profile_file.read_text() if profile_file.exists() else ""
    deadline = time.monotonic() + 5
    while live_pids(group, profile_directory) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not live_pids(group, profile_directory), "browser adapter left a live descendant"


@pytest.mark.parametrize("failure", ["closed-page", "stalled-evaluation", "pair-exception"])
def test_browser_context_failures(browser_command, tmp_path, failure):
    # Instrument a disposable copy solely to exercise real context failure paths.
    adapter = tmp_path / "browser.mjs"
    source = ADAPTER.read_text()
    helper = ADAPTER.with_name("intl.mjs").read_text()
    if failure == "closed-page":
        source = source.replace(
            "const response = await bounded(page.evaluate(observeIntl, request));",
            "await page.close();\n  const response = await bounded(page.evaluate(observeIntl, request));",
        )
    elif failure == "stalled-evaluation":
        helper = "export function observeIntl() { while (true) {} }\n"
        source = source.replace(
            "const response = await bounded(page.evaluate(observeIntl, request));",
            "process.stderr.write('browser evaluation started\\n');\n  const response = await bounded(page.evaluate(observeIntl, request));",
        )
    else:
        helper = helper.replace(
            "const value = collator.compare(left.value, right.value);",
            "if (left.id === '0' && right.id === '1') throw new Error('controlled browser pair failure');\n        const value = collator.compare(left.value, right.value);",
        )
    adapter.write_text(source)
    (tmp_path / "intl.mjs").write_text(helper)
    command = [NODE, str(adapter), *browser_command[2:]]
    if failure == "stalled-evaluation":
        command += ["--deadline-ms", "2500"]
    if failure == "pair-exception":
        cap = capture(document(["a", "b"]), requested(), command)
        assert cap["coverage"]["failed_comparisons"] == 1
        assert cap["coverage"]["completed_comparisons"] == 3
        assert not cap["coverage"]["complete"]
        assert any(
            r.get("reason") == "controlled browser pair failure"
            for r in cap["observation"]["results"]
        )
    else:
        with pytest.raises(
            DeltaError, match="deadline" if failure == "stalled-evaluation" else "closed"
        ) as error:
            capture(document(["a", "b"]), requested(), command, timeout=8)
        if failure == "stalled-evaluation":
            assert "browser evaluation started" in str(error.value)


@pytest.mark.parametrize("selection", ["missing", "empty", "no-package"])
def test_toolchain_selection_does_not_search_ancestors(
    browser_command, tmp_path, monkeypatch, selection
):
    ancestor = tmp_path / "ancestor"
    modules = ancestor / "node_modules"
    modules.mkdir(parents=True)
    (modules / "playwright-core").symlink_to(
        (Path(TOOLCHAIN) / "node_modules/playwright-core").resolve(), target_is_directory=True
    )
    selected = ancestor / selection
    if selection != "missing":
        selected.mkdir()
    if selection == "no-package":
        (selected / "node_modules/playwright-core").mkdir(parents=True)
    monkeypatch.setenv("NODE_PATH", str(modules))
    marker = tmp_path / "browser-started"
    probe = tmp_path / "browser-probe"
    probe.write_text(
        f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n"
    )
    probe.chmod(0o755)
    command = [*browser_command, "--toolchain", str(selected), "--executable", str(probe)]
    with pytest.raises(DeltaError, match="toolchain must contain an installed playwright-core"):
        capture(document(["a"]), requested(), command)
    assert not marker.exists()


def test_native_launch_isolates_credential_storage(browser_command, tmp_path):
    arguments = tmp_path / "arguments.json"
    wrapper = tmp_path / "credential-storage-probe"
    wrapper.write_text(
        f"#!{sys.executable}\nimport json,os,sys\n"
        f"open({str(arguments)!r}, 'w').write(json.dumps(sys.argv[1:]))\n"
        "required={'--password-store=basic','--use-mock-keychain'}\n"
        "if not required.issubset(sys.argv[1:]):\n sys.stderr.write('credential storage is not isolated\\n')\n sys.exit(7)\n"
        f"os.execv({EXECUTABLE!r}, [{EXECUTABLE!r}, *sys.argv[1:]])\n"
    )
    wrapper.chmod(0o755)
    cap = capture(
        document(["A", "a"]),
        requested(options={"sensitivity": "base"}),
        [*browser_command, "--executable", str(wrapper)],
    )
    assert cap["coverage"]["complete"]
    launched = json.loads(arguments.read_text())
    configured = cap["observation"]["runtime"]["execution"]["credential_store_flags"]
    assert set(configured) == {"--password-store=basic", "--use-mock-keychain"}
    assert set(configured).issubset(launched)
    assert "--headless" in launched
    assert "--no-sandbox" not in launched
    assert any(arg.startswith("--user-data-dir=") for arg in launched)


def test_browser_startup_waits_for_complete_endpoint_file(browser_command, tmp_path):
    wrapper = tmp_path / "endpoint-startup-probe"
    wrapper.write_text(
        f"#!{sys.executable}\nimport os,sys,time\nfrom pathlib import Path\n"
        "directory=next(arg.split('=', 1)[1] for arg in sys.argv[1:] if arg.startswith('--user-data-dir='))\n"
        "endpoint=Path(directory)/'DevToolsActivePort'\n"
        "endpoint.write_text('')\ntime.sleep(0.1)\n"
        "endpoint.write_text('1\\n')\ntime.sleep(0.1)\nendpoint.unlink()\n"
        f"os.execv({EXECUTABLE!r}, [{EXECUTABLE!r}, *sys.argv[1:]])\n"
    )
    wrapper.chmod(0o755)
    cap = capture(
        document(["a", "b"]), requested(), [*browser_command, "--executable", str(wrapper)]
    )
    assert cap["coverage"]["complete"]


@pytest.mark.parametrize(
    "contents,match",
    [("", "deadline"), ("invalid\n/not-an-endpoint", "invalid local CDP endpoint")],
)
def test_incomplete_or_invalid_endpoint_is_bounded(browser_command, tmp_path, contents, match):
    probe = tmp_path / "endpoint-failure-probe"
    probe.write_text(
        f"#!{sys.executable}\nimport sys,time\nfrom pathlib import Path\n"
        "directory=next(arg.split('=', 1)[1] for arg in sys.argv[1:] if arg.startswith('--user-data-dir='))\n"
        f"(Path(directory)/'DevToolsActivePort').write_text({contents!r})\n"
        "sys.stderr.write('endpoint probe started\\n');sys.stderr.flush()\ntime.sleep(60)\n"
    )
    probe.chmod(0o755)
    with pytest.raises(DeltaError, match=match) as error:
        capture(
            document(["a"]),
            requested(),
            [*browser_command, "--executable", str(probe), "--deadline-ms", "2000"],
            timeout=8,
        )
    assert "endpoint probe started" in str(error.value)
