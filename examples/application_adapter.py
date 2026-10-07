"""A runnable demonstration of wrapping an application comparator.

Replace application_compare and metadata with your application's actual code.
This example uses Python scalar lexicographic order, not linguistic collation.
"""

import json
import platform
import sys


def application_compare(a, b):
    return (a > b) - (a < b)


def main():
    request = json.load(sys.stdin)
    if request["protocol_version"] != 1:
        raise ValueError("unsupported protocol")
    profile = request["profile"]
    output = {
        "protocol_version": 1,
        "adapter": {"name": "demo-application", "version": "1"},
        "runtime": {"python": platform.python_version()},
        "effective": None,
        "results": [],
    }
    if profile != {
        "version": 1,
        "contract": "demo.scalar-order.v1",
        "locale": "und",
        "options": {},
    }:
        output.update(
            status="unsupported",
            reason="requires demo.scalar-order.v1, und, and no options",
        )
    else:
        output.update(status="ok", effective={"order": "Unicode scalar lexicographic"})
        for a in request["corpus"]["entries"]:
            for b in request["corpus"]["entries"]:
                try:
                    output["results"].append(
                        {
                            "left": a["id"],
                            "right": b["id"],
                            "status": "ok",
                            "value": application_compare(a["value"], b["value"]),
                        }
                    )
                except Exception as exc:
                    output["results"].append(
                        {
                            "left": a["id"],
                            "right": b["id"],
                            "status": "error",
                            "reason": str(exc),
                        }
                    )
    json.dump(output, sys.stdout, ensure_ascii=True, allow_nan=False)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
