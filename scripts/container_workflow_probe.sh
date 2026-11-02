#!/bin/sh
# Mutating integration probe ONLY inside an explicitly authorized disposable container.
# This is separate from the non-root, read-only container_probe.sh contract.
set -eu
[ "${AUTOMATION_DISPOSABLE_CONTAINER:-}" = yes ] || { echo 'Disposable-container opt-in required' >&2; exit 4; }
[ -r /run/.containerenv ] || [ -f /.dockerenv ] || { echo 'Container runtime marker required' >&2; exit 4; }
case "${1:-}" in
    arch) pacman -Sy --noconfirm ;;
    debian) apt-get update ;;
    fedora|rhel) dnf -y makecache ;;
    opensuse) zypper --non-interactive refresh ;;
    alpine) apk update; apk add bash ;;
    *) exit 2 ;;
esac
# All writes, package transactions and logs are confined to this disposable layer.
cp -R /toolkit /tmp/automation-workflow
cd /tmp/automation-workflow
export XDG_STATE_HOME=/tmp/automation-private-state
mkdir -m 700 "$XDG_STATE_HOME"
bash setup.sh prerequisites install --runtime-only --without-ui --yes
run_ai_build() {
    [ "$1" = debian ] || { echo 'Source-build fixture requires Debian' >&2; exit 2; }
    bash setup.sh ai llamacpp install --cpu-threads 2 --yes
    "$HOME/.local/share/automation-toolkit/ai/llamacpp/build/bin/llama-server" --version
    printf 'LLAMACPP_CPU_SOURCE_BUILD=yes\n'
}

run_ollama_install() {
    bash setup.sh ai ollama install --yes
    command -v ollama
    ollama --help >/dev/null
    bash setup.sh ai ollama install --yes
    printf 'OLLAMA_NATIVE_INSTALL_AND_REPEAT=yes\n'
}

run_lint() {
    [ "$1" = debian ] || { echo 'Lint bootstrap is Debian-only' >&2; exit 2; }
    apt-get install -y --no-install-recommends shellcheck shfmt
    shellcheck --version
    shfmt --version
    bash scripts/check-scripts.sh --check
    printf 'LINT_TOOLS_CHECKED=yes\n'
}

run_system_tests() {
    # The minimal Tumbleweed image ships a BusyBox awk variant that conflicts
    # with the official Fish dependency. This is an explicit disposable-fixture
    # variant replacement, never an automatic production solver override.
    if [ "$1" = opensuse ] && rpm -q busybox-gawk >/dev/null 2>&1; then
        zypper --non-interactive remove busybox-gawk
        zypper --non-interactive install gawk
        rpm -q gawk
        command -v awk
        printf 'FIXTURE_AWK_VARIANT=gawk\n'
    fi
    # Exact native shell packages only; repository absence is an explicit
    # capability skip, never a reason to add third-party repositories.
    for shell in fish zsh; do
        if bash setup.sh packages install --select "$shell" --no-lerd --no-auto-search --yes; then
            command -v "$shell"
        else
            status=$?
            [ "$status" = 5 ] || exit "$status"
            printf 'OPTIONAL_SHELL_UNAVAILABLE=%s\n' "$shell"
        fi
    done
    mkdir -m 700 /tmp/automation-test-home
    chown -R 65534:65534 /tmp/automation-test-home /tmp/automation-workflow
    python3 - <<'SYSTEM_TESTS'
import os,sys
home='/tmp/automation-test-home'
env={**os.environ,'HOME':home,'USER':'nobody','LOGNAME':'nobody',
     'XDG_CONFIG_HOME':home+'/.config','XDG_STATE_HOME':home+'/.local/state',
     'XDG_CACHE_HOME':home+'/.cache','PYTHONDONTWRITEBYTECODE':'1'}
for key in ('XDG_RUNTIME_DIR','SSH_AUTH_SOCK','DISPLAY','WAYLAND_DISPLAY','XDG_CURRENT_DESKTOP','BASH_ENV','ENV'):
    env.pop(key,None)
# This rootless-container-only handoff does not involve PAM, login sessions,
# passwords or changing the image's deliberately expired system accounts.
os.setgroups([]);os.setgid(65534);os.setuid(65534)
os.execve(sys.executable,[sys.executable,'-B','-m','unittest','discover','-s','tests','-v'],env)
SYSTEM_TESTS
    printf 'UNPRIVILEGED_SYSTEM_REGRESSIONS=yes\n'
}

