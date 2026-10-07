"""Validate a finite total preorder, including partial-observation contradictions."""

import math

from .formats import fields, require


def response(value, entries, *, normalized=False):
    fields(
        value,
        ("protocol_version", "status", "effective", "runtime", "adapter", "results"),
        ("reason",),
    )
    require(
        type(value["protocol_version"]) is int and value["protocol_version"] == 1,
        "unsupported adapter protocol version",
    )
    require(value["status"] in ("ok", "unsupported", "unresolved"), "invalid adapter status")
    if "reason" in value:
        require(
            isinstance(value["reason"], str) and value["reason"], "reason must be a nonempty string"
        )
    if value["status"] != "ok":
        require(
            isinstance(value.get("reason"), str) and value["reason"],
            "configuration failure requires reason",
        )
    require(
        value["effective"] is None or isinstance(value["effective"], dict),
        "invalid effective settings",
    )
    if value["status"] == "ok":
        require(
            isinstance(value["effective"], dict) and value["effective"],
            "ok requires effective settings",
        )
    for key in ("runtime", "adapter"):
        require(isinstance(value[key], dict) and value[key], f"{key} metadata required")
    require(isinstance(value["results"], list), "results must be an array")
    require(len(value["results"]) <= len(entries) ** 2, "too many results")
    if value["status"] == "unsupported":
        require(not value["results"], "unsupported configuration must not report comparisons")
    ids = {e["id"] for e in entries}
    seen, relations, results = set(), {}, []
    failed = 0
    for item in value["results"]:
        fields(item, ("left", "right", "status"), ("value", "reason"))
        require(
            isinstance(item["left"], str) and isinstance(item["right"], str),
            "pair IDs must be strings",
        )
        pair = item["left"], item["right"]
        require(pair[0] in ids and pair[1] in ids, "unrequested pair in results")
        require(pair not in seen, f"duplicate pair result: {pair!r}")
        seen.add(pair)
        status = item["status"]
        require(status in ("ok", "error", "unresolved"), "invalid pair status")
        result = dict(item)
        if status == "ok":
            require("value" in item and "reason" not in item, "ok requires value only")
            number = item["value"]
            require(type(number) in (int, float), "comparator result must be a finite number")
            require(
                type(number) is int or math.isfinite(number), "comparator result must be finite"
            )
            if normalized:
                require(
                    type(number) is int and number in (-1, 0, 1),
                    "capture relation must be integer sign",
                )
            result["value"] = (number > 0) - (number < 0)
            relations[pair] = result["value"]
        else:
            require(
                "value" not in item and isinstance(item.get("reason"), str) and item["reason"],
                "failed comparison requires reason and no value",
            )
            failed += 1
        results.append(result)
    require(
        not relations or bool(value["effective"]), "observed comparisons require effective settings"
    )
    consistency(entries, relations)
    complete = value["status"] == "ok" and len(relations) == len(entries) ** 2
    coverage = {
        "entries": len(entries),
        "expected_comparisons": len(entries) ** 2,
        "completed_comparisons": len(relations),
        "failed_comparisons": failed,
        "missing_comparisons": len(entries) ** 2 - len(seen),
        "complete": complete,
        "consistency": "verified" if complete else "consistent_partial",
    }
    clean = dict(value, results=sorted(results, key=lambda x: (x["left"], x["right"])))
    return clean, coverage, relations


def consistency(entries, relations):
    # Equality components, followed by strict-order DAG. A cycle or an edge
    # inside a component contradicts any extension to a total preorder.
    values = {entry["id"]: entry["value"] for entry in entries}
    parent = {i: i for i in values}
    rank = {i: 0 for i in values}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        a, b = find(a), find(b)
        if a == b:
            return
        if rank[a] < rank[b]:
            a, b = b, a
        parent[b] = a
        if rank[a] == rank[b]:
            rank[a] += 1

    representatives = {}
    for entry_id, value in values.items():
        if value in representatives:
            union(entry_id, representatives[value])
        else:
            representatives[value] = entry_id

    for (a, b), sign in relations.items():
        require(a != b or sign == 0, f"nonzero self comparison: {a!r}")
        require(values[a] != values[b] or sign == 0, "nonzero comparison of identical strings")
        reverse = relations.get((b, a))
        require(reverse is None or reverse == -sign, f"inconsistent reverse comparison: {(a, b)!r}")
        if sign == 0:
            union(a, b)
    graph = {find(i): set() for i in values}
    for (a, b), sign in relations.items():
        if sign:
            a, b = find(a), find(b)
            require(a != b, "strict relation contradicts equality transitivity")
            graph[a if sign < 0 else b].add(b if sign < 0 else a)
    indegree = {i: 0 for i in graph}
    for neighbors in graph.values():
        for node in neighbors:
            indegree[node] += 1
    ready = [i for i in graph if indegree[i] == 0]
    visited = 0
    while ready:
        node = ready.pop()
        visited += 1
        for neighbor in graph[node]:
            indegree[neighbor] -= 1
            if indegree[neighbor] == 0:
                ready.append(neighbor)
    require(visited == len(graph), "strict-order cycle contradicts transitivity")
