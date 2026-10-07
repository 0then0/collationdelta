"""Regression coverage for capture integrity and bounded report construction."""

import json
import os
import subprocess
import sys
import tracemalloc

import pytest

from collationdelta.evidence import compare, human_report, validate_capture
from collationdelta.formats import DeltaError, decode, digest, dump, load


def sign(a, b):
    return (a > b) - (a < b)


def test_identical_values_cannot_have_a_strict_relation(make_capture):
    def invalid(reply):
        for result in reply["results"]:
            if result["left"] != result["right"]:
                result["value"] = sign(result["left"], result["right"])

    with pytest.raises(DeltaError, match="identical strings"):
        make_capture(("x", "x"), mutate=invalid)


def test_identical_values_have_consistent_relations_to_third_string(make_capture):
    def invalid(reply):
        # No direct observation between the identical records, but their known
        # comparisons to z contradict the comparator's string-value contract.
        reply["results"] = [
            {"left": "0", "right": "2", "status": "ok", "value": -1},
            {"left": "1", "right": "2", "status": "ok", "value": 1},
        ]

    with pytest.raises(DeltaError, match="cycle"):
        make_capture(("x", "x", "z"), mutate=invalid)


def test_duplicate_value_constraint_is_checked_when_loading_capture(make_capture):
    captured = make_capture(("x", "y"))
    captured["corpus"]["entries"][1]["value"] = "x"
    captured["digest"] = digest({k: v for k, v in captured.items() if k != "digest"})
    with pytest.raises(DeltaError, match="identical strings"):
        validate_capture(captured)


@pytest.mark.parametrize("magnitude", ["1e-400", "1e-999", "1e999", "5e-324"])
def test_exact_number_signs_survive_adapter_transport(make_capture, magnitude):
    def raw_transform(raw):
        return raw.replace("0.5", magnitude)

    old = make_capture(
        ("a", "b"), comparator=lambda a, b: sign(a, b) * 0.5, raw_transform=raw_transform
    )
    new = make_capture(
        ("a", "b"), comparator=lambda a, b: -sign(a, b) * 0.5, raw_transform=raw_transform
    )
    report = compare(old, new)
    assert report["status"] == "DRIFT" and report["complete"]
    assert [(f["kind"], f["old_relation"], f["new_relation"]) for f in report["findings"]] == [
        ("order_reversal", -1, 1)
    ]


@pytest.mark.parametrize("token", [b"1e-400", b"-1e-400", b"1e999"])
def test_configuration_numbers_do_not_silently_underflow_or_overflow(token):
    with pytest.raises(DeltaError):
        decode(token)


def test_decimal_zero_and_metadata_numbers_remain_json_compatible(make_capture):
    captured = make_capture(
        ("a", "b"),
        comparator=lambda a, b: 0.0,
        mutate=lambda r: r["runtime"].update(sample=1.25),
        raw_transform=lambda raw: raw.replace('"value": 0.0', '"value": 0e-400'),
    )
    assert captured["observation"]["runtime"]["sample"] == 1.25
    assert compare(captured, captured)["status"] == "STABLE"
    assert decode(b"-0e-400") == 0


@pytest.mark.parametrize("kind", ["equality_merge", "equality_split", "order_reversal"])
@pytest.mark.parametrize("old_orientation", ["forward", "reverse"])
@pytest.mark.parametrize("new_orientation", ["forward", "reverse"])
def test_partial_capture_keeps_direct_pair_witness_without_diagonals(
    make_capture, kind, old_orientation, new_orientation
):
    def keep_witness(orientation):
        def mutate(reply):
            pair = ("0", "1") if orientation == "forward" else ("1", "0")
            reply["results"] = [r for r in reply["results"] if (r["left"], r["right"]) == pair]

        return mutate

    before = (lambda a, b: 0) if kind == "equality_split" else sign
    after = (lambda a, b: 0) if kind == "equality_merge" else (lambda a, b: -sign(a, b))
    old = make_capture(("a", "b"), comparator=before)
    new = make_capture(("a", "b"), comparator=after)
    complete = compare(old, new)
    partial = compare(
        make_capture(("a", "b"), comparator=before, mutate=keep_witness(old_orientation)),
        make_capture(("a", "b"), comparator=after, mutate=keep_witness(new_orientation)),
    )
    assert partial["status"] == "DRIFT_INCOMPLETE" and not partial["complete"]
    assert all(side["coverage"]["completed_comparisons"] == 1 for side in partial["sides"].values())
    assert all(side["coverage"]["missing_comparisons"] == 3 for side in partial["sides"].values())
    assert partial["findings"] == complete["findings"]
    assert partial["findings"][0]["kind"] == kind


