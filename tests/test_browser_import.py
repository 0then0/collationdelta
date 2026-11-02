"""Offline browser import boundary; generated fixtures are explicitly synthetic."""

import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from collationdelta.browser_import import EXPORT_LIMIT, import_browser
from collationdelta.cli import main
from collationdelta.evidence import compare, validate_capture
from collationdelta.formats import DeltaError, decode, digest, dump, load
from collationdelta.observations import response

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def export():
    corpus = load(ROOT / "examples/browser-page/corpus.json")
    requested = load(ROOT / "examples/browser-page/profile.json")
    effective = {
        "locale": "en",
        "usage": "sort",
        "sensitivity": "base",
        "ignorePunctuation": False,
        "collation": "default",
        "numeric": False,
        "caseFirst": "false",
    }
    observation = {
        "protocol_version": 1,
        "status": "ok",
        "effective": effective,
        "runtime": {
            "intl": {
                "canonical_locale": "en",
                "supported_locales": ["en"],
                "resolved_options": copy.deepcopy(effective),
            }
        },
        "adapter": {"contract": "intl.collator.v1"},
        # Synthetic scalar order: these are schema/consistency tests, not Intl observations.
        "results": [
            {
                "left": a["id"],
                "right": b["id"],
                "status": "ok",
                "value": (a["value"] > b["value"]) - (a["value"] < b["value"]),
            }
            for a in corpus["entries"]
            for b in corpus["entries"]
        ],
    }
    return {
        "browser_export_version": 1,
        "corpus": corpus,
        "requested": requested,
        "observation": observation,
        "coverage": response(observation, corpus["entries"])[1],
        "metadata": {
            "page_version": 1,
            "captured_at": "2026-11-02T12:00:00.000Z",
            "execution_context": {
                "kind": "dedicated-worker",
                "has_document": False,
                "has_process": False,
            },
            "user_agent": "synthetic test fixture",
            "navigator_platform": "test",
            "caller_labels": {"label": "not runtime evidence"},
        },
    }


def test_browser_export_cli_import_offline_compare(export, tmp_path):
    source, output = tmp_path / "export.json", tmp_path / "capture.json"
    dump(source, export)
    assert main(["import-browser", str(source), "--output", str(output)]) == 0
    cap = load(output)
    validate_capture(cap)
    assert cap["format_version"] == 2 and "run" not in cap
    assert cap["corpus"] == export["corpus"]
    assert cap["requested"] == export["requested"]
    assert cap["provenance"]["metadata"] == export["metadata"]
    report = compare(cap, cap)
    assert report["status"] == "STABLE"
    assert report["sides"]["old"]["provenance"] == cap["provenance"]
    result = subprocess.run(
        [sys.executable, "-m", "collationdelta", "compare", str(output), str(output)],
        env={**os.environ, "PATH": "", "NODE_PATH": ""},
        capture_output=True,
    )
    assert result.returncode == 0 and b"STABLE" in result.stdout


def unsupported(export):
    export["requested"]["locale"] = "zz-ZZ"
    export["observation"].update(
        status="unsupported", reason="requested locale has no supported lookup match", results=[]
    )
    export["observation"]["runtime"]["intl"].update(canonical_locale="zz-ZZ", supported_locales=[])
    export["coverage"] = response(export["observation"], export["corpus"]["entries"])[1]
    return export


def test_unsupported_stays_incomplete_and_saves(export, tmp_path):
    export = unsupported(export)
    cap = import_browser(export)
    assert compare(cap, cap)["status"] == "INCOMPLETE"
    assert cap["observation"]["effective"]["locale"] == "en"
    source, output = tmp_path / "export.json", tmp_path / "capture.json"
    dump(source, export)
    assert main(["import-browser", str(source), "--output", str(output)]) == 2
    validate_capture(load(output))


