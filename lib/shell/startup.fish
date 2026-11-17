# Toolkit integration sourced by config.fish.
test "$argv[1]" = fish; or return 2
set -e argv[1] # Shell name keeps source arguments separate from the caller.
set -l _automation_banner none
set -l _automation_greeting
set -l _automation_use_agent
set -l _automation_enable_ai
set -l _automation_cleanup_aliases
set -l _automation_commands
while set -q argv[1]
    switch $argv[1]
        case --banner
            set -q argv[2]; or return 2
            set _automation_banner $argv[2]
            set -e argv[1..2]
        case --hide-greeting
            set _automation_greeting 1
            set -e argv[1]
        case --use-toolkit-agent
            set _automation_use_agent 1
            set -e argv[1]
        case --terminal-ai
            set -q argv[2]; or return 2
            set _automation_enable_ai $argv[2]
            set -e argv[1..2]
        case --commands
            set -q argv[2]; or return 2
            set _automation_commands (string split , -- "$argv[2]")
            set -e argv[1..2]
        case --project-cleanup-aliases
            set _automation_cleanup_aliases 1
            set -e argv[1]
        case '*'
            return 2
    end
end

if not set -q _automation_commands[1]
    set _automation_commands artisan vbin pint sail fixer pest phpunit
    if test -n "$_automation_cleanup_aliases"
        set -a _automation_commands clean-npm clean-composer
    end
    if test -n "$_automation_enable_ai"
        set -a _automation_commands ai-ask ai-suggest
    end
end
fish_add_path --path "$HOME/.local/bin" "$HOME/bin" "$HOME/.config/composer/vendor/bin" "$HOME/.composer/vendor/bin"
if contains -- artisan $_automation_commands; and not type -q artisan
    function artisan
        if not test -f artisan
            echo 'artisan not found in the current directory' >&2
            return 1
        end
        php artisan $argv
    end
end
function _automation_run_vendor
    if test (count $argv) -eq 0
        echo 'Usage: vbin TOOL [ARGS...]' >&2
        return 2
    end
    if string match -q '*/*' -- $argv[1]
        return 2
    end
    set -l bin ./vendor/bin/$argv[1]
    set -e argv[1]
    if not test -x "$bin"
        echo 'Vendor tool missing or not executable' >&2
        return 127
    end
    "$bin" $argv
end
if contains -- vbin $_automation_commands; and not type -q vbin
    alias vbin _automation_run_vendor
end
set -l _automation_vendor_runner _automation_run_vendor
if type -q vbin
    set _automation_vendor_runner vbin
end
for tool in pint sail fixer pest phpunit
    if contains -- $tool $_automation_commands; and not type -q $tool
        set -l vendor_tool $tool
        if test "$tool" = fixer
            set vendor_tool php-cs-fixer
        end
        alias $tool "$_automation_vendor_runner $vendor_tool"
    end
end

if test -n "$_automation_greeting"
    set -g fish_greeting ""
end
if test -n "$_automation_use_agent"; and test -z "$SSH_AUTH_SOCK"; and test -n "$XDG_RUNTIME_DIR"
    set -l agent_dir "$XDG_RUNTIME_DIR/automation-ssh-agent"
    if not test -L "$XDG_RUNTIME_DIR"; and not test -L "$agent_dir"; and not test -L "$agent_dir/agent.sock"; and test -S "$agent_dir/agent.sock"
        set -gx SSH_AUTH_SOCK "$agent_dir/agent.sock"
    end
end

if status is-interactive
    if contains -- clean-npm $_automation_commands; and not type -q clean-npm
        alias clean-npm 'rm -rf -- node_modules package-lock.json; and npm install'
    end
    if contains -- clean-composer $_automation_commands; and not type -q clean-composer
        alias clean-composer 'rm -rf -- vendor composer.lock; and composer install'
    end
    if contains -- "$_automation_banner" fastfetch neofetch; and type -q "$_automation_banner"
        $_automation_banner
    end
    if test -n "$_automation_enable_ai"
        set -g _automation_toolkit_setup "$_automation_enable_ai"
        set -g _automation_toolkit_commands $_automation_commands
        function automation_ai
            set -l operation $argv[1]
            if not contains -- "$operation" ask suggest
                echo 'Usage: ai ask|suggest QUESTION' >&2
                return 2
            end
            if not contains -- ai-$operation $_automation_toolkit_commands
                echo 'This Terminal AI command is disabled in Configure → Terminal.' >&2
                return 2
            end
            bash "$_automation_toolkit_setup" ai server $operation --shell fish -- $argv[2..-1]
        end
        if not type -q ai
            alias ai automation_ai
        end
        function _automation_ai_suggest
            set -l prompt (commandline)
            test -n "$prompt"; or return
            set -l proposal (printf '%s' "$prompt" | automation_ai suggest)
            if test $status -eq 0; and test (count $proposal) -eq 1
                commandline -r -- "$proposal"
                commandline -f end-of-line
            end
        end
        if contains -- ai-suggest $_automation_commands; and not bind \cx\ca >/dev/null 2>&1
            bind \cx\ca _automation_ai_suggest
        end
    end
end
