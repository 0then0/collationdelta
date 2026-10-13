#!/usr/bin/env python3
"""Explicit reproduction download for the pinned macOS arm64 experiment.

Verify both archive hashes before extraction. Does not change global installations.
Run npm ci separately for the optional automation toolchain.
"""

import argparse
import os
import platform
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from reproduce_case import file_sha256, obtain

from collationdelta.formats import DeltaError, dump, load, require

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    args = parser.parse_args()
    require(
        platform.system() == "Darwin" and platform.machine() == "arm64",
        "historical download pins cover macOS arm64 only; select an installed runtime for other environments",
    )
    cache = args.runtime_dir.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    node, node_provenance = obtain(
        "24.21.0", load(ROOT / "scripts/node-pins.json")["24.21.0"], cache
    )
    pins = load(ROOT / "scripts/browser-pins.json")
    pin = pins["archives"]["darwin-arm64"]
    archive = cache / "chrome-156.0.8078.4-mac-arm64.zip"
    if not archive.exists():
        temporary = archive.with_suffix(".download")
        try:
            print(f"Downloading {pin['url']}", file=sys.stderr)
            with (
                urllib.request.urlopen(pin["url"], timeout=60) as source,
                temporary.open("wb") as target,
            ):
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    checksum = file_sha256(archive)
    require(checksum == pin["sha256"], "browser archive checksum mismatch")
    # ditto preserves executable permissions and framework symlinks on macOS.
    # Reject absolute/traversing names before handing the verified archive to it.
    with zipfile.ZipFile(archive) as packed:
        require(
            all(
                not Path(info.filename).is_absolute() and ".." not in Path(info.filename).parts
                for info in packed.infolist()
            ),
            "unsafe browser archive paths",
        )
    browser_root = cache / "browser-156.0.8078.4"
    require(
        not browser_root.exists(),
        "browser extraction directory already exists; use a fresh runtime-dir or remove that disposable extraction explicitly",
    )
    subprocess.run(
        ["/usr/bin/ditto", "-x", "-k", str(archive), str(browser_root)], check=True, timeout=60
    )
    executable = browser_root / pin["executable"]
    require(os.access(executable, os.X_OK), "extracted browser is not executable")
    executable_hash = file_sha256(executable)
    dump(
        cache / "provenance.json",
        {
            "node": node_provenance,
            "browser": {
                "url": pin["url"],
                "archive_sha256": checksum,
                "executable_sha256": executable_hash,
                "distribution": pins["distribution"],
            },
            "source": "Pinned HTTPS archive downloads verified against repository SHA-256 pins; not a signature or browser authenticity guarantee.",
        },
    )
    print(f"Node: {node}\nBrowser: {executable}\nProvenance: {cache / 'provenance.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DeltaError, OSError, subprocess.SubprocessError) as exc:
        print(f"Runtime download failed: {exc}", file=sys.stderr)
        raise SystemExit(3) from None
