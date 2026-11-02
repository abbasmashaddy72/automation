# Unified architecture

`setup.sh` is the Bash entrypoint and dispatches Bash-only prerequisites before Python. It classifies read-only requests before any automatic dependency installation.

| Area | Maintained owner |
|---|---|
| CLI / approval / plans / package transactions | `lib/automation.py` |
| Native naming and exact source checks | `lib/catalog.py`, `providers.py` |
| Suggestions and optional Arch sources | `lib/discovery.py`, `sources.py` |
| Progress, metadata caches and selection | `lib/progress.py`, `cache.py`, `wizard.py` |
| Private receipts / ownership | `lib/journal.py` |
| Safe `.env` merge | `lib/configuration.py`, `config/defaults.env` |
| Profiles / exports / offline receipts | `lib/workflows.py`, `extensions.py` |
| Project skeletons | `lib/bootstrap.py` |
| Lerd public CLI | `lib/lerd_ops.py`, `automation.py` |
| AI dispatch / CPU build / foreground serving | `ai/manager.py`, `portable.py` |
| Owned user-service lifecycle and allowlisted runtime | `ai/services.py` |
| User Git/shell integration and conflict-safe restore | `lib/developer.py` |
| Local diagnostics / keys / GGUF receipts | `ai/ai_health.py`, `auth.py`, `models.py` |
| Desktop detection / favorites / backups | `lib/desktop.py` |
| Update / recovery / release generation | `scripts/patch_manager.py`, `full_update.py`, `build-release.py` |
| Offline / container / actual inference checks | `scripts/validate.py`, `container_workflows.py`, `ai_sandbox.py` |

Adapters use pacman, apt, dnf, zypper and apk independently. A common RPM database query does not make zypper interchangeable with dnf. Name matches never authorize substitutions.

The entire `modules/legacy/` installer module is removed. The [ledger](legacy-migration.md) records maintained replacements and owner-approved retirement of host provisioning, standalone development services, Valet and native vLLM/Playground installation. Existing databases, services and AI stores are preserved. Bounded old-state importers remain maintained data parsers, not installer dispatchers. Shell wrappers under `lib/` use the shared implementation.
