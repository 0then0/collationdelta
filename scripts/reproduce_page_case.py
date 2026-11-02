"""Build the static page, exercise real browsers, import and compare downloaded evidence."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from build_browser_page import build

ROOT = Path(__file__).resolve().parents[1]


def reproduce(args):
    args.output.mkdir(parents=True, exist_ok=True)
    commands = []

    def run(command, valid=(0,), offline=False):
        commands.append(command)
        result = subprocess.run(
            command,
            cwd=ROOT,
            env={**os.environ, "PATH": "", "NODE_PATH": ""} if offline else None,
            text=True,
            capture_output=True,
        )
        if result.returncode not in valid:
            raise RuntimeError(f"{command}: {result.returncode}\n{result.stdout}\n{result.stderr}")
        print(result.stdout, end="")
        return result.stdout

    with tempfile.TemporaryDirectory(prefix="collationdelta-page-") as temporary:
        site = Path(temporary) / "collationdelta"
        build(site)
        run(
            [
                args.node,
                str(ROOT / "scripts/check_browser_page.mjs"),
                str(args.toolchain),
                str(site),
                str(args.output),
                *args.browsers,
            ]
        )
    cli = [sys.executable, "-m", "collationdelta"]
    for label in ("node", "node-repeat"):
        run(
            [
                *cli,
                "capture",
                "--corpus",
                str(ROOT / "examples/browser-page/corpus.json"),
                "--profile",
                str(ROOT / "examples/browser-page/profile.json"),
                "--output",
                str(args.output / f"{label}.capture.json"),
                "--",
                args.node,
                str(ROOT / "src/collationdelta/adapters/node.mjs"),
            ]
        )
    for browser in args.browsers:
        for suffix in ("", "-repeat", "-unsupported", "-files", "-after-cancel"):
            run(
                [
                    *cli,
                    "import-browser",
                    str(args.output / f"{browser}{suffix}.browser-export.json"),
                    "--output",
                    str(args.output / f"{browser}{suffix}.capture.json"),
                ],
                valid=(0, 2),
            )
        for label, old, new in (
            (f"{browser}-node", "node", browser),
            (f"{browser}-control", browser, f"{browser}-repeat"),
            (f"{browser}-unsupported-control", f"{browser}-unsupported", f"{browser}-unsupported"),
        ):
            run(
                [
                    *cli,
                    "compare",
                    str(args.output / f"{old}.capture.json"),
                    str(args.output / f"{new}.capture.json"),
                    "--json-output",
                    str(args.output / f"{label}.report.json"),
                ],
                valid=(0, 1, 2),
                offline=True,
            )
    run(
        [
            *cli,
            "compare",
            str(args.output / "node.capture.json"),
            str(args.output / "node-repeat.capture.json"),
            "--json-output",
            str(args.output / "node-control.report.json"),
        ],
        offline=True,
    )
    manifest = {
        "commands": commands,
        "node_version": run([args.node, "--version"]).strip(),
        "python_version": sys.version,
        "offline_compare_without_path": True,
        "sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [
                ROOT / "src/collationdelta/adapters/intl.mjs",
                ROOT / "examples/browser-page/corpus.json",
                ROOT / "examples/browser-page/profile.json",
            ]
        },
    }
    (args.output / "experiment.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", required=True)
    parser.add_argument("--toolchain", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--browsers", nargs="+", choices=("chromium", "firefox"), default=["chromium", "firefox"]
    )
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.toolchain = args.toolchain.resolve()
    reproduce(args)
