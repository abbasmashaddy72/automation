#!/usr/bin/env bash
automation_info() { printf '[INFO] %s\n' "$*"; }
automation_error() { printf '[ERROR] %s\n' "$*" >&2; }
