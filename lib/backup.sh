#!/usr/bin/env bash
# Patch backups and transactional restoration: scripts/patch_manager.py.
automation_backup_help() { bash "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)/scripts/update.sh" --help; }
