import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import collationdelta
from collationdelta.cli import main
from collationdelta.evidence import capture, compare
from collationdelta.formats import dump

NODE = shutil.which("node")
ADAPTER = Path(collationdelta.__file__).parent / "adapters" / "node.mjs"
pytestmark = pytest.mark.skipif(NODE is None, reason="Node not installed; CI installs Node")


def requested(locale="en", options=None):
    return {
        "version": 1,
        "contract": "intl.collator.v1",
        "locale": locale,
        "options": {"sensitivity": "base"} if options is None else options,
    }


def document(values):
    return {
        "version": 1,
        "entries": [{"id": str(i), "value": value} for i, value in enumerate(values)],
    }


def test_real_intl_metadata_unicode_and_control():
    values = ["", "\x00", "e\u0301", "é", "😀", "A", "a", "A", "x\ny"]
    cap = capture(document(values), requested(), [NODE, str(ADAPTER)])
    assert cap["coverage"]["complete"]
    assert cap["observation"]["runtime"]["node"].startswith("v")
    assert cap["observation"]["runtime"]["icu"]
    assert cap["observation"]["effective"]["sensitivity"] == "base"
    rel = {(r["left"], r["right"]): r["value"] for r in cap["observation"]["results"]}
    assert rel["2", "3"] == 0 and rel["5", "6"] == 0 and rel["5", "7"] == 0
    repeat = capture(document(values), requested(), [NODE, str(ADAPTER)])
    assert cap["observation"] == repeat["observation"]
    assert compare(cap, repeat)["status"] == "STABLE"


@pytest.mark.parametrize(
    "locale,options",
    [
        ("zz-ZZ", {}),
        ("en", {"collation": "foobar"}),
        ("en-u-co-foobar", {}),
        ("en", {"numeric": "true"}),
        ("en", {"unknown": True}),
        ("en-u-kn-foobar", {}),
        ("en-u-kf-foobar", {}),
    ],
)
def test_no_silent_unsupported_fallback(locale, options):
    cap = capture(document(["a", "b"]), requested(locale, options), [NODE, str(ADAPTER)])
    assert cap["observation"]["status"] == "unsupported"
    assert not cap["coverage"]["complete"]
    assert compare(cap, cap)["status"] == "INCOMPLETE"


@pytest.mark.parametrize("locale", ["EN-us", "en-XX", "en-u-kn-true", "de-u-co-phonebk"])
def test_canonicalization_negotiation_and_extensions(locale):
    cap = capture(document(["2", "10"]), requested(locale, {}), [NODE, str(ADAPTER)])
    assert cap["coverage"]["complete"]


@pytest.mark.parametrize(
    "locale,numeric,case_first",
    [
        ("en-x-u-kn-true", False, "false"),
        ("en-x-u-kf-upper", False, "false"),
        ("en-u-kn-true-x-u-kf-upper", True, "false"),
        ("en-u-kf-upper-x-u-kn-true", False, "upper"),
    ],
)
def test_private_use_tokens_do_not_become_unicode_extension_options(locale, numeric, case_first):
    cap = capture(document(["2", "10"]), requested(locale, {}), [NODE, str(ADAPTER)])
    direct = json.loads(
        subprocess.check_output(
            [
                NODE,
                "-e",
                "console.log(JSON.stringify(new Intl.Collator(process.argv[1],"
                "{localeMatcher:'lookup'}).resolvedOptions()))",
                locale,
            ]
        )
    )
    assert cap["coverage"]["complete"]
    assert cap["observation"]["effective"] == direct
    assert direct["numeric"] == numeric and direct["caseFirst"] == case_first


def test_intl_options_delegate_to_provider():
    options = {
        "sensitivity": "variant",
        "numeric": True,
        "caseFirst": "upper",
        "ignorePunctuation": True,
        "usage": "sort",
        "collation": "phonebk",
    }
    cap = capture(document(["2", "10", "A", "a"]), requested("de", options), [NODE, str(ADAPTER)])
    assert cap["coverage"]["complete"]
    assert all(cap["observation"]["effective"][k] == v for k, v in options.items())
    rel = {(r["left"], r["right"]): r["value"] for r in cap["observation"]["results"]}
    assert rel["0", "1"] < 0


def test_capture_cli_and_packaged_adapter(tmp_path, capsys):
    corpus_path, profile_path, output = [
        tmp_path / name for name in ("corpus.json", "profile.json", "capture.json")
    ]
    dump(corpus_path, document(["A", "a"]))
    dump(profile_path, requested())
    assert (
        main(
            [
                "capture",
                "--corpus",
                str(corpus_path),
                "--profile",
                str(profile_path),
                "--output",
                str(output),
                "--",
                NODE,
                str(ADAPTER),
            ]
        )
        == 0
    )
    assert "CAPTURED" in capsys.readouterr().out
    assert json.loads(output.read_text())["coverage"]["complete"]


def test_custom_application_adapter():
    root = Path(__file__).resolve().parents[1]
    profile = {"version": 1, "contract": "demo.scalar-order.v1", "locale": "und", "options": {}}
    cap = capture(
        document(["a", "b"]),
        profile,
        [sys.executable, str(root / "examples/application_adapter.py")],
    )
    assert cap["coverage"]["complete"]


def test_demonstration_uses_actual_collator():
    root = Path(__file__).resolve().parents[1]
    demo = json.loads(subprocess.check_output([NODE, str(root / "examples/application.mjs")]))
    assert demo["sorted"] == ["₨", "Rs"]
    assert len(demo["distinct"]) == (1 if demo["rupeeToLetters"] == 0 else 2)
