# Project directories, Lerd PHP and Open WebUI

The old installer module is removed. The [migration ledger](legacy-migration.md)
records which behaviors were replaced and which the owner approved retiring.

## Project directories

```bash
bash setup.sh projects layout "$HOME/Documents/Project-Sites" --dry-run
bash setup.sh projects layout "$HOME/Documents/Project-Sites" --yes
```

Creates missing `Experiment`, `Local`, `Other-Languages`, `Packages-Git`,
`Packages-Own`, `Personal-Git`, `Staging` and `Testing` directories. Existing
projects are preserved. All directory conflicts and links are checked before
creation; repeated invocation creates only missing directories. Select folders
explicitly when using Lerd's public `park`/`link` commands. No Composer global
installation, Valet, phpinfo page or host web-server setup runs implicitly.

## PHP and development services belong to Lerd

```bash
bash setup.sh configuration php
bash setup.sh lerd php:list
bash setup.sh lerd service list
bash setup.sh lerd service preset
```

`configuration php` is read-only guidance. Standalone PHP/FPM/Nginx exports are
retired; old `--standalone` or export requests return exit code 3 without writing
files, even with `--yes`. PHP, Composer, Node/npm, databases and the web stack use
Lerd's public interfaces. Lerd selection also suppresses a separate nvm bootstrap.
Existing host packages, databases, services and configurations remain unchanged.

Use official `lerd php:ini` or `lerd php:ini shared` when you intentionally want
to edit PHP settings. Upstream can restart affected FPM containers after saving;
review that behavior before invoking the editor. This toolkit never edits Lerd
images or internal files directly. See [Lerd PHP](https://lerd.sh/usage/php) and
[services](https://lerd.sh/getting-started/services).

## Optional USB review export

Lerd does not manage USB permissions. The old automatic rule installer is retired;
this separate optional export applies nothing to the host:

```bash
bash setup.sh configuration udev --vendor 05ac --product 12ab
bash setup.sh configuration udev --vendor 05ac --product 12ab --output /absolute/new-usb-review-directory --yes
```

Without `--output`, this is a read-only plan. Export requires a new directory and
`--yes`; check/dry-run never creates it. Output is private (0700 directory, 0600
files), includes SHA-256 values, and never overwrites existing files. An interrupted
export remains available for inspection. System directories and symlink paths are
rejected.

Exact vendor/product IDs are required. The rule uses mode 0660 and `uaccess`
instead of world-writable permissions. Actual access depends on a supported local
logind session; review distro rules and the [udev reference](https://www.freedesktop.org/software/systemd/man/257/udev.html).
No `/etc` activation, device trigger, rule reload or usbmuxd restart is implemented
or advertised. Real device access is not certified by export tests.

## Rootless Open WebUI

Choose and review an exact upstream image digest; replace the placeholder with 64
lowercase hexadecimal digits:

```bash
bash setup.sh webui plan --image ghcr.io/open-webui/open-webui@sha256:REVIEWED_DIGEST
bash setup.sh webui install --image ghcr.io/open-webui/open-webui@sha256:REVIEWED_DIGEST --yes
bash setup.sh webui status
bash setup.sh webui stop --yes
bash setup.sh webui start --yes
bash setup.sh webui remove --yes
bash setup.sh webui recreate --dry-run
bash setup.sh webui recreate --yes
bash setup.sh webui recover --dry-run
bash setup.sh webui recover --yes
```

Installed local rootless Podman is required; remote connection environment settings
are ignored. Cached pinned images are used by default. Add `--allow-pull --yes`
only when explicitly approving the image download. No Docker/Podman service,
group membership, firewall, existing container or Ollama binding is changed.
WebUI publishes on `127.0.0.1:3000`; select a different unprivileged port when
installing. Authentication remains enabled.

The default Ollama endpoint inside the container is
`http://host.containers.internal:11434`, following the
[upstream Podman guidance](https://docs.openwebui.com/getting-started/quick-start/).
Reachability depends on the existing network; the toolkit never exposes or
reconfigures an existing Ollama service to make it reachable. Container running
state alone does not prove app readiness, connectivity or inference.

An intent file is written privately before resource creation. Ownership is
committed only after observing the exact container ID/image/label/data mount and
volume creation identity. `recover` handles failure before container creation,
interruption before receipt publication and interruption after publication. It
refuses foreign containers, mismatched receipts, altered volumes and later edits.
It never deletes a container or data as a recovery shortcut.

Removal requires an explicitly stopped owned container and preserves its data
volume, image and receipt. `recreate` reuses only that observed volume and the same
pinned image/configuration after confirming that the old container ID is absent;
previous receipts are backed up privately. The generated session key lives in
the data volume with umask 0077 so recreation can preserve sessions. Older receipts
without a volume creation identity cannot authorize recreation automatically.
Image upgrades need a separate application-data backup and migration review;
`recreate` does not silently switch images or apply database migrations from a new
version.

## Actual app sandbox

```bash
python3 scripts/webui_sandbox.py --image ghcr.io/open-webui/open-webui@sha256:REVIEWED_DIGEST --yes --output /absolute/private/validation/webui
```

Add `--allow-pull` explicitly if the pinned image is not cached. The sandbox uses
randomly named rootless containers/volumes and an internal network. It disables
model-provider connections and does not contact existing AI services. A fresh
fixture account tests valid, invalid and absent credentials on the protected
endpoint, receipt interruption/recovery, and account/session/key preservation
across actual recreation. Only its own marked resources are torn down; the
approved downloaded image stays cached. No credentials or raw app logs are
included in `webui-sandbox.json`. Browser UX and model inference are separate gates.

The actual slim-image sandbox passed interrupted recovery, valid/invalid/absent
credential checks, account/session/private-key persistence and full fixture
teardown using digest
`sha256:82cb66ea03829d29b27b66214e740ccc31101415e67c2db2338456e081356dfe`.
The normal result is in `validation/webui-migration/webui-sandbox.json` under
the toolkit's state directory. This does not certify other image versions or
connectivity to an existing Ollama server.

## Verification boundaries

| Workflow | Evidence | Independent gates |
|---|---|---|
| Project layout | Disposable filesystem dry-run/repeat/conflict/link/preservation tests | Existing Valet conversion is retired |
| PHP | Lerd-only guidance and retired-export refusal tests | No host PHP/INI or Lerd services mutated |
| USB export | Input, checksums, permissions, no-overwrite and CLI no-write tests | Real device access/manual activation |
| WebUI lifecycle | Receipt/ownership/recovery/recreation and remote-engine refusal regressions; actual app sandbox output | Browser UX, provider connectivity/inference and image-version upgrades |

Existing GNOME/KDE sessions, host user systemd/autostart, GPUs and production
servers are not certified by these tests. See the normal validation output and
[migration ledger](legacy-migration.md) for the scope of each gate.
