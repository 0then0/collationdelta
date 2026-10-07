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
