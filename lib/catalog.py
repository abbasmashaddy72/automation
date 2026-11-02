"""Curated package sources; never infer a package name on a different distro.

Names are candidates, not guarantees: the active repository must answer the
availability query before installation. No third-party repositories are added.
"""
from __future__ import annotations

FAMILIES = ('arch', 'debian', 'fedora', 'rhel', 'opensuse', 'alpine')

# Most names are shared. Use explicit per-family exceptions rather than guessing.
CROSS = {
    'git': 'git', 'curl': 'curl', 'wget': 'wget', 'unzip': 'unzip', 'zip': 'zip',
    'tree': 'tree', 'nodejs': 'nodejs', 'flatpak': 'flatpak', 'podman': 'podman',
    'shellcheck': {'arch':'shellcheck','debian':'shellcheck','fedora':'ShellCheck','rhel':'ShellCheck','opensuse':'ShellCheck','alpine':'shellcheck'},
    'shfmt': {'arch':'shfmt','debian':'shfmt','fedora':'shfmt','rhel':'shfmt','opensuse':'shfmt','alpine':'shfmt'},
    'python3': {'arch':'python','debian':'python3','fedora':'python3','rhel':'python3','opensuse':'python3','alpine':'python3'},
    'firefox': {'arch':'firefox','debian':'firefox-esr','fedora':'firefox','rhel':'firefox','opensuse':'MozillaFirefox','alpine':'firefox'},
    'thunderbird': {'arch':'thunderbird','debian':'thunderbird','fedora':'thunderbird','rhel':'thunderbird','opensuse':'MozillaThunderbird','alpine':'thunderbird'},
    'vlc': {'arch':'vlc','debian':'vlc','fedora':'vlc','opensuse':'vlc','alpine':'vlc'},
    'keepassxc': {'arch':'keepassxc','debian':'keepassxc','fedora':'keepassxc','opensuse':'keepassxc','alpine':'keepassxc'},
    'remmina': {'arch':'remmina','debian':'remmina','fedora':'remmina','opensuse':'remmina','alpine':'remmina'},
    'freerdp': {'arch':'freerdp','debian':'freerdp3-x11','fedora':'freerdp','opensuse':'freerdp','alpine':'freerdp'},
    'meld': {'arch':'meld','debian':'meld','fedora':'meld','opensuse':'meld','alpine':'meld'},
    'okular': {'arch':'okular','debian':'okular','fedora':'okular','opensuse':'okular','alpine':'okular'},
    'scrcpy': {'arch':'scrcpy','debian':'scrcpy','fedora':'scrcpy','opensuse':'scrcpy','alpine':'scrcpy'},
    'usbmuxd': {'arch':'usbmuxd','debian':'usbmuxd','fedora':'usbmuxd','opensuse':'usbmuxd','alpine':'usbmuxd'},
    'libimobiledevice': {'arch':'libimobiledevice','debian':'libimobiledevice-utils','fedora':'libimobiledevice','opensuse':'libimobiledevice-1_0-6','alpine':'libimobiledevice'},
    'ifuse': {'arch':'ifuse','debian':'ifuse','fedora':'ifuse','opensuse':'ifuse','alpine':'ifuse'},
    'android-tools': {'arch':'android-tools','debian':'adb','fedora':'android-tools','opensuse':'android-tools','alpine':'android-tools'},
    'gvfs-afc': {'arch':'gvfs-afc','debian':'gvfs-backends','fedora':'gvfs-afc','opensuse':'gvfs-backends','alpine':'gvfs-afc'},
    'virtualbox': {'arch':'virtualbox','debian':'virtualbox','fedora':'VirtualBox','opensuse':'virtualbox'},
    'base-devel': {'arch':'base-devel'},
    'shelly': {'arch':'shelly'},
    'ttf-jetbrains-mono': {'arch':'ttf-jetbrains-mono','debian':'fonts-jetbrains-mono','fedora':'jetbrains-mono-fonts','opensuse':'jetbrains-mono-fonts'},
    'ttf-hack-nerd': {'arch':'ttf-hack-nerd'},
    'deluge-gtk': {'arch':'deluge-gtk','debian':'deluge-gtk','fedora':'deluge-gtk','opensuse':'deluge','alpine':'deluge'},
    'dbeaver': {'arch':'dbeaver'},
    'brave-browser': {'arch':'brave-browser'},
    'firefox-developer-edition': {'arch':'firefox-developer-edition'},
    'google-chrome': {'arch':'google-chrome'},
    'torbrowser-launcher': {'arch':'torbrowser-launcher','debian':'torbrowser-launcher'},
    'intellij-idea-community-edition': {'arch':'intellij-idea-community-edition'},
    'pycharm-community-edition': {'arch':'pycharm-community-edition'},
    'android-studio': {'arch':'android-studio'},
    'visual-studio-code-bin': {'arch':'visual-studio-code-bin'},
    'void-bin': {'arch':'void-bin'},
    'postman-bin': {'arch':'postman-bin'},
    'tiny-rdm-bin': {'arch':'tiny-rdm-bin'},
    'onlyoffice-bin': {'arch':'onlyoffice-bin'},
    'ferdium': {'arch':'ferdium'},
    'winscp': {'arch':'winscp'},
    'anydesk-bin': {'arch':'anydesk-bin'},
    'peek': {'arch':'peek','debian':'peek','fedora':'peek'},
    'freetube': {'arch':'freetube'},
    'virtualbox-guest-iso': {'arch':'virtualbox-guest-iso'},
    'virtualbox-guest-utils': {'arch':'virtualbox-guest-utils','debian':'virtualbox-guest-utils','fedora':'virtualbox-guest-additions','opensuse':'virtualbox-guest-tools'},
    'ventoy': {'arch':'ventoy'},
}