@pytest.mark.parametrize(
    "path,value",
    [
        (("browser_export_version",), 2),
        (("browser_export_version",), True),
        (("corpus", "version"), 2),
        (("requested", "version"), 2),
        (("requested", "contract"), "other.v1"),
        (("extra",), "not allowed"),
        (("coverage", "complete"), False),
        (("coverage", "entries"), True),
        (("coverage", "missing_comparisons"), 1),
        (("coverage", "extra"), 1),
        (("metadata", "page_version"), 2),
        (("metadata", "captured_at"), "not a date"),
        (("metadata", "captured_at"), "2026-11-02T12:00:00"),
        (("metadata", "execution_context", "kind"), "window"),
        (("metadata", "execution_context", "has_document"), 0),
        (("metadata", "engine"), "guessed"),
        (("metadata", "caller_labels", "label"), "x" * 257),
        (("observation", "protocol_version"), 2),
        (("observation", "runtime", "intl", "supported_locales"), []),
        (("observation", "runtime", "intl", "resolved_options", "numeric"), True),
        (("observation", "adapter", "contract"), "other.v1"),
        (("requested", "options", "sensitivity"), "variant"),
        (("requested", "options", "numeric"), 0),
        (("requested", "options", "localeMatcher"), "best fit"),
        (("observation", "results", 0, "value"), True),
        (("observation", "results", 0, "value"), 0.0),
        (("observation", "results", 0, "value"), 2),
        (("observation", "results", 0, "value"), 1),
        (("observation", "results", 0, "left"), "unknown"),
        (("corpus", "entries", 0, "value"), "\ud800"),
        (("corpus", "entries", 0, "id"), ""),
    ],
)
def test_invalid_export_is_error_and_output_untouched(export, tmp_path, path, value):
    target = export
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    source, output = tmp_path / "bad.json", tmp_path / "saved.json"
    # Write using JSON escaping so invalid scalar strings reach the strict decoder.
    source.write_text(json.dumps(export, ensure_ascii=True))
    output.write_bytes(b"existing output\n")
    assert main(["import-browser", str(source), "--output", str(output)]) == 3
    assert output.read_bytes() == b"existing output\n"
    assert not list(tmp_path.glob(".collationdelta-*"))


@pytest.mark.parametrize(
    "raw",
    [
        b'{"browser_export_version":1,"browser_export_version":1}',
        b'{"a":1,"\\u0061":2}',
        b'{"x":"\\udc00"}',
        b'{"x":"\xff"}',
        b'{"x":1e999}',
        b'{"x":1e-400}',
        b'{"x":NaN}',
    ],
)
def test_strict_decoder_is_unchanged(raw, tmp_path):
    source, output = tmp_path / "bad.json", tmp_path / "output"
    source.write_bytes(raw)
    output.write_text("old")
    assert main(["import-browser", str(source), "--output", str(output)]) == 3
    assert output.read_text() == "old"


def test_unicode_js_json_order_and_integer_signs(export):
    raw = json.dumps(export, ensure_ascii=False, separators=(",", ":")).encode()
    cap = import_browser(decode(raw))
    assert cap["corpus"] == export["corpus"]
    assert cap["digest"] == digest({k: v for k, v in cap.items() if k != "digest"})
    assert decode(b'"\\ud83d\\ude00"') == "😀"
    for token in ("1e-400", "1e999", "1.0", "-0.0", "true", '"0"'):
        raw = json.dumps(export).replace('"value": 0}', f'"value": {token}}}', 1).encode()
        with pytest.raises(DeltaError):
            import_browser(decode(raw))


def test_duplicate_pairs_missing_pairs_and_contradictions(export):
    export["observation"]["results"][1] = export["observation"]["results"][0]
    with pytest.raises(DeltaError, match="duplicate"):
        import_browser(export)
    export["observation"]["results"].pop(1)
    export["coverage"] = response(export["observation"], export["corpus"]["entries"])[1]
    with pytest.raises(DeltaError, match="all ordered pairs"):
        import_browser(export)


def test_cycles_and_reverse_relations_use_core_validator(export):
    entries = [{"id": c, "value": c} for c in "abc"]
    export["corpus"]["entries"] = entries
    results = [
        {
            "left": a["id"],
            "right": b["id"],
            "status": "ok",
            "value": (a["id"] > b["id"]) - (a["id"] < b["id"]),
        }
        for a in entries
        for b in entries
    ]
    export["observation"]["results"] = results
    results[2]["value"] = 1
    with pytest.raises(DeltaError, match="reverse"):
        import_browser(export)
    results[6]["value"] = -1
    with pytest.raises(DeltaError, match="cycle"):
        import_browser(export)