@pytest.mark.parametrize("old_pair", [("0", "1"), ("1", "0")])
@pytest.mark.parametrize("equal", [False, True])
def test_unchanged_opposite_orientations_remain_incomplete(make_capture, old_pair, equal):
    def keep(pair):
        def mutate(reply):
            reply["results"] = [r for r in reply["results"] if (r["left"], r["right"]) == pair]

        return mutate

    comparator = (lambda a, b: 0) if equal else sign
    old = make_capture(("a", "b"), comparator=comparator, mutate=keep(old_pair))
    new = make_capture(("a", "b"), comparator=comparator, mutate=keep(old_pair[::-1]))
    report = compare(old, new)
    assert report["status"] == "INCOMPLETE" and not report["complete"]
    assert report["finding_count"] == 0


@pytest.mark.parametrize("status", ["error", "unresolved", "missing"])
def test_pair_without_success_on_one_side_is_not_a_finding(make_capture, status):
    def no_success(reply):
        reply["results"] = (
            []
            if status == "missing"
            else [{"left": "0", "right": "1", "status": status, "reason": "not observed"}]
        )

    report = compare(make_capture(("a", "b")), make_capture(("a", "b"), mutate=no_success))
    assert report["status"] == "INCOMPLETE" and not report["complete"]
    assert report["finding_count"] == 0


def test_failed_diagonal_does_not_hide_observed_reversal(make_capture):
    def fail_diagonal(reply):
        reply["results"][0] = {"left": "0", "right": "0", "status": "error", "reason": "failed"}

    report = compare(
        make_capture(("a", "b")),
        make_capture(("a", "b"), comparator=lambda a, b: -sign(a, b), mutate=fail_diagonal),
    )
    assert report["status"] == "DRIFT_INCOMPLETE" and report["finding_count"] == 1


@pytest.mark.skipif(os.name != "posix", reason="POSIX file-size limits")
def test_capture_write_failure_preserves_valid_baseline(make_capture, tmp_path):
    baseline = tmp_path / "baseline.json"
    original = make_capture()
    dump(baseline, original)
    before = baseline.read_bytes()
    assert len(before) > 1024
    corpus, profile = tmp_path / "corpus.json", tmp_path / "profile.json"
    dump(corpus, original["corpus"])
    dump(profile, original["requested"])
    script = (
        "import resource,signal,sys;from collationdelta.cli import main;"
        "signal.signal(signal.SIGXFSZ,signal.SIG_IGN);"
        "resource.setrlimit(resource.RLIMIT_FSIZE,(1024,1024));"
        "raise SystemExit(main(sys.argv[1:]))"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            script,
            "capture",
            "--corpus",
            str(corpus),
            "--profile",
            str(profile),
            "--output",
            str(baseline),
            "--",
            *original["run"]["argv"],
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 3 and "ERROR:" in result.stderr
    assert baseline.read_bytes() == before
    assert compare(load(baseline), original)["status"] == "STABLE"
    assert not list(tmp_path.glob(".collationdelta-*"))


def test_atomic_dump_success_and_failed_replace(make_capture, tmp_path, monkeypatch):
    baseline = tmp_path / "baseline.json"
    old, new = make_capture(), make_capture(comparator=lambda a, b: -sign(a, b))
    dump(baseline, old)
    before = baseline.read_bytes()

    def failed_replace(source, destination):
        raise OSError("replacement failed")

    with monkeypatch.context() as patch:
        patch.setattr("collationdelta.formats.os.replace", failed_replace)
        with pytest.raises(OSError, match="replacement failed"):
            dump(baseline, new)
    assert baseline.read_bytes() == before
    assert not list(tmp_path.glob(".collationdelta-*"))
    dump(baseline, new)
    assert load(baseline) == new


def test_output_limit_preserves_destination_and_cleans_tempfile(tmp_path, monkeypatch):
    destination = tmp_path / "report.json"
    dump(destination, {"original": True})
    before = destination.read_bytes()
    monkeypatch.setattr("collationdelta.formats.MAX_FILE_BYTES", 128)
    with pytest.raises(DeltaError, match="32 MiB"):
        dump(destination, {"oversized": "x" * 1024})
    assert destination.read_bytes() == before
    assert not list(tmp_path.glob(".collationdelta-*"))


def test_many_findings_fit_a_bounded_report_allocation(make_capture, tmp_path, monkeypatch):
    values = tuple(f"{i:03d}" + "x" * 509 for i in range(64))
    old = make_capture(values)
    new = make_capture(values, comparator=lambda a, b: -sign(a, b))
    tracemalloc.start()
    try:
        report = compare(old, new)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert report["finding_count"] == 2016
    # The previous implementation allocates over 100 MiB for this corpus.
    assert peak < 24 * 1024 * 1024
    assert "Shown 1 of 2016" in human_report(report, limit=1)
    assert len(json.loads(json.dumps(report))["findings"]) == 2016

    # Oversized output must be rejected during streaming, before allocating the
    # entire serialized report. The full evidence remains available in memory.
    monkeypatch.setattr("collationdelta.formats.MAX_FILE_BYTES", 1024 * 1024)
    tracemalloc.start()
    try:
        with pytest.raises(DeltaError, match="output exceeds"):
            dump(tmp_path / "oversized-report.json", report)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 8 * 1024 * 1024
    assert not (tmp_path / "oversized-report.json").exists()
    assert not list(tmp_path.glob(".collationdelta-*"))
