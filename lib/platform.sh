#!/usr/bin/env bash
# Compatibility shell interface, central logic lives in lib/automation.py.
automation_platform() { python3 "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/automation.py" doctor "$@"; }
