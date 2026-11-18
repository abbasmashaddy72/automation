"""Versioned, explicitly reviewed backups of supported setup preferences."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import re
import uuid
from urllib.parse import urlsplit

import configuration
import discovery
import filesystem
import journal
import package_mappings
import workflows
import zed_settings

SCHEMA = 2
LIMIT = 512 * 1024
SETTINGS = workflows.PROFILE_KEYS | configuration.EDITABLE.keys()
SECTIONS = ("toolkit", "setup", "mappings", "zed")

PORT = (1024, 65535)
PATH = "absolute-path"
LABEL = re.compile(r"[\w .+()-]{1,128}")
TOKEN = re.compile(r"[A-Za-z0-9_.-]{1,128}")
AI = {
    "location": {"local", "ssh"},
    "backend": {"auto", "cpu", "cuda", "hip", "vulkan"},
    "install_mode": {"install", "update", "reinstall"},
    "store_choice": "storage-choice",
    "data_root": PATH,
    "model": PATH,
    "model_mode": {"existing", "download"},
    "recommendation": TOKEN,
    "port": PORT,
    "test_port": PORT,
    "chatPort": PORT,
    "webuiPort": PORT,
    "context_tokens": (128, 1048576),
    "gpu_layers": (0, 999),
    "stage": bool,
}
REMOTE = {
    "host": re.compile(r"[A-Za-z0-9][A-Za-z0-9.:-]{0,252}"),
    "user": re.compile(r"[a-zA-Z_][a-zA-Z0-9_-]{0,63}"),
    "directory": PATH,
    **{
        key: AI[key]
        for key in ("data_root", "model", "port", "test_port", "context_tokens")
    },
}
ZED = {
    "theme": {"mode": {"system", "light", "dark"}, "light": LABEL, "dark": LABEL},
    "icon_theme": LABEL,
    "base_keymap": LABEL,
    "vim_mode": bool,
    "ui_font_size": (6, 96),
    "buffer_font_size": (6, 96),
    "buffer_font_family": LABEL,
    "tab_size": range(1, 17),
    "hard_tabs": bool,
    "format_on_save": {"on", "off"},
    "autosave": {"off", "on_focus_change", "on_window_change"},
    "soft_wrap": {"none", "editor_width", "preferred_line_length", "bounded"},
    "terminal": {"font_size": (6, 96), "font_family": LABEL},
    "telemetry": {"diagnostics": bool, "metrics": bool},
    "language_models": {"llama.cpp": {"api_url": "endpoint", "auto_discover": bool}},
}


def encode(value):
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode()


def parse_document(text):
    if not isinstance(text, str):
        raise ValueError("Choose a profile JSON file up to 512 KiB")

    def non_finite(_):
        raise ValueError("Profile JSON numbers must be finite")

    def number(raw):
        value = float(raw)
        if not math.isfinite(value):
            non_finite(raw)
        return value

    try:
        if len(text.encode("utf-8")) > LIMIT:
            raise ValueError("Choose a profile JSON file up to 512 KiB")
        document = json.loads(
            text,
            object_pairs_hook=filesystem.unique,
            parse_constant=non_finite,
            parse_float=number,
        )
        # Check decoded characters too, including escaped unpaired surrogates.
        json.dumps(document, ensure_ascii=False).encode("utf-8")
        return document
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid JSON at line {error.lineno}, column {error.colno}. {error.msg}."
        ) from None
    except UnicodeError:
        raise ValueError("Profile JSON contains invalid Unicode") from None
    except RecursionError:
        raise ValueError("Profile JSON is nested too deeply") from None


def validate_document(value):
    if len(encode(value)) > LIMIT:
        raise ValueError("Profile exceeds the 512 KiB limit")


def object_fields(value, allowed, path):
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    unknown = set(value) - set(allowed)
    if unknown:
        names = ", ".join(sorted(key for key in unknown if TOKEN.fullmatch(key))[:8])
        raise ValueError(
            f"Unsupported fields in {path}: {names or 'unrecognized names'}. "
            "Review and edit a copy of the profile to continue."
        )
    return value


def valid_path(value):
    return (
        isinstance(value, str)
        and 0 < len(value) <= 4096
        and value.startswith("/")
        and ".." not in Path(value).parts
        and all(ord(char) >= 32 for char in value)
    )


def valid_endpoint(value):
    if (
        not isinstance(value, str)
        or len(value) > 256
        or any(c.isspace() for c in value)
    ):
        return False
    try:
        url = urlsplit(value)
        return (
            url.scheme in {"http", "https"}
            and bool(url.hostname)
            and url.username is None
            and url.password is None
            and not url.query
            and not url.fragment
            and url.path in {"", "/", "/v1", "/v1/"}
            and url.port != 0
        )
    except ValueError:
        return False


def value_matches(value, rule):
    if rule is bool:
        return type(value) is bool
    if rule == PATH:
        return valid_path(value)
    if rule == "storage-choice":
        return value == "custom" or valid_path(value)
    if rule == "endpoint":
        return valid_endpoint(value)
    if isinstance(rule, range):
        return type(value) is int and value in rule
    if isinstance(rule, tuple):
        return type(value) in (int, float) and rule[0] <= value <= rule[1]
    if isinstance(rule, set):
        return isinstance(value, str) and value in rule
    return isinstance(value, str) and bool(rule.fullmatch(value))


def fields(value, rules, path, *, select=False, optional=False):
    """Project only supported values on export and reject unknown values on import."""
    if select and not isinstance(value, dict):
        return {}
    data = value if select else object_fields(value, rules, path)
    result = {}
    for key, rule in rules.items():
        if key not in data:
            continue
        item = data[key]
        field = f"{path}.{key}"
        if isinstance(rule, dict):
            nested = fields(item, rule, field, select=select)
            if nested or not select:
                result[key] = nested
        elif (optional and rule is not bool and item in (None, "")) or (
            value_matches(item, rule)
            and (not optional or not isinstance(rule, tuple) or type(item) is int)
        ):
            result[key] = item
        elif not select:
            raise ValueError(f"Invalid value for {field}")
    return result


def draft(value, *, export=False):
    rules = {
        "selected": None,
        "projects": bool,
        "projectPhpSample": bool,
        "zed": bool,
        "ai": AI,
        "remote": REMOTE,
    }
    if not isinstance(value, dict):
        raise ValueError("Dashboard selections must be an object")
    if not export:
        object_fields(value, rules, "setup")
    result = fields(
        value, {k: v for k, v in rules.items() if v is bool}, "setup", select=True
    )
    for key, rule in (("ai", AI), ("remote", REMOTE)):
        if key in value:
            result[key] = fields(
                value[key], rule, f"setup.{key}", select=export, optional=True
            )
    for key in ("projects", "projectPhpSample", "zed"):
        if key in value and key not in result:
            raise ValueError(f"Invalid value for setup.{key}")
    if "selected" in value:
        names = value["selected"]
        if not isinstance(names, list) or len(names) > 1024:
            raise ValueError("setup.selected must be a list of up to 1024 packages")
        result["selected"] = list(
            dict.fromkeys(discovery.validate_term(name) for name in names)
        )
    return result


def mapping_rows(value):
    if not isinstance(value, dict) or len(value) > 128:
        raise ValueError("Package mappings must be grouped by platform")
    for platform, rows in value.items():
        parts = platform.split("/")
        if len(parts) != 4 or any(not TOKEN.fullmatch(part) for part in parts):
            raise ValueError("Invalid package mapping platform")
        distro, _, arch, manager = parts
        if manager not in {"apt-get", "pacman", "dnf", "zypper", "apk"}:
            raise ValueError("Unsupported package mapping manager")
        if not isinstance(rows, dict) or len(rows) > 1024:
            raise ValueError("Invalid package mapping rows")
        for name, row in rows.items():
            discovery.validate_term(name)
            if name == "lerd" or name.startswith("ai-"):
                raise ValueError("Managed components cannot be package mappings")
            object_fields(
                row,
                {"distribution", "architecture", "manager", "source", "actual"},
                "mapping",
            )
            if [
                row.get(key)
                for key in ("distribution", "architecture", "manager", "source")
            ] != [distro, arch, manager, manager]:
                raise ValueError("Package mapping source does not match its platform")
            discovery.validate_term(row.get("actual"))
    return value


def export_profile(root, state, selected, browser, parse, validate):
    if (
        not isinstance(selected, list)
        or not selected
        or any(key not in SECTIONS for key in selected)
    ):
        raise ValueError("Select at least one supported profile section")
    sections, notices = {}, []
    if "toolkit" in selected:
        target = filesystem.checked(root / ".env")
        filesystem.read_regular(target, missing=True, limit=65536)
        sections["toolkit"] = {
            key: value for key, value in parse(target).items() if key in SETTINGS
        }
    if "setup" in selected:
        setup = draft(browser, export=True)
        sections["setup"] = setup
        if any(browser.get(key) != setup.get(key) for key in ("ai", "remote")):
            notices.append(
                "The export skipped outdated or unsupported Local AI and SSH settings."
            )
        if setup.get("ai", {}).get("model_mode") == "download":
            notices.append(
                "Custom download links and verification details are excluded. Review the model download again."
            )
    if "mappings" in selected:
        sections["mappings"] = mapping_rows(package_mappings.load(state))
    if "zed" in selected:
        before = zed_settings.read(zed_settings.settings_path(), missing=True)
        data = zed_settings.decode(before) if before is not None else {}
        sections["zed"] = fields(data, ZED, "zed", select=True)
        if sections["zed"] != data:
            notices.append(
                "The Zed export includes supported preferences and credential-free llama.cpp endpoints. Other Zed settings stay in settings.json."
            )
    document = {
        "schema": SCHEMA,
        "type": "automation-profile",
        "application_version": workflows.APPLICATION_VERSION,
        "sections": sections,
    }
    normalize(document, validate)
    return {"profile": document, "notices": notices}


def normalize(document, validate):
    validate_document(document)
    if not isinstance(document, dict) or document.get("type") != "automation-profile":
        raise ValueError(
            "Expected an Automation Toolkit profile with type automation-profile"
        )
    schema = document.get("schema")
    if type(schema) is not int or schema not in (1, SCHEMA):
        raise ValueError(
            "Unsupported profile schema. Keep the original and use a toolkit version that supports it."
        )
    notices = []
    version = workflows.profile_version(document.get("application_version"))
    if schema == 1:
        object_fields(
            document,
            {"type", "schema", "application_version", "settings"},
            "legacy profile",
        )
        settings = object_fields(
            document.get("settings"), workflows.PROFILE_KEYS, "legacy settings"
        )
        sections = {"toolkit": settings}
        validate(settings)
        if "AUTOMATION_SELECTED_PACKAGES" in settings:
            sections["setup"] = {
                "selected": [
                    name.strip()
                    for name in settings["AUTOMATION_SELECTED_PACKAGES"].split(",")
                    if name.strip()
                ]
            }
        notices.append(
            "Schema 1 CLI settings were migrated. Sections absent from that profile keep their current values."
        )
    else:
        object_fields(
            document, {"type", "schema", "application_version", "sections"}, "profile"
        )
        if version is None:
            raise ValueError("Schema 2 profiles require an application version")
        sections = object_fields(document.get("sections"), SECTIONS, "sections")
    if version and tuple(map(int, version.split("."))) > tuple(
        map(int, workflows.APPLICATION_VERSION.split("."))
    ):
        notices.append(
            "A newer application exported this profile. Only fields supported here can be applied."
        )
    if not sections:
        raise ValueError("Choose at least one profile section")
    clean = {}
    if "toolkit" in sections:
        values = object_fields(sections["toolkit"], SETTINGS, "toolkit")
        validate(values)
        clean["toolkit"] = values
    if "setup" in sections:
        setup = sections["setup"]
        ai = setup.get("ai") if isinstance(setup, dict) else None
        if isinstance(ai, dict) and "shell" in ai:
            setup = dict(setup)
            current_ai = {key: value for key, value in ai.items() if key != "shell"}
            if current_ai:
                setup["ai"] = current_ai
            else:
                del setup["ai"]
            notices.append(
                "Skipped the retired Local AI shell preference. Use Configure → Terminal for shell settings."
            )
        clean["setup"] = draft(setup)
    if "mappings" in sections:
        clean["mappings"] = mapping_rows(sections["mappings"])
    if "zed" in sections:
        clean["zed"] = fields(sections["zed"], ZED, "zed")
    return clean, notices


def plan(root, state, info, document, parse, validate):
    sections, notices = normalize(document, validate)
    writes = {}
    settings = sections.get("toolkit", {})
    selected = sections.get("setup", {}).get("selected", [])
    dedicated = {"bash", "fish", "zsh", "lerd"} & set(selected)
    if dedicated:
        if document["schema"] != 1:
            raise ValueError(
                "Use the dedicated Terminal and Lerd pages for: "
                + ", ".join(sorted(dedicated))
            )
        sections["setup"]["selected"] = [
            name for name in selected if name not in dedicated
        ]
        notices.append(
            "Dedicated Terminal and Lerd package choices stay in CLI settings and are configured on their own dashboard pages: "
            + ", ".join(sorted(dedicated))
        )
    if settings:
        target, before, after, changes = configuration.prepare(
            root, settings, parse, validate, fields=SETTINGS
        )
        writes["toolkit"] = (target, before, after, changes)
        if any(row["environment_override"] for row in changes.values()):
            notices.append(
                "Environment overrides remain active over imported toolkit settings."
            )
    if sections.get("mappings"):
        target = package_mappings.path(state)
        before = filesystem.read_regular(
            target, missing=True, private=True, limit=workflows.MAX_JSON
        )
        data = (
            json.loads(before, object_pairs_hook=filesystem.unique)
            if before is not None
            else {}
        )
        mapping_rows(data)
        previous = copy.deepcopy(data)
        for platform, rows in sections["mappings"].items():
            data.setdefault(platform, {}).update(rows)
        if any(
            key != package_mappings.platform_key(info) for key in sections["mappings"]
        ):
            notices.append(
                "Mappings for other platforms are saved but inactive on this system."
            )
        after = before if data == previous else encode(data)
        if after is not None and len(after) > workflows.MAX_JSON:
            raise ValueError("Merged package mappings exceed the size limit")
        writes["mappings"] = (target, before, after, None)
    if sections.get("zed"):
        target = zed_settings.settings_path()
        before = zed_settings.read(target, missing=True)
        original = zed_settings.decode(before) if before is not None else {}
        result = copy.deepcopy(original)
        zed_settings.overlay(result, sections["zed"])
        encoded = encode(result)
        after = before if encoded == encode(original) else encoded
        if after is not None and len(after) > zed_settings.LIMIT:
            raise ValueError("Merged Zed settings exceed the size limit")
        writes["zed"] = (target, before, after, None)
    if sections.get("setup") or "AUTOMATION_PROJECT_SITES_DIR" in settings:
        notices.append(
            "Confirm that imported folder paths and remote hosts are correct for this computer. Import does not create project or model folders, connect to servers, install packages, or start services."
        )
    revision = hashlib.sha256(
        encode(
            {
                "profile": document,
                "files": {
                    key: [
                        str(target),
                        zed_settings.digest(before),
                        zed_settings.digest(after),
                        changes,
                    ]
                    for key, (target, before, after, changes) in writes.items()
                },
            }
        )
    ).hexdigest()
    return writes, {
        "revision": revision,
        "sections": list(sections),
        "notices": notices,
        "settings": sections,
        "setup": sections.get("setup", {}),
        "files": [
            {"section": key, "path": str(target), "changed": before != after}
            for key, (target, before, after, _) in writes.items()
        ],
    }


def restore(root, state, info, document, parse, validate, *, revision=None):
    writes, review = plan(root, state, info, document, parse, validate)
    if revision is None:
        return review
    if not isinstance(revision, str) or revision != review["revision"]:
        raise ValueError(
            "Profile or current configuration changed. Review the import again."
        )
    written, backups = [], {}
    try:
        for key, (target, before, after, changes) in writes.items():
            if before == after:
                continue
            if key == "toolkit":
                backups[key] = configuration.record(state, target, changes)
            elif key == "zed":
                backups[key] = zed_settings.backup(
                    state, target, before, zed_settings.digest(after), announce=False
                )
            else:
                folder = journal.state_dir(state)
                backup = folder / f"profile-mappings-{uuid.uuid4().hex}.json"
                workflows.write_json(
                    backup,
                    {
                        "schema": SCHEMA,
                        "type": "automation-profile",
                        "application_version": workflows.APPLICATION_VERSION,
                        "sections": {
                            "mappings": json.loads(before) if before is not None else {}
                        },
                    },
                    private=True,
                )
                backups[key] = backup.name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if (
                filesystem.read_regular(target, missing=True, limit=workflows.MAX_JSON)
                != before
            ):
                raise ValueError(
                    "A configuration file changed during import. Review again."
                )
            filesystem.atomic(target, after)
            written.append((target, before, after))
    except (OSError, ValueError) as error:
        failed = []
        for target, before, after in reversed(written):
            try:
                if (
                    filesystem.read_regular(
                        target, missing=True, limit=workflows.MAX_JSON
                    )
                    != after
                ):
                    failed.append(str(target))
                elif before is None:
                    target.unlink()
                else:
                    filesystem.atomic(target, before)
            except (OSError, ValueError):
                failed.append(str(target))
        if failed:
            raise ValueError(
                "Import interrupted. Check local backups and these files: "
                + ", ".join(failed)
            ) from error
        raise
    return {**review, "backups": backups}
