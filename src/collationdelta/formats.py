"""Strict JSON and finite Unicode inputs; no string transformations."""

import hashlib
import json
import math
import os
import tempfile
from decimal import Decimal, DecimalException
from pathlib import Path

MAX_ENTRIES = 256
MAX_FILE_BYTES = 32 * 1024 * 1024


class DeltaError(ValueError):
    """Invalid input, inconsistent evidence, or adapter transport failure."""


def require(condition, message):
    if not condition:
        raise DeltaError(message)


def fields(value, required, optional=()):
    require(isinstance(value, dict), "expected JSON object")
    require(set(required) <= value.keys(), f"missing fields: {set(required) - value.keys()}")
    require(value.keys() <= set(required) | set(optional), "unexpected object fields")


def scalar_strings(value):
    if isinstance(value, str):
        require(
            not any(0xD800 <= ord(c) <= 0xDFFF for c in value), "unpaired surrogate in JSON string"
        )
    elif isinstance(value, list):
        for item in value:
            scalar_strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            scalar_strings(key)
            scalar_strings(item)


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _constant(value):
    raise DeltaError(f"non-finite JSON number: {value}")


def _float(token):
    number = float(token)
    require(math.isfinite(number), "JSON number exceeds finite float range")
    require(number != 0 or Decimal(token).is_zero(), "nonzero JSON number underflows to zero")
    return number


def _ordinary_numbers(value):
    if isinstance(value, Decimal):
        return _float(str(value))
    if isinstance(value, list):
        return [_ordinary_numbers(item) for item in value]
    if isinstance(value, dict):
        return {key: _ordinary_numbers(item) for key, item in value.items()}
    return value


def decode(data, *, exact_results=False):
    try:
        value = json.loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=_object,
            parse_constant=_constant,
            parse_float=Decimal if exact_results else _float,
        )
        if exact_results:
            # Normalize comparator returns before conversion to binary floats.
            # Metadata and configuration keep the ordinary JSON representation.
            if isinstance(value, dict) and isinstance(value.get("results"), list):
                for item in value["results"]:
                    if isinstance(item, dict) and item.get("status") == "ok":
                        number = item.get("value")
                        if isinstance(number, Decimal):
                            require(number.is_finite(), "comparator result must be finite")
                            item["value"] = (number > 0) - (number < 0)
            value = _ordinary_numbers(value)
        scalar_strings(value)
        # Reject overflow such as 1e999 as well as explicit NaN/Infinity.
        canonical(value)
        return value
    except (UnicodeError, ValueError, RecursionError, DecimalException) as exc:
        raise DeltaError(f"invalid UTF-8/Unicode JSON: {exc}") from exc


def load(path):
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    require(len(data) <= MAX_FILE_BYTES, "JSON file exceeds 32 MiB limit")
    return decode(data)


def canonical(value):
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("ascii")


def digest(value):
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def dump(path, value):
    # ASCII escaping preserves scalar strings and keeps control characters inert.
    destination = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination.parent, prefix=".collationdelta-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            size = 0
            encoder = json.JSONEncoder(ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False)
            for chunk in encoder.iterencode(value):
                data = chunk.encode("ascii")
                size += len(data)
                require(size + 1 <= MAX_FILE_BYTES, "output exceeds 32 MiB file limit")
                stream.write(data)
            stream.write(b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def corpus(value):
    fields(value, ("version", "entries"))
    require(type(value["version"]) is int and value["version"] == 1, "unsupported corpus version")
    entries = value["entries"]
    require(
        isinstance(entries, list) and 1 <= len(entries) <= MAX_ENTRIES,
        f"corpus requires 1..{MAX_ENTRIES} entries",
    )
    ids = set()
    for entry in entries:
        fields(entry, ("id", "value"))
        require(isinstance(entry["id"], str) and entry["id"], "entry ID must be a nonempty string")
        require(isinstance(entry["value"], str), "entry value must be a string")
        scalar_strings(entry)
        require(entry["id"] not in ids, f"duplicate entry ID: {entry['id']!r}")
        ids.add(entry["id"])
    return value


def profile(value):
    fields(value, ("version", "contract", "locale", "options"))
    require(type(value["version"]) is int and value["version"] == 1, "unsupported profile version")
    for key in ("contract", "locale"):
        require(isinstance(value[key], str) and value[key], f"{key} must be a nonempty string")
    require(isinstance(value["options"], dict), "options must be an object")
    scalar_strings(value)
    return value
