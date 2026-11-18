#!/usr/bin/env bash
set -Eeuo pipefail

# Run from Bash, Fish or Zsh with: bash scripts/check-scripts.sh
# --format applies shfmt to the source tree; the default is read-only.
BASE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
MODE="${1:---check}"
case "$MODE" in --check | --format | --syntax-only) ;; *)
    printf 'Usage: bash scripts/check-scripts.sh [--check|--format|--syntax-only]\n' >&2
    exit 2
    ;;
esac
cd "$BASE"

mapfile -d '' FILES < <(
    find . -type d \( \
        -name .git -o -name .cache -o -name .next -o -name .venv -o -name __pycache__ -o \
        -name node_modules -o -name backups -o -name logs -o -name reports \
        \) -prune -o -type f -name '*.sh' -print0 | sort -z && printf '\0'
)
# The empty final record confirms discovery completed even though mapfile
# cannot report the exit code of its process substitution.
if (("${#FILES[@]}" == 0)) || [[ -n "${FILES[-1]}" ]]; then
    printf 'FAIL: Could not enumerate Bash source files.\n' >&2
    exit 1
fi
unset 'FILES[-1]'
failed=0
printf 'Checking %s Bash scripts...\n' "${#FILES[@]}"
for file in "${FILES[@]}"; do
    if ! bash -n "$file"; then
        printf 'FAIL syntax: %s\n' "$file" >&2
        failed=1
    fi
done
if [[ "$MODE" == --syntax-only ]]; then exit "$failed"; fi
if command -v shellcheck > /dev/null 2>&1; then
    # Report but do not change historical scripts. Script style warnings may
    # require a separate review; syntax and actual errors are blockers.
    shellcheck --severity=error "${FILES[@]}" || failed=1
else
    printf 'WARNING: shellcheck not installed; install with the native package manager\n' >&2
fi
if command -v shfmt > /dev/null 2>&1; then
    if [[ "$MODE" == --format ]]; then
        shfmt -w -i 4 -ci -sr "${FILES[@]}"
    else
        # Do not fail pre-existing scripts just because formatting differs.
        if ! formatting=$(shfmt -l -i 4 -ci -sr "${FILES[@]}"); then
            printf 'FAIL: shfmt could not parse one or more scripts.\n' >&2
            failed=1
        elif [[ -n "$formatting" ]]; then
            printf 'NOTE: Some scripts differ from shfmt style; use --format after reviewing git diff.\n'
        fi
    fi
else
    printf 'WARNING: shfmt not installed; install with the native package manager\n' >&2
fi
if command -v python3 > /dev/null 2>&1; then
    # Parse Python helpers without writing __pycache__ into the project.
    python3 -B - << 'PY'
import sys

sys.path.insert(0, "scripts")
from validate import python_syntax

result = python_syntax()
for error in result["errors"]:
    print("FAIL Python:", error, file=sys.stderr)
if result["status"] != "pass":
    sys.exit(1)
print('Python helper syntax: passed')
PY
fi
exit "$failed"
