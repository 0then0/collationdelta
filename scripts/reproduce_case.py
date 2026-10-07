#!/usr/bin/env python3
"""Explicitly download pinned official binaries and reproduce the upgrade case.

This standalone experiment is not runtime management inside CollationDelta.
It verifies archive checksums and actual runtime/provider metadata before use.
"""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

from collationdelta.evidence import capture, compare, human_report
from collationdelta.formats import DeltaError, dump, load, require

ROOT = Path(__file__).resolve().parents[1]


def obtain(version, pin, cache):
    system = {"Darwin": "darwin", "Linux": "linux"}.get(platform.system())
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64"}.get(platform.machine())
    suffix = "tar.gz" if system == "darwin" else "tar.xz"
    target = f"{system}-{arch}.{suffix}"
    require(target in pin["archives"], f"no pinned archive for {target}")
    name = f"node-v{version}-{target}"
    archive = cache / name
    url = f"https://nodejs.org/dist/v{version}/{name}"
    if not archive.exists():
        print(f"Downloading {url}", file=sys.stderr)
        temporary = archive.with_suffix(archive.suffix + ".download")
        try:
            with (
                urllib.request.urlopen(url, timeout=60) as source,
                temporary.open("wb") as destination,
            ):
                while chunk := source.read(1024 * 1024):
                    destination.write(chunk)
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    with archive.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    require(checksum == pin["archives"][target], f"archive checksum mismatch: {archive}")
    # Extract each verified archive again: never trust a previously altered tree.
    with tarfile.open(archive) as packed:
        packed.extractall(cache, filter="data")
    binary = cache / f"node-v{version}-{system}-{arch}" / "bin" / "node"
    return binary, {"url": url, "sha256": checksum, "archive": name}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-dir", type=Path, required=True, help="disposable download/extraction directory"
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="evidence directory; matching files are overwritten",
    )
    args = parser.parse_args()
    args.runtime_dir.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)
    pins = load(ROOT / "scripts/node-pins.json")
    adapter = ROOT / "src/collationdelta/adapters/node.mjs"
    corpus, profile = load(ROOT / "examples/corpus.json"), load(ROOT / "examples/profile.json")
    applications, binaries = {}, {}
    for label, version in (("old", "18.20.8"), ("new", "24.21.0")):
        binary, identity = obtain(version, pins[version], args.runtime_dir)
        binaries[label] = identity
        first = capture(corpus, profile, [str(binary), str(adapter)])
        observed = first["observation"]["runtime"]
        require(
            all(observed[k] == v for k, v in pins[version]["runtime"].items()),
            f"actual runtime metadata does not match pin: {observed}",
        )
        second = capture(corpus, profile, [str(binary), str(adapter)])
        require(
            first["observation"] == second["observation"], "capture observations not repeatable"
        )
        dump(args.output / f"{label}.capture.json", first)
        dump(args.output / f"{label}-repeat.capture.json", second)
        control = compare(
            load(args.output / f"{label}.capture.json"),
            load(args.output / f"{label}-repeat.capture.json"),
        )
        require(control["status"] == "STABLE", "same-runtime control not stable")
        dump(args.output / f"{label}-control.report.json", control)
        process = subprocess.run(
            [str(binary), str(ROOT / "examples/application.mjs")],
            capture_output=True,
            check=True,
            timeout=30,
        )
        applications[label] = json.loads(process.stdout)
    # Use only deserialized artifacts, not the processes or in-memory captures.
    report = compare(load(args.output / "old.capture.json"), load(args.output / "new.capture.json"))
    require(
        report["status"] == "DRIFT" and report["finding_count"] == 2,
        "unexpected historical findings",
    )
    require(
        {f["kind"] for f in report["findings"]} == {"equality_merge", "order_reversal"},
        "missing drift kind",
    )
    require(
        applications["old"]["sorted"] == applications["new"]["sorted"] == ["₨", "Rs"],
        "snapshot changed",
    )
    require(
        len(applications["old"]["distinct"]) == 2 and len(applications["new"]["distinct"]) == 1,
        "demonstration application output did not change",
    )
    dump(args.output / "upgrade.report.json", report)
    (args.output / "upgrade.txt").write_text(human_report(report), encoding="utf-8")
    dump(
        args.output / "experiment.json",
        {
            "experiment_version": 1,
            "binaries": binaries,
            "applications": applications,
            "repeatable_observations": {"old": True, "new": True},
            "controls": {"old": "STABLE", "new": "STABLE"},
            "offline_comparison": "DRIFT",
            "scope": "whole Node runtime upgrade; demonstration application, not production incident",
        },
    )
    print(human_report(report), end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DeltaError, OSError, subprocess.SubprocessError) as exc:
        print(f"Experiment failed: {exc}", file=sys.stderr)
        raise SystemExit(3) from None
