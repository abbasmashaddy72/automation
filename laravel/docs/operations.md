# Reviewed manifests and operation boundaries

A PHP repository manifest is private reviewed data, not an executable hook:

```json
{"schema":1,"name":"approved-php","uri":"https://YOUR_APPROVED_REPOSITORY/ubuntu","suite":"noble","component":"main","key_url":"https://YOUR_APPROVED_REPOSITORY/signing-key.asc","key_sha256":"INDEPENDENTLY_VERIFIED_64_HEX_DIGEST"}
```

Replace all illustrative values with an independently verified upstream repository, Ubuntu suite and ASCII-armored public signing key checksum. Repository installation needs `--approve-repository`; negative pinning excludes non-PHP packages from that origin. APT still verifies archive signatures. No default third-party repository or obsolete `apt-key` command is embedded. The external provisioning script URL and repository source are separate controls.

A migration review manifest contains exactly these fields:

```json
{"schema":1,"backward_compatible":true,"files":{"2026_01_01_000000_create_example_table.php":"REVIEWED_FILE_SHA256"}}
```

Include every committed PHP migration with the exact relative filename and SHA-256. Generate hashes from the reviewed revision outside the deployment, after human compatibility review; a hash alone cannot classify PHP code as safe. The command compares the full file map and uses `migrate --force --isolated=75`. Database isolation depends on the application's configured lock store. Back up production databases and use expand-and-contract deployment procedures. No automatic schema reversal exists.

Private provisioning state/backups live under `/var/lib/automation-toolkit/laravel/DOMAIN/`. This retained namespace is an on-server receipt location, not a parent toolkit dependency. Deployment locks, state and interruption receipts live in SITE_ROOT. A failed operation leaves evidence and preserves later user edits. Fix unavailable packages, edited configuration, incompatible migrations or service failures explicitly, then repeat the approved operation. Provisioning file recovery occurs on the next approved managed-file transaction; application activation recovery requires explicit `--recover`. External script failures require `--retry-external` after inspection.

The toolkit does not configure Git hosting accounts, manage production secrets, install drivers, force package substitutions, overwrite sites, reset firewalls, rotate database credentials or expose a network shell executor. Existing externally provisioned layouts must meet the documented ownership/storage/environment contract. Do not use a container success as proof of host SSH access, systemd autostart or TLS issuance.
