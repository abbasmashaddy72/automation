#!/usr/bin/env bash
# Noninteractive calls are handled by Python; gum is used only with a TTY.
automation_ui_available() { command -v gum >/dev/null && [[ -t 0 && -t 1 ]]; }
