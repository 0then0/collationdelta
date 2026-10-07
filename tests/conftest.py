import json
import sys

import pytest

from collationdelta.evidence import capture


@pytest.fixture
def profile():
    return {"version": 1, "contract": "test.v1", "locale": "en", "options": {}}


@pytest.fixture
def make_capture(profile, tmp_path):
    def make(
        values=("a", "b", "c"), comparator=None, mutate=None, requested=None, raw_transform=None
    ):
        entries = [{"id": str(i), "value": value} for i, value in enumerate(values)]
        comparator = comparator or (lambda a, b: (a > b) - (a < b))
        reply = {
            "protocol_version": 1,
            "status": "ok",
            "effective": {"order": "test"},
            "runtime": {"synthetic": True, "version": "fixture"},
            "adapter": {"name": "test-fixture"},
            "results": [
                {
                    "left": a["id"],
                    "right": b["id"],
                    "status": "ok",
                    "value": comparator(a["value"], b["value"]),
                }
                for a in entries
                for b in entries
            ],
        }
        if mutate:
            mutate(reply)
        output = tmp_path / "adapter-output.json"
        raw = json.dumps(reply)
        output.write_text(raw_transform(raw) if raw_transform else raw, encoding="utf-8")
        code = "import sys,pathlib;sys.stdin.buffer.read();sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes())"
        return capture(
            {"version": 1, "entries": entries},
            requested or profile,
            [sys.executable, "-c", code, str(output)],
        )

    return make