# Official application IDs; Flatpak source availability still requires a
# configured user remote. These do not imply Flathub endorsement by a distro.
FLATPAKS = {
    'firefox':'org.mozilla.firefox',
    'thunderbird':'org.mozilla.Thunderbird',
    'vlc':'org.videolan.VLC',
    'keepassxc':'org.keepassxc.KeePassXC',
    'dbeaver':'io.dbeaver.DBeaverCommunity',
    'remmina':'org.remmina.Remmina',
    'meld':'org.gnome.meld',
    'okular':'org.kde.okular',
    'onlyoffice-bin':'org.onlyoffice.desktopeditors',
    'ferdium':'org.ferdium.Ferdium',
    'freetube':'io.freetubeapp.FreeTube',
    'brave-browser':'com.brave.Browser',
    'google-chrome':'com.google.Chrome',
    'postman-bin':'com.getpostman.Postman',
    'intellij-idea-community-edition':'com.jetbrains.IntelliJ-IDEA-Community',
    'pycharm-community-edition':'com.jetbrains.PyCharm-Community',
    'visual-studio-code-bin':'com.visualstudio.code',
}

# Community/unverified repackagings are never implicit fallback choices.
COMMUNITY_FLATPAKS = {'visual-studio-code-bin'}

# Explicit documented Arch AUR package names. Never apply outside Arch.
AUR = {
    'shelly','brave-browser','google-chrome','firefox-developer-edition',
    'intellij-idea-community-edition','pycharm-community-edition','android-studio',
    'visual-studio-code-bin','void-bin','postman-bin','tiny-rdm-bin',
    'onlyoffice-bin','ferdium','anydesk-bin','freetube','ventoy',
}

DESKTOP_CATEGORIES = {'Browsers and Desktop Applications', 'Optional Productivity Tools'}
DESKTOP_EXTRA = {'android-studio','visual-studio-code-bin','intellij-idea-community-edition',
                 'pycharm-community-edition','dbeaver','postman-bin','remmina','freerdp',
                 'virtualbox-guest-iso','virtualbox-guest-utils','ttf-jetbrains-mono',
                 'ttf-hack-nerd','shelly'}


def native_name(package, family):
    if package == 'lerd':
        return None
    name = CROSS.get(package)
    if isinstance(name, str):
        return name if family in FAMILIES else None
    if isinstance(name, dict):
        return name.get(family)
    return package if family == 'arch' else None


def supports(package, family, desktop=True):
    if package == 'lerd':
        return True
    return bool(native_name(package, family) or (desktop and package in FLATPAKS))

# Standalone servers/tools superseded by the Lerd-managed local environment.
# Never include desktop DB clients (DBeaver), API clients (Postman) or generic
# Podman in this set: they are independent tools that may still be necessary.
LERD_MANAGED = {
    'nodejs': 'Lerd-managed Node version selection',
    'npm': 'Lerd-managed Node tooling',
    'nvm': 'Lerd-managed Node version selection; no separate version-manager bootstrap',
    'php': 'Lerd PHP runtime and PHP version switching',
    'php-fpm': 'Lerd-managed PHP-FPM',
    'mariadb': 'Lerd MariaDB preset (select through Lerd)',
    'mysql-server': 'Lerd MySQL service',
    'postgresql-server': 'Lerd PostgreSQL service',
    'postgresql': 'Lerd PostgreSQL service (server package alias)',
    'valkey': 'Skipped for the Lerd-selected profile; choose a supported cache service through the public Lerd CLI',
    'redis': 'Lerd Redis service',
    'nginx': 'Lerd web server and local HTTPS',
    'apache2': 'Lerd web server and local HTTPS',
    'composer': 'Lerd Composer tooling',
}

CROSS.update({
    'php': {'arch':'php','debian':'php','fedora':'php','rhel':'php','opensuse':'php8','alpine':'php83'},
    'php-fpm': {'arch':'php-fpm','debian':'php-fpm','fedora':'php-fpm','rhel':'php-fpm','opensuse':'php8-fpm','alpine':'php83-fpm'},
    'mariadb': {'arch':'mariadb','debian':'mariadb-server','fedora':'mariadb-server','rhel':'mariadb-server','opensuse':'mariadb','alpine':'mariadb'},
    'mysql-server': {'debian':'mysql-server','fedora':'community-mysql-server','rhel':'mysql-server','opensuse':'mysql-community-server'},
    'postgresql-server': {'arch':'postgresql','debian':'postgresql','fedora':'postgresql-server','rhel':'postgresql-server','opensuse':'postgresql-server','alpine':'postgresql'},
    'redis': {'arch':'redis','debian':'redis-server','fedora':'redis','rhel':'redis','opensuse':'redis','alpine':'redis'},
    'nginx': 'nginx',
    'apache2': {'arch':'apache','debian':'apache2','fedora':'httpd','rhel':'httpd','opensuse':'apache2','alpine':'apache2'},
    'composer': {'arch':'composer','debian':'composer','fedora':'composer','rhel':'composer','opensuse':'php-composer','alpine':'composer'},
})
