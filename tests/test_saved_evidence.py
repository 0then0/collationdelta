"""Offline assertions against actual committed runtime observations, not mocks."""

from pathlib import Path

from collationdelta.evidence import compare
from collationdelta.formats import load

EVIDENCE = Path(__file__).resolve().parents[1] / "evidence/node-upgrade"


def test_saved_real_upgrade_and_negative_controls():
    old, new = load(EVIDENCE / "old.capture.json"), load(EVIDENCE / "new.capture.json")
    report = compare(old, new)
    assert report == load(EVIDENCE / "upgrade.report.json")
    assert report["status"] == "DRIFT" and report["finding_count"] == 2
    assert [(f["kind"], f["old_relation"], f["new_relation"]) for f in report["findings"]] == [
        ("equality_merge", 1, 0),
        ("order_reversal", -1, 1),
    ]
    for label, expected in (
        ("old", ("v18.20.8", "74.2", "44.1")),
        ("new", ("v24.21.0", "78.3", "48.0")),
    ):
        first, second = (
            load(EVIDENCE / f"{label}.capture.json"),
            load(EVIDENCE / f"{label}-repeat.capture.json"),
        )
        runtime = first["observation"]["runtime"]
        assert (runtime["node"], runtime["icu"], runtime["cldr"]) == expected
        assert first["observation"] == second["observation"]
        assert compare(first, second)["status"] == "STABLE"
        assert first["coverage"]["completed_comparisons"] == 9


def test_saved_actual_application_outputs():
    experiment = load(EVIDENCE / "experiment.json")
    old, new = experiment["applications"]["old"], experiment["applications"]["new"]
    assert old["sorted"] == new["sorted"] == ["₨", "Rs"]
    assert old["distinct"] == ["₨", "Rs"] and new["distinct"] == ["₨"]
    assert old["rupeeToLetters"] == -1 and new["rupeeToLetters"] == 0
    assert old["rupeeToZero"] == -1 and new["rupeeToZero"] == 1


def test_saved_native_browser_case_completely_offline():
    root = EVIDENCE.parent / "node-browser"
    for locale, expected in (("en", "STABLE"), ("is", "INCOMPLETE")):
        node, browser = (
            load(root / f"{runtime}-{locale}.capture.json") for runtime in ("node", "browser")
        )
        report = compare(node, browser)
        assert report == load(root / f"{locale}.report.json")
        assert report["status"] == expected and report["finding_count"] == 0
        assert node["coverage"]["completed_comparisons"] == 64
        for runtime in ("node", "browser"):
            first, repeat = (
                load(root / f"{runtime}-{locale}{suffix}.capture.json")
                for suffix in ("", "-repeat")
            )
            assert first["observation"] == repeat["observation"]
            control = compare(first, repeat)
            assert control == load(root / f"{runtime}-{locale}-control.report.json")
            assert control["status"] == (
                "INCOMPLETE" if runtime == "browser" and locale == "is" else "STABLE"
            )
        observed = browser["observation"]
        assert observed["runtime"]["browser"]["version"] == "156.0.8078.4"
        assert observed["runtime"]["automation"]["version"] == "1.64.0"
        if locale == "is":
            assert observed["runtime"]["intl"]["supported_locales"] == []
            assert observed["effective"]["locale"] == "en-US"
            assert observed["status"] == "unsupported" and observed["results"] == []
            assert report["sides"]["new"]["reason"]
            assert browser["coverage"]["missing_comparisons"] == 64
        else:
            assert observed["runtime"]["intl"]["supported_locales"] == ["en"]
            assert browser["coverage"]["completed_comparisons"] == 64
    manifest = load(root / "experiment.json")
    assert all(manifest["repeatable_observations"].values())
    assert manifest["offline_cli_without_path"]
    assert (
        manifest["installation_provenance"]["browser"]["archive_sha256"]
        == "987d2f8499c87d21676f78178550cfcbfb1bb53786821e2cff46c5a7e99b58be"
    )
