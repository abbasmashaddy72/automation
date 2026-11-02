#!/usr/bin/env bash
automation_configuration() { python3 "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/automation.py" config "$@"; }
