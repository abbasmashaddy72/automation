#!/bin/bash

set -e

echo "📦 Setting up Zsh environment..."

# Install Zsh silently
if ! command -v zsh &>/dev/null; then
    echo "Installing Zsh..."
    sudo zypper install -y zsh
else
    echo "✅ Zsh already installed."
fi

# Change default shell to Zsh (non-interactive)
chsh -s /usr/bin/zsh "$(whoami)"

# Install Oh My Zsh silently
if [ ! -d "$HOME/.oh-my-zsh" ]; then
    echo "Installing Oh My Zsh..."
    RUNZSH=no CHSH=no KEEP_ZSHRC=yes sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
else
    echo "✅ Oh My Zsh already installed."
fi

ZSH_CUSTOM="${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}"

# Clone plugins
declare -A plugins_repos=(
    ["zsh-autosuggestions"]="https://github.com/zsh-users/zsh-autosuggestions"
    ["zsh-syntax-highlighting"]="https://github.com/zsh-users/zsh-syntax-highlighting"
    ["zsh-autocomplete"]="https://github.com/marlonrichert/zsh-autocomplete"
)

for plugin in "${!plugins_repos[@]}"; do
    plugin_path="$ZSH_CUSTOM/plugins/$plugin"
    if [ ! -d "$plugin_path" ]; then
        echo "Cloning $plugin..."
        git clone "${plugins_repos[$plugin]}" "$plugin_path"
    else
        echo "✅ $plugin already exists."
    fi
done

# Ensure plugins are added to .zshrc
plugins=('colorize' 'command-not-found' 'composer' 'laravel' 'npm' 'safe-paste' 'suse' 'git' 'zsh-autosuggestions' 'zsh-autocomplete' 'zsh-syntax-highlighting')

for plugin in "${plugins[@]}"; do
    if ! grep -q "$plugin" ~/.zshrc; then
        sed -i "/^plugins=(/ s/)/ $plugin)/" ~/.zshrc
        echo "Added plugin: $plugin"
    fi
done

# Update theme to agnoster
sed -i 's/ZSH_THEME=".*"/ZSH_THEME="agnoster"/' ~/.zshrc

# Add colorize config if missing
if ! grep -q "ZSH_COLORIZE_TOOL=" ~/.zshrc; then
    cat <<'EOF' >>~/.zshrc

# Zsh Colorize Plugin
export ZSH_COLORIZE_TOOL=chroma
export ZSH_COLORIZE_STYLE="colorful"
export ZSH_COLORIZE_CHROMA_FORMATTER=terminal256
EOF
    echo "Added colorize config."
fi

echo "✅ Zsh environment setup complete."