def test_import_size_limits_and_atomic_output(export, tmp_path):
    source, output = tmp_path / "export", tmp_path / "output"
    source.write_bytes(b" " * (EXPORT_LIMIT + 1))
    output.write_text("old")
    assert main(["import-browser", str(source), "--output", str(output)]) == 3
    assert output.read_text() == "old"
    export["corpus"]["entries"][0]["value"] = "a" * (1024 * 1024)
    with pytest.raises(DeltaError, match="1 MiB"):
        import_browser(export)


def test_import_digest_and_v2_provenance_validation(export):
    cap = import_browser(export)
    cap["provenance"]["metadata"]["user_agent"] = "altered"
    with pytest.raises(DeltaError, match="digest"):
        validate_capture(cap)
    cap["provenance"]["version"] = 2
    cap["digest"] = digest({k: v for k, v in cap.items() if k != "digest"})
    with pytest.raises(DeltaError, match="provenance version"):
        validate_capture(cap)


def test_old_captures_and_reports_still_work():
    for case in ("node-upgrade", "node-browser"):
        for path in (ROOT / "evidence" / case).glob("*.capture.json"):
            cap = load(path)
            assert cap["format_version"] == 1
            validate_capture(cap)


def test_no_paths_urls_or_commands_accepted(export, tmp_path, monkeypatch):
    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **kw: pytest.fail("import must not execute")
    )
    export["metadata"]["caller_labels"]["label"] = (
        "https://example.invalid/ /etc/passwd $(touch /tmp/wrong)"
    )
    cap = import_browser(export)
    validate_capture(cap)
    export["metadata"]["argv"] = ["sh", "-c", "false"]
    with pytest.raises(DeltaError):
        import_browser(export)


def test_production_build_copies_single_intl_source(tmp_path):
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/build_browser_page.py"),
            "--output",
            str(tmp_path / "collationdelta"),
        ],
        check=True,
    )
    assert (tmp_path / "collationdelta/intl.mjs").read_bytes() == (
        ROOT / "src/collationdelta/adapters/intl.mjs"
    ).read_bytes()
    assert not (ROOT / "web/intl.mjs").exists()


@pytest.mark.skipif(
    not os.environ.get("COLLATIONDELTA_PAGE_BROWSERS"),
    reason="real browser-page integration requires COLLATIONDELTA_PAGE_BROWSERS=chromium,firefox and installed toolchain/browsers",
)
def test_real_browser_page_export_import_compare(tmp_path):
    toolchain = os.environ["COLLATIONDELTA_BROWSER_TOOLCHAIN"]
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/reproduce_page_case.py"),
            "--node",
            shutil.which("node"),
            "--toolchain",
            toolchain,
            "--output",
            str(tmp_path),
            "--browsers",
            *os.environ["COLLATIONDELTA_PAGE_BROWSERS"].split(","),
        ],
        check=True,
        timeout=180,
    )


@pytest.mark.parametrize(
    "locale,option,setting",
    [
        ("en-u-kn-true", "numeric", False),
        ("en-u-kf-upper", "caseFirst", "false"),
        ("de-u-co-phonebk", "collation", "default"),
    ],
)
def test_original_unicode_requests_cannot_disappear(export, tmp_path, locale, option, setting):
    export["requested"]["locale"] = locale
    export["observation"]["effective"][option] = setting
    export["observation"]["runtime"]["intl"]["resolved_options"][option] = setting
    source, output = tmp_path / "export.json", tmp_path / "capture.json"
    dump(source, export)
    output.write_text("existing")
    assert main(["import-browser", str(source), "--output", str(output)]) == 3
    assert output.read_text() == "existing"
    # Explicit options override the extension, exactly as in observeIntl().
    export["requested"]["options"][option] = setting
    validate_capture(import_browser(export))


def test_empty_collation_cannot_be_successful(export):
    export["requested"]["options"]["collation"] = ""
    export["observation"]["effective"]["collation"] = ""
    export["observation"]["runtime"]["intl"]["resolved_options"]["collation"] = ""
    with pytest.raises(DeltaError, match="invalid resolved collation"):
        import_browser(export)
    # A genuine configuration refusal remains valid incomplete evidence.
    export["observation"].update(
        status="unsupported", reason="Intl configuration rejected", results=[], effective=None
    )
    export["observation"]["runtime"]["intl"].update(
        canonical_locale="en", supported_locales=["en"], resolved_options=None
    )
    export["coverage"] = response(export["observation"], export["corpus"]["entries"])[1]
    assert compare(import_browser(export), import_browser(export))["status"] == "INCOMPLETE"
