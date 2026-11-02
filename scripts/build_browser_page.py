"""Build dependency-free, relocatable static assets; never duplicate Intl semantics."""

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "style.css", "app.mjs", "input.mjs", "worker.mjs"):
        shutil.copyfile(ROOT / "web" / name, destination / name)
    shutil.copyfile(ROOT / "src/collationdelta/adapters/intl.mjs", destination / "intl.mjs")
    (destination / ".nojekyll").touch()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/browser-page")
    build(parser.parse_args().output)
