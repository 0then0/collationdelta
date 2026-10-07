"""Capture persistence and deterministic offline relation reports."""

import datetime
import itertools
import json
import os
import platform

from . import __version__
from .formats import canonical, corpus, decode, digest, fields, profile, require
from .observations import response
from .transport import run


def capture(entries_document, requested, argv, **limits):
    corpus(entries_document)
    profile(requested)
    request = {"protocol_version": 1, "corpus": entries_document, "profile": requested}
    out, err = run(argv, canonical(request), **limits)
    observed, coverage, _ = response(decode(out, exact_results=True), entries_document["entries"])
    payload = {
        "format_version": 1,
        "corpus": entries_document,
        "requested": requested,
        "observation": observed,
        "coverage": coverage,
        "run": {
            "argv": list(argv),
            "cwd": os.getcwd(),
            "platform": platform.platform(),
            "captured_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "tool_version": __version__,
            "timeout_seconds": limits.get("timeout", 30.0),
            "stdout_limit_bytes": limits.get("stdout_limit", 16 * 1024 * 1024),
            "stderr_limit_bytes": limits.get("stderr_limit", 1024 * 1024),
            "stderr": err.decode("utf-8", errors="replace"),
        },
    }
    return dict(payload, digest=digest(payload))


def validate_capture(value):
    fields(
        value, ("format_version", "corpus", "requested", "observation", "coverage", "run", "digest")
    )
    require(
        type(value["format_version"]) is int and value["format_version"] == 1,
        "unsupported capture format version",
    )
    require(
        isinstance(value["digest"], str)
        and value["digest"] == digest({k: v for k, v in value.items() if k != "digest"}),
        "capture digest mismatch",
    )
    corpus(value["corpus"])
    profile(value["requested"])
    _, coverage, relations = response(
        value["observation"], value["corpus"]["entries"], normalized=True
    )
    require(
        canonical(coverage) == canonical(value["coverage"]),
        "capture coverage does not match observations",
    )
    info = value["run"]
    fields(
        info,
        (
            "argv",
            "cwd",
            "platform",
            "captured_at",
            "tool_version",
            "timeout_seconds",
            "stdout_limit_bytes",
            "stderr_limit_bytes",
            "stderr",
        ),
    )
    require(
        isinstance(info["argv"], list)
        and info["argv"]
        and all(isinstance(arg, str) and arg for arg in info["argv"]),
        "invalid capture argv",
    )
    for key in ("cwd", "platform", "captured_at", "tool_version", "stderr"):
        require(isinstance(info[key], str), f"invalid run field: {key}")
    for key in ("stdout_limit_bytes", "stderr_limit_bytes"):
        require(type(info[key]) is int and info[key] > 0, f"invalid run limit: {key}")
    require(
        type(info["timeout_seconds"]) in (int, float)
        and 0 < info["timeout_seconds"] < float("inf"),
        "invalid run timeout",
    )
    return relations


def compare(old, new):
    old_rel, new_rel = validate_capture(old), validate_capture(new)
    left = {entry["id"]: entry["value"] for entry in old["corpus"]["entries"]}
    right = {entry["id"]: entry["value"] for entry in new["corpus"]["entries"]}
    require(left == right, "incompatible corpora: IDs and exact scalar strings must match")
    require(
        canonical(old["requested"]) == canonical(new["requested"]),
        "incompatible requested profiles",
    )
    sides = {
        label: {
            "capture_digest": side["digest"],
            "effective": side["observation"]["effective"],
            "runtime": side["observation"]["runtime"],
            "adapter": side["observation"]["adapter"],
            "status": side["observation"]["status"],
            "reason": side["observation"].get("reason"),
            "coverage": side["coverage"],
        }
        for label, side in (("old", old), ("new", new))
    }
    findings = []
    records_by_id = {}

    def record(entry_id):
        if entry_id not in records_by_id:
            value = left[entry_id]
            records_by_id[entry_id] = {
                "id": entry_id,
                "value": value,
                "escaped": json.dumps(value, ensure_ascii=True),
                "code_points": [f"U+{ord(c):04X}" for c in value],
            }
        return records_by_id[entry_id]

    for a, b in itertools.combinations(sorted(left), 2):
        # Use the same directly observed orientation on both sides. Reverse
        # witnesses are oriented by stable ID without inferring a missing result.
        if (a, b) in old_rel and (a, b) in new_rel:
            before, after = old_rel[a, b], new_rel[a, b]
        elif (b, a) in old_rel and (b, a) in new_rel:
            before, after = -old_rel[b, a], -new_rel[b, a]
        else:
            continue
        kind = None
        if before != 0 and after == 0:
            kind = "equality_merge"
        elif before == 0 and after != 0:
            kind = "equality_split"
        elif before * after < 0:
            kind = "order_reversal"
        if kind:
            records = [record(a), record(b)]
            identity = {
                "requested": old["requested"],
                "records": records,
                "kind": kind,
                "old_relation": before,
                "new_relation": after,
            }
            findings.append(
                {
                    "id": "cd1-" + digest(identity)[7:],
                    "kind": kind,
                    "records": records,
                    "old_relation": before,
                    "new_relation": after,
                }
            )
    complete = old["coverage"]["complete"] and new["coverage"]["complete"]
    status = (
        ("DRIFT" if complete else "DRIFT_INCOMPLETE")
        if findings
        else ("STABLE" if complete else "INCOMPLETE")
    )
    return {
        "report_version": 1,
        "status": status,
        "complete": complete,
        "requested": old["requested"],
        "sides": sides,
        "finding_count": len(findings),
        "findings": findings,
    }


def coverage_text(coverage):
    return (
        f"entries={coverage['entries']} comparisons={coverage['completed_comparisons']}/"
        f"{coverage['expected_comparisons']} missing={coverage['missing_comparisons']} "
        f"failed={coverage['failed_comparisons']} complete={str(coverage['complete']).lower()}"
    )


def human_report(report, limit=20):
    lines = [
        f"{report['status']} | findings={report['finding_count']} | complete={str(report['complete']).lower()}"
    ]
    for label, side in report["sides"].items():
        lines.append(f"{label}: {coverage_text(side['coverage'])}")
        if side["reason"]:
            lines.append(f"  {side['status']}: {json.dumps(side['reason'], ensure_ascii=True)}")
    lines.append("Equality means compare(a, b) == 0.")
    for finding in report["findings"][:limit]:
        lines.extend(["", f"{finding['id']} {finding['kind']}"])
        for record in finding["records"]:
            points = " ".join(record["code_points"]) or "(empty)"
            lines.append(
                f"  {json.dumps(record['id'], ensure_ascii=True)}: {record['escaped']} [{points}]"
            )
        lines.append(f"  relation: {finding['old_relation']:+d} -> {finding['new_relation']:+d}")
        for label, side in report["sides"].items():
            lines.append(
                f"  {label} runtime={json.dumps(side['runtime'], ensure_ascii=True, sort_keys=True)}"
            )
            lines.append(
                f"  {label} effective={json.dumps(side['effective'], ensure_ascii=True, sort_keys=True)}"
            )
    if len(report["findings"]) > limit:
        lines.append(
            f"\nShown {limit} of {report['finding_count']} findings; JSON contains all evidence."
        )
    if not report["findings"]:
        for label, side in report["sides"].items():
            lines.append(
                f"{label} runtime={json.dumps(side['runtime'], ensure_ascii=True, sort_keys=True)}"
            )
            lines.append(
                f"{label} effective={json.dumps(side['effective'], ensure_ascii=True, sort_keys=True)}"
            )
    return "\n".join(lines) + "\n"
