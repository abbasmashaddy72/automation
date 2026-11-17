"""Replay exact native choices from an exported plan on the same platform."""

import workflows


def selection(value, info):
    rows = workflows.validate_plan(value)
    host = value.get("host")
    keys = ("id", "family", "arch", "manager")
    if not isinstance(host, dict) or any(
        not info.get(k) or host.get(k) != info[k] for k in keys
    ):
        raise ValueError(
            "Package plan must match this distribution, architecture and manager"
        )
    chosen = {}
    for row in rows:
        if (
            row["status"] not in ("installed", "available")
            or row["source"] != info["manager"]
            or not workflows.NAME_PACKAGE.fullmatch(row.get("actual") or "")
        ):
            raise ValueError(
                "Replay requires a plan containing only exact native packages"
            )
        if row["name"] == "lerd" or row["name"].startswith("ai-"):
            raise ValueError("Use the dedicated workflow for managed applications")
        if row["name"] in chosen:
            raise ValueError("Duplicate package in replay plan")
        chosen[row["name"]] = row["actual"]
    if not chosen:
        raise ValueError("Package replay plan is empty")
    return chosen
