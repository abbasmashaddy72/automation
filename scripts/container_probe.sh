#!/bin/sh
# Read-only distro/package-manager capability probe. Never installs packages.
set -eu
expected="${1:-}"
case "$expected" in arch|debian|fedora|rhel|opensuse|alpine) ;; *) echo 'Invalid expected family' >&2; exit 2;; esac
[ -r /etc/os-release ] || { echo 'Missing /etc/os-release' >&2; exit 3; }
# Parse only ID/ID_LIKE; do not execute OS-provided text as shell code.
id=$(sed -n 's/^ID=//p' /etc/os-release | head -n 1 | tr -d '"')
like=$(sed -n 's/^ID_LIKE=//p' /etc/os-release | head -n 1 | tr -d '"')
case " $id $like " in
  *' arch '*|*' archlinux '*) family=arch; manager=pacman ;;
  *' debian '*|*' ubuntu '*) family=debian; manager=apt-get ;;
  *' fedora '*) family=fedora; manager=dnf ;;
  *' rhel '*|*' centos '*|*' rocky '*|*' almalinux '*) family=rhel; manager=dnf ;;
  *' opensuse '*|*' opensuse-tumbleweed '*|*' opensuse-leap '*|*' suse '*) family=opensuse; manager=zypper ;;
  *' alpine '*) family=alpine; manager=apk ;;
  *) family=unknown; manager=none ;;
esac
# ID-specific override before parent matches (mirrors Python provider precedence).
case "$id" in
  fedora|nobara) family=fedora; manager=dnf ;;
  rocky|almalinux|rhel|centos) family=rhel; manager=dnf ;;
  opensuse*|sles) family=opensuse; manager=zypper ;;
  alpine) family=alpine; manager=apk ;;
  arch|archlinux|cachyos|manjaro) family=arch; manager=pacman ;;
  debian|ubuntu|linuxmint|pop) family=debian; manager=apt-get ;;
esac
printf 'DISTRO_ID=%s\nFAMILY=%s\nMANAGER=%s\n' "$id" "$family" "$manager"
[ "$family" = "$expected" ] || { echo "Expected $expected, detected $family" >&2; exit 4; }
command -v "$manager" >/dev/null 2>&1 || { echo "Native package manager missing: $manager" >&2; exit 5; }
printf 'MANAGER_PRESENT=yes\nREAD_ONLY=yes\n'