run_checklist_automation() (
export AUTOMATION_PROJECT_SITES_DIR=/tmp/automation-checklist-sites
mkdir -p "$AUTOMATION_PROJECT_SITES_DIR/Local"
printf 'preserved-project\n' > "$AUTOMATION_PROJECT_SITES_DIR/Local/existing.txt"
bash setup.sh checklist automate --select configuration,projects --dry-run
test ! -e "$AUTOMATION_PROJECT_SITES_DIR/Testing"
bash setup.sh checklist automate --select configuration,projects --yes
bash setup.sh checklist automate --select configuration,projects --yes
bash setup.sh checklist check > /tmp/automation-checklist-observations.json
python3 - <<'AUTOMATED_CHECKS'
import json
from pathlib import Path
result=json.loads(Path('/tmp/automation-checklist-observations.json').read_text())
assert all(row['status']=='ready' for row in result['checks'])
assert Path('/tmp/automation-checklist-sites/Local/existing.txt').read_text()=='preserved-project\n'
print('CHECKLIST_AUTOMATION=yes')
AUTOMATED_CHECKS
)

if [ "${AUTOMATION_WORKFLOW_SKIP_SMOKE:-no}" = yes ]; then
    if [ "${AUTOMATION_WORKFLOW_LINT:-no}" = yes ]; then run_lint "$1"; fi
    if [ "${AUTOMATION_WORKFLOW_AI_BUILD:-no}" = yes ]; then run_ai_build "$1"; fi
    if [ "${AUTOMATION_WORKFLOW_OLLAMA_INSTALL:-no}" = yes ]; then run_ollama_install "$1"; fi
    if [ "${AUTOMATION_WORKFLOW_SYSTEM_TESTS:-no}" = yes ]; then
        bash setup.sh prerequisites install --runtime-only --with-git --with-ssh --with-ollama --without-ui --yes
        run_checklist_automation
        run_system_tests "$1"
    fi
    exit 0
fi

bash setup.sh --check
bash setup.sh packages plan --select git --no-lerd --no-auto-search --dry-run
bash setup.sh packages search git --no-lerd
bash setup.sh packages plan --select git,curl,wget,unzip,python3 --no-lerd --no-auto-search --dry-run
install_tools() {
    if [ "$1" = fedora ]; then
        # Explicit test selection, not a fuzzy/automatic fallback: Fedora ships
        # wget2-wget. Its FTP/WARC semantics differ; keep catalogue reporting honest.
        bash setup.sh packages install --select git,curl,wget,unzip --replace wget=wget2-wget --no-lerd --no-auto-search --yes
    else
        bash setup.sh packages install --select git,curl,wget,unzip --no-lerd --no-auto-search --yes
    fi
}
install_tools "$1"
install_tools "$1"
command -v git
command -v curl
command -v wget
command -v unzip
# OpenSSH prerequisites and user-only legacy replacements. No network SSH
# connection or agent is started; the key/config exist only in this layer.
bash setup.sh prerequisites install --runtime-only --with-ssh --without-ui --yes
command -v ssh
command -v ssh-add
command -v ssh-keygen
mkdir -m 700 /tmp/automation-ssh-fixture
ssh-keygen -q -t ed25519 -N '' -f /tmp/automation-ssh-fixture/identity
bash setup.sh developer ssh --identity-file /tmp/automation-ssh-fixture/identity --ssh-host fixture --hostname example.invalid --ssh-user git --yes
ssh -G -F "$HOME/.ssh/automation-toolkit.conf" fixture > /tmp/automation-ssh-fixture/effective-config
grep -Fx 'hostname example.invalid' /tmp/automation-ssh-fixture/effective-config
grep -Fx 'identitiesonly yes' /tmp/automation-ssh-fixture/effective-config
# Explicit Git transport changes and native agent protocol, confined to this
# disposable layer. No remote SSH connection or systemd service is started.
bash setup.sh developer git-transport --transport ssh --yes
test "$(git ls-remote --get-url https://github.com/fixture/project)" = git@github.com:fixture/project
bash setup.sh developer git-transport --transport https --yes
test "$(git ls-remote --get-url https://github.com/fixture/project)" = https://github.com/fixture/project
export XDG_RUNTIME_DIR=/tmp/automation-native-runtime
mkdir -m 700 "$XDG_RUNTIME_DIR" "$XDG_RUNTIME_DIR/automation-ssh-agent"
ssh-agent -D -a "$XDG_RUNTIME_DIR/automation-ssh-agent/agent.sock" >/dev/null 2>&1 &
fixture_agent_pid=$!
cleanup_agent() {
    kill "$fixture_agent_pid" 2>/dev/null || true
    wait "$fixture_agent_pid" 2>/dev/null || true
}
trap cleanup_agent EXIT HUP INT TERM
python3 - <<'AGENT_CHECK'
import os,sys,time
from pathlib import Path
sys.path.insert(0,'lib')
import ssh_agent,developer
deadline=time.monotonic()+5
while time.monotonic()<deadline:
    if ssh_agent.probe()=='ready-empty':break
    time.sleep(0.05)
