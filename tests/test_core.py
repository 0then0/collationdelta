import copy
import json
from functools import cmp_to_key

import pytest

from collationdelta.evidence import compare, human_report, validate_capture
from collationdelta.formats import DeltaError, corpus, decode, digest


def sign(a, b):
    return (a > b) - (a < b)


def seal(value):
    value["digest"] = digest({k: v for k, v in value.items() if k != "digest"})
    return value


def test_three_drift_types_and_same_labels(make_capture):
    old = make_capture(("a", "A"))
    new = make_capture(("a", "A"), lambda a, b: sign(a.lower(), b.lower()))
    merged = compare(old, new)
    assert merged["status"] == "DRIFT"
    assert [f["kind"] for f in merged["findings"]] == ["equality_merge"]
    assert compare(new, old)["findings"][0]["kind"] == "equality_split"
    reversed_capture = make_capture(("a", "A"), lambda a, b: -sign(a, b) * 17)
    finding = compare(old, reversed_capture)["findings"][0]
    assert finding["kind"] == "order_reversal"
    assert finding["old_relation"] == 1 and finding["new_relation"] == -1
    assert old["observation"]["runtime"] == new["observation"]["runtime"]


def test_version_change_alone_is_stable(make_capture):
    old = make_capture()
    new = copy.deepcopy(old)
    new["observation"]["runtime"]["version"] = "next"
    assert compare(old, seal(new))["status"] == "STABLE"


def test_sorted_snapshot_blind_spot(make_capture):
    old_cmp = sign

    def new_cmp(a, b):
        return sign(a.lower(), b.lower())

    values = ("A", "a")
    assert sorted(values, key=cmp_to_key(old_cmp)) == sorted(values, key=cmp_to_key(new_cmp))
    assert compare(make_capture(values), make_capture(values, new_cmp))["finding_count"] == 1


def test_duplicate_values_and_equal_distinct_values(make_capture):
    captured = make_capture(("A", "a", "A"), lambda a, b: sign(a.lower(), b.lower()))
    assert captured["coverage"]["completed_comparisons"] == 9
    assert len(captured["corpus"]["entries"]) == 3
    assert all(r["value"] == 0 for r in captured["observation"]["results"])
    assert compare(captured, captured)["status"] == "STABLE"


def test_unicode_preserved_and_escaped(make_capture):
    values = ("", "\x00", "a\nb", "e\u0301", "é", "😀", " \t", "\u202e")
    old = make_capture(values)
    assert tuple(e["value"] for e in old["corpus"]["entries"]) == values
    new = make_capture(values, lambda a, b: -sign(a, b))
    report = compare(old, new)
    human = human_report(report, 100)
    assert "\\u0000" in human and "U+1F600" in human and "\\u202e" in human
    assert "\x00" not in human and "\u202e" not in human
    assert report["finding_count"] == 28


@pytest.mark.parametrize(
    "data",
    [
        b'"\xff"',
        b'"\\ud800"',
        b'"\\udfff"',
        b'{"a":1,"a":2}',
        b"NaN",
        b"1e999",
        b"{",
        b'"\xed\xa0\x80"',
    ],
)
def test_bad_json_unicode(data):
    with pytest.raises(DeltaError):
        decode(data)


def test_surrogate_pair_decodes_to_scalar():
    assert decode(b'"\\ud83d\\ude00"') == "😀"


def test_corpus_bounds_and_duplicate_ids():
    for entries in (
        [],
        [{"id": "x", "value": "a"}] * 2,
        [{"id": str(i), "value": ""} for i in range(257)],
        [{"id": "x", "value": 1}],
    ):
        with pytest.raises(DeltaError):
            corpus({"version": 1, "entries": entries})


def test_incompatible_corpus_and_profile(make_capture):
    old = make_capture()
    with pytest.raises(DeltaError, match="incompatible corpora"):
        compare(old, make_capture(("a", "b", "d")))
    new = copy.deepcopy(old)
    new["requested"]["options"] = {"numeric": True}
    with pytest.raises(DeltaError, match="incompatible requested profiles"):
        compare(old, seal(new))


def test_reordered_corpus_is_compatible(make_capture):
    old = make_capture()
    new = copy.deepcopy(old)
    new["corpus"]["entries"].reverse()
    assert compare(old, seal(new))["status"] == "STABLE"


