#!/usr/bin/env bash
automation_ai() { python3 "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/../ai/manager.py" "$@"; }
