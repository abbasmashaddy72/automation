"""Merge Zed settings as data with private, conflict-checked rollback receipts."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
from urllib.parse import urlsplit

import filesystem
import journal

LIMIT = 256 * 1024
TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|//[^\r\n]*|/\*[\s\S]*?\*/|,\s*(?=[}\]])')
COMMENTS = re.compile(r'"(?:[^"\\]|\\.)*"|//[^\r\n]*|/\*[\s\S]*?\*/')


def decode(raw):
    text = raw.decode("utf-8")
    text = COMMENTS.sub(lambda m: " " if m[0].startswith("/") else m[0], text)
    text = TOKEN.sub(lambda m: "" if m[0].startswith(",") else m[0], text)

    def reject_constant(_):
        raise ValueError("Non-finite settings value")

    try:
        value = json.loads(
            text, object_pairs_hook=filesystem.unique, parse_constant=reject_constant
        )
    except RecursionError as exc:
        raise ValueError("Settings nested too deeply") from exc
    if not isinstance(value, dict):
        raise ValueError("Zed settings must be a JSONC object")
    return value


def read(path, *, missing=False, private=False, owned=True, limit=LIMIT):
    return filesystem.read_regular(
        path, limit=limit, missing=missing, private=private, owned=owned
    )


def digest(raw):
    return None if raw is None else hashlib.sha256(raw).hexdigest()


def connection_summary(data):
    providers = data.get("language_models", {})
    if not isinstance(providers, dict):
        return []
    agent = data.get("agent")
    model = agent.get("default_model", {}) if isinstance(agent, dict) else {}
    if isinstance(model, dict) and model.get("provider") == "llama.cpp":
        providers = {"llama.cpp": {}, **providers}
    result = []
    for provider, options in providers.items():
        if not isinstance(options, dict):
            continue
        url = options.get("api_url")
        if url is None and provider == "llama.cpp":
            url = "http://localhost:8080"
        if not isinstance(url, str):
            continue
        try:
            address = urlsplit(url)
            if (
                address.hostname
                and address.scheme in ("http", "https")
                and not address.username
                and not address.password
            ):
                result.append(
                    {
                        "provider": provider,
                        "host": address.hostname,
                        "port": address.port
                        or (443 if address.scheme == "https" else 80),
                        "scheme": address.scheme,
                        "can_test": address.scheme == "http"
                        and not address.username
                        and address.hostname in ("localhost", "127.0.0.1", "::1")
                        and address.path.rstrip("/") in ("", "/v1")
                        and not address.query
                        and not address.fragment,
                        "model": model.get("model")
                        if isinstance(model, dict)
                        and isinstance(model.get("model"), str)
                        and model.get("provider") == provider
                        else None,
                    }
                )
        except ValueError:
            continue
    return result


def merge(current, profile, prefix=()):
    changes = []
    for key, value in profile.items():
        path = (*prefix, key)
        if key not in current:
            current[key] = value
            changes.append(".".join(path))
        elif isinstance(current[key], dict) and isinstance(value, dict):
            changes.extend(merge(current[key], value, path))
    return changes


def backup(state, target, before, expected, *, announce=True):
    folder = journal.state_dir(state)
    name = "zed-" + uuid.uuid4().hex + ".json"
    record = {
        "schema": 1,
        "target": str(target),
        "before": None if before is None else base64.b64encode(before).decode("ascii"),
        "before_sha256": digest(before),
        "expected_sha256": expected,
    }
    import workflows

    workflows.write_json(folder / name, record, private=True)
    if announce:
        print("Zed backup:", name)
    return name


def telemetry(args, approve, *, state=""):
    operation = args.action or "status"
    if operation not in ("status", "disable", "restore") or args.value:
        raise ValueError("telemetry status|disable|restore")
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    if not config_home.is_absolute():
        raise ValueError("XDG_CONFIG_HOME must be absolute")
    target = filesystem.checked(config_home / "zed/settings.json")
    before = read(target, missing=True)
    data = decode(before) if before is not None else {}
    current = data.get("telemetry")
    if "telemetry" in data and not isinstance(current, dict):
        raise ValueError("The Zed telemetry setting must be an object")
    keys = ("diagnostics", "metrics")
    folder = journal.state_dir(state, create=False)
    receipt = folder / "zed-telemetry.json"
    saved = read(receipt, missing=True, private=True)
    print(
        json.dumps(
            {
                "application": "Zed",
                "settings_present": before is not None,
                **{
                    key: (current or {}).get(key, "application default") for key in keys
                },
                "restore_available": saved is not None,
            },
            indent=2,
        )
    )
    if operation == "status" or args.dry_run:
        return 0
    if operation == "disable" and all(
        (current or {}).get(key) is False for key in keys
    ):
        return 0
    if before is None:
        raise ValueError("Create Zed settings before changing telemetry")
    if saved is not None:
        record = json.loads(saved, object_pairs_hook=filesystem.unique)
        if (
            not isinstance(record, dict)
            or record.get("target") != str(target)
            or not isinstance(record.get("before"), dict)
            or set(record["before"]) - set(keys)
            or type(record.get("had_section")) is not bool
        ):
            raise ValueError("Invalid Zed telemetry receipt")
    if operation == "restore":
        if saved is None:
            raise ValueError("No recorded Zed telemetry change")
        if {
            key: current[key] for key in keys if current is not None and key in current
        } == record["before"]:
            if not approve(args, "Clear the completed Zed telemetry receipt?"):
                return 4
            if read(target) != before or read(receipt, private=True) != saved:
                raise ValueError("Telemetry settings or receipt changed during review")
            receipt.unlink()
            return 0
        if any((current or {}).get(key) is not False for key in keys):
            raise ValueError("Zed telemetry changed after the recorded operation")
    elif (
        saved is not None
        and {
            key: current[key] for key in keys if current is not None and key in current
        }
        != record["before"]
    ):
        raise ValueError(
            "An earlier telemetry change is recorded. Review or restore it first"
        )
    if not approve(
        args, f"{operation.capitalize()} the listed Zed telemetry settings?"
    ):
        return 4
    if read(target) != before or read(receipt, missing=True, private=True) != saved:
        raise ValueError("Telemetry settings or receipt changed during review")
    flags = data.setdefault("telemetry", {})
    if operation == "disable":
        from workflows import write_json

        if saved is None:
            journal.state_dir(state)
            write_json(
                receipt,
                {
                    "target": str(target),
                    "before": {k: flags[k] for k in keys if k in flags},
                    "had_section": current is not None,
                },
                private=True,
            )
        flags.update(dict.fromkeys(keys, False))
    else:
        for key in keys:
            flags.pop(key, None)
            if key in record["before"]:
                flags[key] = record["before"][key]
        if not flags and not record.get("had_section"):
            data.pop("telemetry")
    filesystem.atomic(
        target,
        (
            json.dumps(data, ensure_ascii=True, allow_nan=False, indent=2) + "\n"
        ).encode(),
    )
    if operation == "restore":
        receipt.unlink()
    print(f"Zed telemetry {operation} completed.")
    return 0


def settings_path():
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    if not config_home.is_absolute():
        raise ValueError("XDG_CONFIG_HOME must be absolute")
    return filesystem.checked(config_home / "zed/settings.json")


def overlay(target, updates):
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            overlay(target[key], value)
        else:
            target[key] = value


def main(args, approve, *, root, state=""):
    operation = args.action or "status"
    if operation not in (
        "status",
        "show",
        "plan",
        "apply",
        "override",
        "replace",
        "backup",
        "restore",
    ):
        raise ValueError(
            "zed status|show|plan [PROFILE]|apply [PROFILE]|override PROFILE|replace PROFILE|backup|restore BACKUP_ID"
        )
    if args.value and operation not in (
        "plan",
        "apply",
        "override",
        "replace",
        "restore",
    ):
        raise ValueError("Unexpected Zed argument")
    target = settings_path()
    before = read(target, missing=True)
    if operation == "show":
        print(
            before.decode("utf-8")
            if before is not None
            else "No Zed settings file exists."
        )
        return 0
    if operation == "status":
        current = decode(before) if before is not None else {}
        print(
            json.dumps(
                {
                    "settings_present": before is not None,
                    "settings_valid": True,
                    "sha256": digest(before),
                    "connections": connection_summary(current),
                }
            )
        )
        return 0
    if operation in ("plan", "apply", "override", "replace"):
        version = digest(before) or "missing"
        expected = getattr(args, "current_sha256", None)
        if expected is not None and expected != version:
            raise ValueError("Zed settings changed since the preview")
        if operation in ("override", "replace") and not args.value:
            raise ValueError("Choose a JSONC settings file")
        profile = (
            Path(args.value)
            if args.value
            else root / "config/zed-vscode-long-context.json"
        )
        original = decode(before) if before is not None else {}
        incoming = decode(read(profile, owned=bool(args.value)))
        data = json.loads(json.dumps(original))
        if operation == "override":
            overlay(data, incoming)
        elif operation == "replace":
            data = incoming
        else:
            merge(data, incoming)
        added, removed, changed = [], [], []
        comparable_paths = {
            "vim_mode",
            "tab_size",
            "ui_font_size",
            "buffer_font_size",
            "terminal.font_size",
            "telemetry.metrics",
            "telemetry.diagnostics",
        }
        comparisons = {}

        def compare(old, new, prefix=""):
            for key in sorted(old.keys() | new.keys()):
                path = prefix + key
                if path in comparable_paths:
                    old_value, new_value = old.get(key), new.get(key)
                    if all(
                        type(value) in (bool, int, float, type(None))
                        for value in (old_value, new_value)
                    ) and (
                        old_value != new_value or type(old_value) is not type(new_value)
                    ):
                        comparisons[path] = [old_value, new_value]
                if key not in old:
                    added.append(path)
                elif key not in new:
                    removed.append(path)
                elif isinstance(old[key], dict) and isinstance(new[key], dict):
                    compare(old[key], new[key], path + ".")
                elif old[key] != new[key] or type(old[key]) is not type(new[key]):
                    changed.append(path)

        compare(original, data)
        for key, kind in {
            "telemetry": dict,
            "agent": dict,
            "language_models": dict,
            "vim_mode": bool,
            "tab_size": int,
        }.items():
            if key in data and type(data[key]) is not kind:
                raise ValueError(f"Invalid Zed setting type: {key}")
        if any(
            key in data.get("telemetry", {})
            and type(data["telemetry"][key]) is not bool
            for key in ("metrics", "diagnostics")
        ):
            raise ValueError("Zed telemetry metrics and diagnostics must be boolean")
        keys = added + removed + changed
        if any(
            key
            in (
                "language_models",
                "language_models.llama.cpp",
                "language_models.llama.cpp.api_url",
            )
            for key in added + changed
        ):
            llama = data.get("language_models", {}).get("llama.cpp", {})
            if not isinstance(llama, dict):
                raise ValueError("Zed llama.cpp settings must be an object")
            if "api_url" in llama:
                url = llama["api_url"]
                try:
                    if not isinstance(url, str) or any(
                        character.isspace() for character in url
                    ):
                        raise ValueError
                    address = urlsplit(url)
                    if (
                        address.scheme not in ("http", "https")
                        or not address.hostname
                        or address.username is not None
                        or address.password is not None
                        or address.query
                        or address.fragment
                        or address.port == 0
                    ):
                        raise ValueError
                except ValueError:
                    raise ValueError(
                        "Zed llama.cpp API URL needs an HTTP(S) host and an optional port"
                    ) from None
        try:
            after = (
                json.dumps(data, ensure_ascii=True, allow_nan=False, indent=2) + "\n"
            ).encode()
        except RecursionError as exc:
            raise ValueError("Settings nested too deeply") from exc
        if len(after) > LIMIT:
            raise ValueError("Merged settings exceed size limit")
        print(
            json.dumps(
                {
                    "add": added,
                    "change": changed,
                    "remove": removed,
                    "compare": comparisons,
                    "mode": operation,
                    "version": version,
                    "preserve_existing_values": operation in ("apply", "plan"),
                    "connections_before": connection_summary(original),
                    "connections_after": connection_summary(data),
                },
                indent=2,
            )
        )
        if operation == "plan" or args.dry_run or not keys:
            return 0
        if not approve(
            args, "Apply the listed Zed settings changes and back up the current file?"
        ):
            return 4
        if read(target, missing=True) != before:
            raise ValueError("Zed settings changed during review; retry")
        backup(state, target, before, digest(after))
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if read(target, missing=True) != before:
            raise ValueError("Zed settings changed before write; retry")
        filesystem.atomic(target, after)
        return 0
    if operation == "backup":
        if before is None:
            raise ValueError("No Zed settings to back up")
        if args.dry_run:
            print("Dry run: would create a private Zed backup.")
            return 0
        if not approve(args, "Save a private copy of Zed settings?"):
            return 4
        if read(target, missing=True) != before:
            raise ValueError("Zed settings changed during review; retry")
        backup(state, target, before, digest(before))
        return 0
    if not re.fullmatch(r"zed-[0-9a-f]{32}\.json", args.value or ""):
        raise ValueError("Select an exact Zed backup ID")
    receipt = read(
        journal.state_dir(state, create=False) / args.value,
        private=True,
        limit=2 * LIMIT,
    )
    record = json.loads(receipt, object_pairs_hook=filesystem.unique)
    if (
        not isinstance(record, dict)
        or set(record)
        != {"schema", "target", "before", "before_sha256", "expected_sha256"}
        or record.get("schema") != 1
        or record.get("target") != str(target)
        or (record["before"] is not None and not isinstance(record["before"], str))
    ):
        raise ValueError("Zed backup belongs to another settings path")
    encoded = record["before"]
    original = None if encoded is None else base64.b64decode(encoded, validate=True)
    if digest(original) != record["before_sha256"]:
        raise ValueError("Zed backup checksum mismatch")
    if before == original:
        print("Zed settings already match this backup.")
        return 0
    expected = getattr(args, "current_sha256", None) or record["expected_sha256"]
    if digest(before) != expected:
        raise ValueError(
            "Zed settings changed since backup; review current settings and use --current-sha256"
        )
    if args.dry_run:
        print("Dry run: would restore the selected Zed backup.")
        return 0
    if not approve(args, "Restore this Zed backup after backing up current settings?"):
        return 4
    if read(target, missing=True) != before:
        raise ValueError("Zed settings changed during review; retry")
    backup(state, target, before, digest(original))
    if read(target, missing=True) != before:
        raise ValueError("Zed settings changed before restore; retry")
    if original is None:
        target.unlink()
    else:
        filesystem.atomic(target, original)
    return 0
