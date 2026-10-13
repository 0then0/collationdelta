#!/usr/bin/env python3
"""Capture explicitly selected runtimes, repeat, then reanalyze only saved artifacts.

No downloads. --expect-pinned validates the historical macOS arm64 case; omit it
for a current build which may legitimately support more locales or change relations.
"""

import argparse
import platform
import subprocess
import sys
from pathlib import Path

from reproduce_case import file_sha256

from collationdelta.evidence import capture, compare, human_report
from collationdelta.formats import DeltaError, digest, dump, load, require

ROOT = Path(__file__).resolve().parents[1]


def identity(path):
    path = path.resolve(strict=True)
    checksum = file_sha256(path)
    return {"path": str(path), "sha256": checksum}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--browser", type=Path, required=True)
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--provenance",
        type=Path,
        help="installer provenance JSON, recorded separately from runtime observations",
    )
    parser.add_argument("--expect-pinned", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    adapter = ROOT / "src/collationdelta/adapters"
    commands = {
        "node": [str(args.node.resolve()), str(adapter / "node.mjs")],
        "browser": [
            str(args.node.resolve()),
            str(adapter / "browser.mjs"),
            "--toolchain",
            str(args.toolchain.resolve()),
            "--executable",
            str(args.browser.resolve()),
        ],
    }
    corpus = load(ROOT / "examples/browser/corpus.json")
    profiles, controls, reports, observations, captures = {}, {}, {}, {}, {}
    for locale in ("en", "is"):
        profile = load(ROOT / f"examples/browser/{locale}.profile.json")
        profiles[locale] = digest(profile)
        for label, command in commands.items():
            key = f"{label}-{locale}"
            first, repeat = (capture(corpus, profile, command) for _ in range(2))
            require(
                first["observation"] == repeat["observation"],
                f"{key}: observations changed within runtime",
            )
            dump(args.output / f"{key}.capture.json", first)
            dump(args.output / f"{key}-repeat.capture.json", repeat)
            report = compare(
                load(args.output / f"{key}.capture.json"),
                load(args.output / f"{key}-repeat.capture.json"),
            )
            expected = "STABLE" if first["coverage"]["complete"] else "INCOMPLETE"
            require(report["status"] == expected, f"{key}: invalid same-runtime control")
            dump(args.output / f"{key}-control.report.json", report)
            controls[key] = report["status"]
            observations[key] = {
                "status": first["observation"]["status"],
                "effective": first["observation"]["effective"],
                "runtime": first["observation"]["runtime"],
                "adapter": first["observation"]["adapter"],
            }
            captures[key] = {"first": first["digest"], "repeat": repeat["digest"]}
        report = compare(
            load(args.output / f"node-{locale}.capture.json"),
            load(args.output / f"browser-{locale}.capture.json"),
        )
        dump(args.output / f"{locale}.report.json", report)
        (args.output / f"{locale}.txt").write_text(human_report(report), encoding="utf-8")
        reports[locale] = {"status": report["status"], "finding_count": report["finding_count"]}
        if locale == "en":
            require(report["complete"], "acceptance control en must be supported by both runtimes")
        print(f"{locale}: {report['status']}, findings={report['finding_count']}")
    if args.expect_pinned:
        pins = load(ROOT / "scripts/browser-pins.json")
        for label, binary in (("node", args.node), ("browser", args.browser)):
            require(
                identity(binary)["sha256"] == pins["selected_executable_sha256"][label],
                f"{label}: selected executable hash does not match pin",
            )
        require(
            platform.system() == "Darwin" and platform.machine() == "arm64",
            "historical case is macOS arm64 only",
        )
        require(
            observations["node-is"]["runtime"]["node"] == "v24.21.0",
            "Node version does not match historical pin",
        )
        require(
            observations["node-is"]["runtime"]["icu"] == "78.3",
            "Node provider does not match historical pin",
        )
        runtime = observations["browser-is"]["runtime"]
        require(
            runtime["browser"]["version"] == pins["browser_version"],
            "browser version does not match historical pin",
        )
        require(
            runtime["automation"]["version"] == pins["automation_version"],
            "automation version does not match pin",
        )
        require(
            observations["node-is"]["status"] == "ok"
            and observations["node-is"]["effective"]["locale"] == "is",
            "historical Node is support differs",
        )
        require(
            observations["browser-is"]["status"] == "unsupported"
            and observations["browser-is"]["effective"]["locale"] == "en-US",
            "historical browser support outcome differs",
        )
        require(
            reports
            == {
                "en": {"status": "STABLE", "finding_count": 0},
                "is": {"status": "INCOMPLETE", "finding_count": 0},
            },
            "historical reports differ",
        )
    # A fresh Python process with no executable search path proves offline CLI analysis.
    import os

    for locale in ("en", "is"):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "collationdelta",
                "compare",
                str(args.output / f"node-{locale}.capture.json"),
                str(args.output / f"browser-{locale}.capture.json"),
                "--format",
                "json",
            ],
            capture_output=True,
            env={**os.environ, "PATH": "", "NODE_PATH": ""},
            timeout=30,
        )
        require(
            result.returncode
            == (
                0
                if reports[locale]["status"] == "STABLE"
                else 1
                if reports[locale]["status"] == "DRIFT"
                else 2
            ),
            f"{locale}: offline CLI failed: {result.stderr!r}",
        )
    dump(
        args.output / "experiment.json",
        {
            "experiment_version": 1,
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "architecture": platform.machine(),
                "python": platform.python_version(),
            },
            "executables": {"node": identity(args.node), "browser": identity(args.browser)},
            "installation_provenance": load(args.provenance) if args.provenance else None,
            "provenance_limitations": "Executable hashes identify selected files, not all shared libraries or locale data. Installer provenance is separate from runtime observations; a version or user agent is not authentication.",
            "inputs": {"corpus": digest(corpus), "profiles": profiles},
            "adapters": {
                name: identity(adapter / name) for name in ("node.mjs", "browser.mjs", "intl.mjs")
            },
            "commands": commands,
            "reproduction_argv": [sys.executable, *sys.argv],
            "observations": observations,
            "captures": captures,
            "repeatable_observations": {key: True for key in controls},
            "controls": controls,
            "offline_comparisons": reports,
            "offline_cli_without_path": True,
            "scope": "Finite eight-name corpus; strict native Intl only; no fallback comparisons, no conformance claim, no Workers or other browser distribution evidence.",
        },
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DeltaError, OSError, subprocess.SubprocessError) as exc:
        print(f"Experiment failed: {exc}", file=sys.stderr)
        raise SystemExit(3) from None
