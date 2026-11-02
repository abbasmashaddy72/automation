# Arch/CachyOS/Manjaro/EndeavourOS

Use the unified entrypoint; native package operations use `pacman`.

```bash
bash setup.sh --check
bash setup.sh prerequisites check
bash setup.sh packages search git
bash setup.sh packages plan --profile=minimal --dry-run
bash setup.sh packages install --select git,curl --yes
```

Only already configured repositories are queried; exact identity is checked before approved installation. No repository additions or signature bypasses are performed. Missing metadata/packages are reported unavailable.

See [setup](unified-setup.md), [AI](archlinux-llamacpp.md), [legacy migration](legacy-migration.md) and [test matrix](unified-setup.md). Container package tests do not certify real-host services, desktop settings or GPU acceleration. Legacy provisioning is not a supported shortcut.