else:raise SystemExit('Temporary native agent did not become ready')
Path('/tmp/automation-shell-fixture').write_bytes(developer.shell_content(b'','bash',use_agent=True))
AGENT_CHECK
bash --noprofile --norc -c 'unset SSH_AUTH_SOCK; source /tmp/automation-shell-fixture; test "$SSH_AUTH_SOCK" = "$XDG_RUNTIME_DIR/automation-ssh-agent/agent.sock"'
SSH_AUTH_SOCK="$XDG_RUNTIME_DIR/automation-ssh-agent/agent.sock" ssh-add /tmp/automation-ssh-fixture/identity >/dev/null 2>&1
python3 - <<'LOADED_CHECK'
import sys
sys.path.insert(0,'lib')
import ssh_agent
assert ssh_agent.probe()=='ready-with-keys'
print('GIT_TRANSPORT_AND_PRIVATE_AGENT=yes')
LOADED_CHECK
cleanup_agent
trap - EXIT HUP INT TERM
test ! -S "$XDG_RUNTIME_DIR/automation-ssh-agent/agent.sock"
bash setup.sh checklist done theme --yes
bash setup.sh checklist list > /tmp/automation-checklist-fixture.json
python3 - <<'USER_CHECKS'
import json
from pathlib import Path
tasks=json.loads(Path('/tmp/automation-checklist-fixture.json').read_text())['tasks']
assert len(tasks)==25
assert next(row for row in tasks if row['id']=='theme')['status']=='done'
assert not {'identity','software'} & {row['id'] for row in tasks}
print('SSH_CONFIG_AND_MANUAL_CHECKLIST=yes')
USER_CHECKS
run_checklist_automation
# Verify every catalogue entry resolves to a truthful status on this distribution.
python3 - <<'CHECK'
import sys
sys.path.insert(0, 'lib')
import automation
import json
names=[row['id'] for row in json.load(open('config/packages/default.json'))['packages']]
raise SystemExit(automation.main(['packages','plan','--select',','.join(names),'--no-lerd','--no-auto-search','--dry-run']))
CHECK
if [ "${AUTOMATION_WORKFLOW_LINT:-no}" = yes ]; then
    run_lint "$1"
fi
if [ "${AUTOMATION_WORKFLOW_AI_BUILD:-no}" = yes ]; then
    run_ai_build "$1"
fi
if bash setup.sh packages install --select automation-nonexistent-test-package --no-lerd --no-auto-search --yes; then
    echo 'Unavailable package incorrectly reported success' >&2
    exit 1
else
    status=$?
    [ "$status" = 5 ] || { echo "Unexpected unavailable-package exit: $status" >&2; exit 1; }
fi
printf 'BOOTSTRAP=yes\nPLAN=yes\nGIT_INSTALL_VERIFIED=yes\nREPEAT_INSTALL=yes\nUNAVAILABLE_EXIT=5\n'

if [ "${AUTOMATION_WORKFLOW_OLLAMA_INSTALL:-no}" = yes ]; then
    run_ollama_install "$1"
fi

if [ "${AUTOMATION_WORKFLOW_SYSTEM_TESTS:-no}" = yes ]; then
    run_system_tests "$1"
fi
