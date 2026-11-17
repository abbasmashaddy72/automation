#!/usr/bin/env bash
# Sourced from Bash or Zsh. Options come from the reviewed startup block.
_automation_toolkit_configure_shell() {
    case "${1-}" in
        bash | zsh) ;;
        *) return 2 ;;
    esac
    local client_shell="$1" banner=none enable_ai='' use_agent='' cleanup_aliases='' agent_dir commands=''
    shift
    while (($#)); do
        case "$1" in
            --banner)
                (($# >= 2)) || return 2
                banner="$2"
                shift 2
                ;;
            --use-toolkit-agent)
                use_agent=1
                shift
                ;;
            --commands)
                (($# >= 2)) || return 2
                commands="$2"
                shift 2
                ;;
            --project-cleanup-aliases)
                [[ "$client_shell" == zsh ]] || return 2
                cleanup_aliases=1
                shift
                ;;
            --terminal-ai)
                (($# >= 2)) || return 2
                enable_ai="$2"
                shift 2
                ;;
            *) return 2 ;;
        esac
    done

    if [[ -z "$commands" ]]; then
        commands=artisan,vbin,pint,sail,fixer,pest,phpunit
        if [[ -n "$cleanup_aliases" ]]; then commands+=,clean-npm,clean-composer; fi
        if [[ -n "$enable_ai" ]]; then commands+=,ai-ask,ai-suggest; fi
    fi
    commands=",$commands,"
    local _automation_toolkit_dir _automation_toolkit_tool vendor_runner vendor_tool
    for _automation_toolkit_dir in "$HOME/.local/bin" "$HOME/bin" "$HOME/.config/composer/vendor/bin" "$HOME/.composer/vendor/bin"; do
        case ":$PATH:" in
            *":$_automation_toolkit_dir:"*) ;;
            *) PATH="$_automation_toolkit_dir:$PATH" ;;
        esac
    done
    export PATH
    if [[ "$commands" == *,artisan,* ]] && ! alias artisan > /dev/null 2>&1 && ! command -v artisan > /dev/null 2>&1; then
        artisan() {
            if [[ ! -f artisan ]]; then
                printf '%s\n' 'artisan not found in the current directory' >&2
                return 1
            fi
            php artisan "$@"
        }
    fi
    _automation_run_vendor() {
        if [[ $# -eq 0 ]]; then
            printf '%s\n' 'Usage: vbin TOOL [ARGS...]' >&2
            return 2
        fi
        case "$1" in '' | */*)
            printf '%s\n' 'Select one vendor/bin tool name' >&2
            return 2
            ;;
        esac
        local vendor_executable="./vendor/bin/$1"
        shift
        if [[ ! -x "$vendor_executable" ]]; then
            printf '%s\n' 'Vendor tool missing or not executable' >&2
            return 127
        fi
        "$vendor_executable" "$@"
    }
    if [[ "$commands" == *,vbin,* ]] && ! command -v vbin > /dev/null 2>&1; then
        vbin() { _automation_run_vendor "$@"; }
    fi
    vendor_runner=_automation_run_vendor
    if command -v vbin > /dev/null 2>&1; then vendor_runner=vbin; fi
    for _automation_toolkit_tool in pint sail fixer pest phpunit; do
        if [[ "$commands" == *",${_automation_toolkit_tool},"* ]] && ! command -v "$_automation_toolkit_tool" > /dev/null 2>&1; then
            vendor_tool="$_automation_toolkit_tool"
            if [[ "$vendor_tool" == fixer ]]; then vendor_tool=php-cs-fixer; fi
            alias "$_automation_toolkit_tool=$vendor_runner $vendor_tool"
        fi
    done

    if [[ -n "$use_agent" && -z "${SSH_AUTH_SOCK:-}" && -n "${XDG_RUNTIME_DIR:-}" ]]; then
        agent_dir="$XDG_RUNTIME_DIR/automation-ssh-agent"
        if [[ ! -L "$XDG_RUNTIME_DIR" && ! -L "$agent_dir" && ! -L "$agent_dir/agent.sock" && -S "$agent_dir/agent.sock" ]]; then
            export SSH_AUTH_SOCK="$agent_dir/agent.sock"
        fi
    fi

    if [[ $- != *i* ]]; then return 0; fi
    if [[ "$commands" == *,clean-npm,* ]] && ! command -v clean-npm > /dev/null 2>&1; then
        alias clean-npm='rm -rf -- node_modules package-lock.json && npm install'
    fi
    if [[ "$commands" == *,clean-composer,* ]] && ! command -v clean-composer > /dev/null 2>&1; then
        alias clean-composer='rm -rf -- vendor composer.lock && composer install'
    fi
    if [[ "$banner" == fastfetch || "$banner" == neofetch ]] && command -v "$banner" > /dev/null 2>&1; then "$banner"; fi
    if [[ -z "$enable_ai" ]]; then return 0; fi
    _automation_toolkit_setup="$enable_ai"
    _automation_toolkit_client_shell="$client_shell"
    _automation_toolkit_commands="$commands"
    automation_ai() {
        case "${1:-}" in ask | suggest) ;; *)
            printf '%s\n' 'Usage: ai ask|suggest QUESTION' >&2
            return 2
            ;;
        esac
        if [[ "$_automation_toolkit_commands" != *",ai-$1,"* ]]; then
            printf '%s\n' 'This Terminal AI command is disabled in Configure → Terminal.' >&2
            return 2
        fi
        local operation="$1"
        shift
        bash "$_automation_toolkit_setup" ai server "$operation" --shell "$_automation_toolkit_client_shell" -- "$@"
    }
    if ! command -v ai > /dev/null 2>&1; then alias ai=automation_ai; fi

    if [[ "$commands" != *,ai-suggest,* ]]; then return 0; fi
    if [[ "$client_shell" == zsh ]]; then
        _automation_ai_suggest() {
            local proposal
            [[ -n $BUFFER ]] || return
            proposal=$(printf '%s' "$BUFFER" | automation_ai suggest) || return
            [[ -n $proposal ]] || return
            BUFFER=$proposal
            CURSOR=${#BUFFER}
        }
        if [[ $(bindkey '^X^A') == *' undefined-key' ]]; then
            zle -N _automation_ai_suggest
            bindkey '^X^A' _automation_ai_suggest
        fi
    else
        _automation_ai_suggest() {
            local proposal
            [[ -n $READLINE_LINE ]] || return
            proposal=$(printf '%s' "$READLINE_LINE" | automation_ai suggest) || return
            [[ -n $proposal ]] || return
            READLINE_LINE=$proposal
            READLINE_POINT=${#READLINE_LINE}
        }
        if bind -X > /dev/null 2>&1 && ! {
            bind -p
            bind -s
            bind -X
        } 2> /dev/null | grep -Fq '"\C-x\C-a":'; then
            bind -x '"\C-x\C-a":_automation_ai_suggest'
        fi
    fi
}

_automation_toolkit_configure_shell "$@"
unset -f _automation_toolkit_configure_shell
