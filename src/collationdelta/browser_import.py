"""Strict, offline acceptance boundary for browser-page exports (no execution)."""

import datetime
import json

from . import __version__
from .formats import canonical, corpus, digest, fields, profile, require, scalar_strings
from .observations import response

INPUT_LIMIT = 1024 * 1024
EXPORT_LIMIT = 16 * 1024 * 1024
OPTIONS = {
    "usage": ("sort", "search"),
    "sensitivity": ("base", "accent", "case", "variant"),
    "caseFirst": ("upper", "lower", "false"),
    "numeric": bool,
    "ignorePunctuation": bool,
    "collation": str,
}


def timestamp(value):
    require(isinstance(value, str) and len(value) <= 64, "invalid browser timestamp")
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        require(False, "invalid browser timestamp")
    require(parsed.utcoffset() == datetime.timedelta(0), "browser timestamp must be UTC")


def metadata(value):
    fields(
        value,
        (
            "page_version",
            "captured_at",
            "execution_context",
            "user_agent",
            "navigator_platform",
            "caller_labels",
        ),
    )
    require(
        type(value["page_version"]) is int and value["page_version"] == 1,
        "unsupported page version",
    )
    timestamp(value["captured_at"])
    require(
        canonical(value["execution_context"])
        == canonical({"kind": "dedicated-worker", "has_document": False, "has_process": False}),
        "invalid browser execution context",
    )
    for key in ("user_agent", "navigator_platform"):
        require(isinstance(value[key], str) and len(value[key]) <= 4096, f"invalid browser {key}")
    fields(value["caller_labels"], ("label",))
    require(
        isinstance(value["caller_labels"]["label"], str)
        and len(value["caller_labels"]["label"]) <= 256,
        "invalid caller label",
    )


def intl_observation(observed, requested):
    """Validate claims, not runtime authenticity; never negotiate using the importing host."""
    fields(observed["adapter"], ("contract",))
    require(observed["adapter"]["contract"] == "intl.collator.v1", "invalid browser contract")
    require(requested["contract"] == "intl.collator.v1", "browser export requires intl.collator.v1")
    fields(observed["runtime"], ("intl",))
    intl = observed["runtime"]["intl"]
    fields(intl, ("canonical_locale", "supported_locales", "resolved_options"))
    locale, supported, resolved = (
        intl[k] for k in ("canonical_locale", "supported_locales", "resolved_options")
    )
    require(
        locale is None or (isinstance(locale, str) and bool(locale)), "invalid canonical locale"
    )
    require(
        supported is None or supported == [] or (locale is not None and supported == [locale]),
        "invalid supported locales",
    )
    require(canonical(resolved) == canonical(observed["effective"]), "resolved/effective mismatch")
    require(
        locale is not None or (supported is None and resolved is None), "locale metadata mismatch"
    )
    require(
        resolved is None or supported is not None, "resolved settings require locale negotiation"
    )
    if resolved is not None:
        fields(resolved, ("locale", *OPTIONS))
        require(
            isinstance(resolved["locale"], str) and resolved["locale"], "invalid resolved locale"
        )
        for key, rule in OPTIONS.items():
            setting = resolved[key]
            require(
                (type(setting) is rule and (rule is not str or bool(setting)))
                if isinstance(rule, type)
                else setting in rule,
                f"invalid resolved {key}",
            )
    if observed["status"] == "ok":
        require(
            locale is not None and supported == [locale] and resolved is not None,
            "ok requires supported locale and resolved settings",
        )
        expected = dict(requested["options"])
        # Check original requests as well as recorded canonical requests. A changed
        # canonical claim must not silently erase co/kn/kf from the profile.
        for source in (requested["locale"], locale):
            subtags = source.lower().split("-x-", 1)[0].split("-u-", 1)
            extensions = {}
            if len(subtags) == 2:
                parts = iter(subtags[1].split("-"))
                key = None
                for part in parts:
                    if len(part) == 1:
                        break
                    if len(part) == 2:
                        key = part
                        extensions[key] = []
                    elif key is not None:
                        extensions[key].append(part)
                extensions = {k: "-".join(v) or "true" for k, v in extensions.items()}
            for extension, option in (("co", "collation"), ("kf", "caseFirst"), ("kn", "numeric")):
                if option not in requested["options"] and extension in extensions:
                    setting = extensions[extension]
                    if option == "numeric":
                        require(
                            setting in ("true", "false"), "invalid kn request in ok observation"
                        )
                        setting = setting == "true"
                    expected[option] = setting
            for key, setting in expected.items():
                require(
                    key in resolved and canonical(setting) == canonical(resolved[key]),
                    f"requested {key} did not resolve",
                )
        for key, setting in expected.items():
            require(key in OPTIONS, "unsupported option in ok observation")
            require(
                canonical(setting) == canonical(resolved[key]), f"requested {key} did not resolve"
            )
    else:
        require(observed["status"] == "unsupported", "invalid browser observation status")


def validate_export(value):
    fields(
        value,
        ("browser_export_version", "corpus", "requested", "observation", "coverage", "metadata"),
    )
    require(
        type(value["browser_export_version"]) is int and value["browser_export_version"] == 1,
        "unsupported browser export version",
    )
    scalar_strings(value)
    corpus(value["corpus"])
    profile(value["requested"])
    for key in ("corpus", "requested"):
        require(
            len(json.dumps(value[key], ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            <= INPUT_LIMIT,
            "browser input exceeds 1 MiB limit",
        )
    metadata(value["metadata"])
    clean, coverage, relations = response(
        value["observation"], value["corpus"]["entries"], normalized=True
    )
    intl_observation(clean, value["requested"])
    require(
        canonical(coverage) == canonical(value["coverage"]),
        "browser coverage does not match observations",
    )
    require(
        clean["status"] != "ok" or coverage["missing_comparisons"] == 0,
        "browser export must include all ordered pairs",
    )
    return clean, coverage, relations


def import_browser(value):
    observed, coverage, _ = validate_export(value)
    payload = {
        "format_version": 2,
        "corpus": value["corpus"],
        "requested": value["requested"],
        "observation": observed,
        "coverage": coverage,
        "provenance": {
            "version": 1,
            "kind": "browser-export",
            "browser_export_version": 1,
            "metadata": value["metadata"],
            "importer": {
                "tool_version": __version__,
                "imported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
        },
    }
    return dict(payload, digest=digest(payload))


def validate_provenance(value):
    fields(value, ("version", "kind", "browser_export_version", "metadata", "importer"))
    require(
        type(value["version"]) is int and value["version"] == 1, "unsupported provenance version"
    )
    require(value["kind"] == "browser-export", "unsupported provenance kind")
    fields(value["importer"], ("tool_version", "imported_at"))
    require(
        isinstance(value["importer"]["tool_version"], str) and value["importer"]["tool_version"],
        "invalid importer version",
    )
    timestamp(value["importer"]["imported_at"])
