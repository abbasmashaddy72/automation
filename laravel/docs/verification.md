# Laravel verification

## 2026-11-18 native rerun

The standalone rootless Ubuntu 24.04 fixture passed all 12 checks again. Continuous HTTP sampling through native Nginx and PHP-FPM passed through failed candidate verification, healthy activation and rollback. The fixture exited successfully and its container was removed. The recovered run evidence is under `dashboard-layout-20261118/resumed` in the toolkit validation state directory.

## 2026-11-17 native results

The standalone toolkit passed all 12 checks on rootless Ubuntu 24.04. Continuous HTTP sampling through real Nginx and PHP-FPM returned 200 while the deployment rejected an unhealthy candidate before activation, switched to a healthy release and rolled back. The run also verified fresh and repeated provisioning, native PostgreSQL setup, preserved configuration and uploads, and Laravel migrations against a disposable SQLite application database. Container teardown passed.

The receipt is `advanced-deploy-20261117/laravel-current/laravel-sandbox.json` under the toolkit validation state directory. The systemd adapter drives native daemons and simulates the systemd manager, including timer and autostart behavior.

## Run the checks

Run these commands from the standalone Laravel directory.

```bash
python3 scripts/validate.py
python3 scripts/podman_test.py --allow-install --allow-pull --output="$HOME/.local/state/portable-laravel-tests"
```

The offline suite uses temporary Git repositories and command or HTTP fixtures. It checks configuration and approval boundaries, prerequisites, repository and URL validation, release locks, candidate failures, activation, rollback, recovery and retention. The host run discovers 31 Laravel tests. Its native PHP check is skipped when only the host Lerd wrapper is available, and the Ubuntu fixture exercises it with native PHP.

The native runner exports only this folder, excludes private configuration, keys and caches, and mounts the export read-only. Packages, Laravel dependencies and fixture data are installed inside the disposable layer. The runner verifies rootless Podman and confirms container removal.

## Earlier runs and remaining coverage

Native Ubuntu 24.04 runs on 2026-11-02 and 2026-11-03 passed the earlier ten-marker suite and confirmed teardown. Their receipts are `portable-laravel-manifest-fix/laravel-sandbox.json` and `system-finalization-20261103/isolated/laravel/laravel-sandbox.json`.

Separate gates cover native Ubuntu 22.04 and 26.04, arm64, real systemd boot and timers, queue service lifecycle, public ACME/DNS, administrator SSH and firewall changes, real remote Git credentials and production load. The fixture uses a small declared Node build task. Application-specific PHP, Node and frontend requirements depend on the deployed project.
