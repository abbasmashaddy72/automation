# Packages and prerequisites

Use **Packages** in the local dashboard or `bash setup.sh wizard` in a terminal. The system check detects the distribution and package manager. The toolkit resolves package names using the native manager and the enabled sources for that host. [Observed distribution differences](unified-setup.md#observed-distribution-differences)

```bash
bash setup.sh prerequisites check
bash setup.sh packages search git
bash setup.sh packages plan --profile=minimal --dry-run
bash setup.sh packages install --select git,curl --yes
```

## Select, preview, and install

1. Select a category or search the catalog. Package status can reflect an installed alias, such as `brave-bin` for Brave or `intellij-idea-oss` for IntelliJ IDEA Community on compatible Arch systems.
2. Choose **Next: preview selected packages** to see the exact package IDs, sources, and installed or unavailable entries. Under **Custom package**, search existing sources for other packages.
3. Choose **Proceed with installation** to approve the preview. An existing selection is skipped unless you request a reinstall in the confirmation. The package manager resolves dependencies. Use the launching terminal if prompted for authentication or source review.

A similar name is a suggestion. Review its source and select it explicitly before using it. The toolkit validates your exact selection before installing. Use `--replace REQUEST=EXACT_NATIVE` to confirm an exact native replacement on the CLI. Saved dashboard mappings retain the actual ID, source, distribution, architecture and manager.

## Package sources

- **Native repositories** use pacman, APT, DNF, Zypper, or APK on their respective distributions. A missing cache or unavailable package stays unverified.
- **AUR and Shelly** are Arch-family workflows. The dashboard detects configured working helpers. Noninteractive CLI use needs `--enable-aur` or saved approval. The helper presents its own build-recipe and dependency review in the launching terminal.
- **Flatpak** uses configured remotes and exact app IDs. On Arch, select the Flatpak preference explicitly if you choose it as an alternative. If an AUR installation fails, the dashboard exposes alternative search and review.
- **Lerd** owns its development runtimes. Selecting Lerd suppresses overlapping standalone databases, PHP, Node, caches and web servers from the same package plan.

The toolkit queries configured repositories and remotes without adding sources. An unavailable installation selection exits with code 5. For distro test coverage, see the [validation matrix](validation.md).

## Save and reuse a plan

Use **Download plan JSON** after preview, or export from the CLI:

```bash
bash setup.sh packages export --select git,curl --output reviewed-packages.json
bash setup.sh packages restore reviewed-packages.json --dry-run
```

Native restore uses exact IDs and a matching platform. Mixed-source plans serve as an inventory. See [portable profiles and offline receipts](workflows.md) for formats, replay approval and limitations.
