#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "${1:-}" == laravel ]]; then
    case "${2:-}" in
        provision|deploy)
            LARAVEL_WORKFLOW="${2}"
            shift 2
            exec bash "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/laravel/laravel-${LARAVEL_WORKFLOW}.sh" "$@"
            ;;
        *) printf 'Usage: bash setup.sh laravel provision|deploy [options]\n' >&2; exit 2 ;;
    esac
fi
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

# This Bash-only entrypoint remains useful before Python has been installed.
if [[ "${1:-}" == prerequisites ]]; then
    shift
    exec bash "$ROOT/scripts/prerequisites.sh" "$@"
fi

AUTO_PREREQS=0
FORWARD=()
for arg in "$@"; do
    if [[ "$arg" == --auto-prereqs ]]; then
        AUTO_PREREQS=1
    else
        FORWARD+=("$arg")
    fi
done

python_ok() {
    command -v python3 >/dev/null 2>&1 && python3 -c 'import sys;sys.exit(0 if sys.version_info >= (3,9) else 1)' >/dev/null 2>&1
}
readonly_request=0 mutation=0 wants_lerd=0
for arg in "${FORWARD[@]}"; do
    case "$arg" in
        --check|--status|--list-models|--test-api|--dry-run|--help|-h|doctor|check|status|service-status|list|models|model-search|model-files|cache-list|gguf-list|gguf-legacy-list|gguf-resolve|legacy-plan|plan|search|hardware) readonly_request=1 ;;
        --install|install|--repair|repair|--update|update|wizard|configure|model-select|gguf-download|gguf-legacy-import|gguf-select|gguf-remove|legacy-import|start|stop|restart|autostart|key-generate|key-use|key-import|key-rotate|key-revoke|model-download|model-remove|snapshot-import|snapshot-remove) mutation=1 ;;
    esac
done
case "${FORWARD[0]:-}:${FORWARD[1]:-}" in
    developer:git|developer:git-transport|developer:shell|developer:ssh|developer:ssh-generate|developer:ssh-add|developer:ssh-copy|developer:clone|developer:ssh-agent|developer:import-git-backup|developer:import-shell-backup|developer:restore|checklist:automate|checklist:done|checklist:pending|checklist:skipped|checklist:review|config:init|projects:init|projects:layout|profiles:import|profiles:export|dashboard:export|offline:prepare|packages:export|desktop:apply|desktop:restore) mutation=1 ;;
esac
case "${FORWARD[0]:-}:${FORWARD[1]:-}:${FORWARD[2]:-}" in
    developer:ssh-agent:|developer:ssh-agent:status) readonly_request=1 ;;
esac
if [[ ${#FORWARD[@]} == 0 && -t 0 ]]; then mutation=1; fi
if (( mutation || AUTO_PREREQS )) || ! python_ok; then
    # Only mutating workflows may auto-bootstrap. Help, doctor and planning are
    # always read-only, even when --auto-prereqs is accidentally supplied.
    if [[ "${FORWARD[*]}" == *'lerd install'* || "${FORWARD[*]}" == *'--select lerd'* || "${FORWARD[*]}" == *'--select=lerd'* ]]; then
        wants_lerd=1
    fi
    opts=(--runtime-only)
    (( wants_lerd )) && opts+=(--with-lerd)
    # Backend-specific build prerequisites run after Python validates AI flags.
    opts+=(--without-ui)  # Wizard never installs optional Gum implicitly.
    for item in "${FORWARD[@]}"; do
        case "$item" in
            --yes|-y|--dry-run|--non-interactive) opts+=("$item") ;;
        esac
    done
    if (( mutation && ! readonly_request )); then
        bash "$ROOT/scripts/prerequisites.sh" install "${opts[@]}" || exit $?
    else
        bash "$ROOT/scripts/prerequisites.sh" check "${opts[@]}" || exit $?
    fi
fi
if ! python_ok; then
    printf 'Python 3.9+ is required. To safely bootstrap it from existing native repositories:\n' >&2
    printf '  bash setup.sh prerequisites check\n' >&2
    printf '  bash setup.sh prerequisites install --dry-run\n' >&2
    printf '  bash setup.sh prerequisites install --yes\n' >&2
    printf 'Or use --auto-prereqs with a mutating setup command.\n' >&2
    exit 69
fi
if [[ "${FORWARD[0]:-}" == validate ]]; then
    exec python3 "$ROOT/scripts/validate.py" "${FORWARD[@]:1}"
fi
if [[ "${FORWARD[0]:-}" == ai ]]; then
    exec python3 "$ROOT/ai/manager.py" "${FORWARD[@]:1}"
fi
exec python3 "$ROOT/lib/automation.py" "${FORWARD[@]}"