def test_digest_and_coverage_not_trusted(make_capture):
    old = make_capture()
    new = copy.deepcopy(old)
    new["corpus"]["entries"][0]["value"] = "altered"
    with pytest.raises(DeltaError, match="digest mismatch"):
        compare(old, new)
    new = copy.deepcopy(old)
    new["coverage"]["complete"] = False
    with pytest.raises(DeltaError, match="coverage"):
        validate_capture(seal(new))
    new["coverage"] = old["coverage"]
    new["format_version"] = 2
    with pytest.raises(DeltaError, match="format version"):
        validate_capture(seal(new))


def test_recomputed_digest_does_not_bypass_consistency(make_capture):
    captured = make_capture()
    captured["observation"]["results"][0]["value"] = 1
    with pytest.raises(DeltaError, match="self comparison"):
        validate_capture(seal(captured))


def test_incomplete_capture_retains_findings(make_capture):
    old = make_capture()
    new = make_capture(comparator=lambda a, b: -sign(a, b), mutate=lambda r: r["results"].pop())
    report = compare(old, new)
    assert report["status"] == "DRIFT_INCOMPLETE"
    assert report["finding_count"] == 3
    assert not report["complete"]
    assert new["coverage"]["missing_comparisons"] == 1
    assert compare(new, new)["status"] == "INCOMPLETE"


def test_failed_comparison_is_not_equality(make_capture):
    def fail(reply):
        reply["results"][1] = {
            "left": "0",
            "right": "1",
            "status": "error",
            "reason": "application exception",
        }

    old = make_capture()
    new = make_capture(mutate=fail)
    assert new["coverage"]["failed_comparisons"] == 1
    assert compare(old, new)["status"] == "INCOMPLETE"
    assert compare(old, new)["finding_count"] == 0


def test_unsupported_and_unresolved(make_capture):
    def unsupported(reply):
        reply.update(status="unsupported", effective=None, results=[], reason="locale unavailable")

    old = make_capture()
    new = make_capture(mutate=unsupported)
    assert new["coverage"]["completed_comparisons"] == 0
    assert compare(old, new)["status"] == "INCOMPLETE"

    def unresolved(reply):
        reply.update(status="unresolved", reason="one backend unavailable")

    partial = make_capture(comparator=lambda a, b: -sign(a, b), mutate=unresolved)
    assert compare(old, partial)["status"] == "DRIFT_INCOMPLETE"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r["results"].__setitem__(1, r["results"][0]),
        lambda r: r["results"][0].update(left="unknown"),
        lambda r: r["results"][0].update(value=True),
        lambda r: r["results"][0].update(value="0"),
        lambda r: r["results"][0].update(status="other"),
        lambda r: r.update(protocol_version=2),
        lambda r: r.update(effective=None),
        lambda r: r.update(runtime={}),
        lambda r: r.update(reason=7),
        lambda r: r.update(results={}),
        lambda r: r["results"][0].update(value=1),
        lambda r: r["results"][1].update(value=1),
    ],
)
def test_invalid_protocol_and_relations(make_capture, mutation):
    with pytest.raises(DeltaError):
        make_capture(mutate=mutation)


def test_equality_and_order_transitivity(make_capture):
    def contradictory_equality(a, b):
        return sign(a, b) if {a, b} == {"a", "c"} else 0

    with pytest.raises(DeltaError, match="equality transitivity"):
        make_capture(comparator=contradictory_equality)

    def cycle(a, b):
        return 0 if a == b else (-1 if (a, b) in [("a", "b"), ("b", "c"), ("c", "a")] else 1)

    with pytest.raises(DeltaError, match="cycle"):
        make_capture(comparator=cycle)


def test_deterministic_reports_and_human_limit(make_capture):
    old = make_capture()
    new = make_capture(comparator=lambda a, b: -sign(a, b))
    report = compare(old, new)
    assert json.dumps(report, sort_keys=True) == json.dumps(compare(old, new), sort_keys=True)
    assert human_report(report, 1) == human_report(report, 1)
    assert "Shown 1 of 3" in human_report(report, 1)
    assert len(report["findings"]) == 3
    repeated = make_capture(comparator=lambda a, b: -sign(a, b))
    assert [f["id"] for f in compare(old, repeated)["findings"]] == [
        f["id"] for f in report["findings"]
    ]


def test_maximum_corpus(make_capture):
    captured = make_capture(tuple(f"s{i:03}" for i in range(256)))
    assert captured["coverage"]["completed_comparisons"] == 65536
    assert compare(captured, captured)["status"] == "STABLE"
