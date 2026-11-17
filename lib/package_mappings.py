"""User-confirmed native package aliases scoped to the detected platform."""

import json

import discovery
import filesystem
import journal
import workflows


def path(state):
    return journal.state_dir(state, create=False) / "package-mappings.json"


def platform_key(info):
    return "/".join(
        str(info.get(field, "")) for field in ("id", "family", "arch", "manager")
    )


def load(state):
    target = path(state)
    data = workflows.read_json(target) if target.exists() or target.is_symlink() else {}
    if not isinstance(data, dict) or any(
        not isinstance(rows, dict) for rows in data.values()
    ):
        raise ValueError("Invalid saved package mappings")
    return data


def choices(info, state):
    rows = load(state).get(platform_key(info), {})
    return {
        discovery.validate_term(name): discovery.validate_term(row.get("actual"))
        for name, row in rows.items()
        if isinstance(row, dict) and row.get("source") == info.get("manager")
    }


def save(info, state, name, actual):
    discovery.validate_term(name)
    discovery.validate_term(actual)
    if name == "lerd" or name.startswith("ai-"):
        raise ValueError("Use the dedicated workflow for managed components")
    journal.state_dir(state)
    data = load(state)
    row = {
        "distribution": info["id"],
        "architecture": info["arch"],
        "manager": info["manager"],
        "source": info["manager"],
        "actual": actual,
    }
    data.setdefault(platform_key(info), {})[name] = row
    raw = (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()
    if len(raw) > workflows.MAX_JSON:
        raise ValueError("Package mappings exceed size limit")
    filesystem.atomic(path(state), raw)
    return row
