# Smart Backup

Open **Maintenance → Smart Backup** in the dashboard or choose **Smart Backup** from the interactive toolkit menu. Use the folder browser or enter absolute paths. The source defaults to your home directory. A detected mounted, writable external drive is suggested for the destination. Drive suggestions use `lsblk` when it is available. You can always choose an existing writable directory manually. The toolkit does not mount or format devices.

The dashboard starts with the preset from the original backup script. It copies visible files directly in Home and the existing **Desktop**, **Documents**, **Downloads**, **Music**, **Pictures**, **Videos**, and **Code** folders. If **Documents/Project-Sites** exists, it becomes its own ZIP archive. The terminal offers the same preset.

Expand folders in the dashboard tree to see their subfolders. Each subfolder inherits its parent's selection until you choose **Copy**, **ZIP archive**, or **Skip this folder** for that row. Separately selected subfolders are omitted from their parent's output. Each row keeps its action and hidden-file controls together. Turn on **Show hidden folders in the tree** to browse dot-directories, or add a folder by its path relative to the source. Open **Exclusions and verification** to change the defaults. Hidden entries inside selections are excluded by default. You can change the default or override it for each selected folder, explicitly select a hidden directory as its own job, and independently adjust the default `.git`, `node_modules`, `vendor`, `vendors` and `__pycache__` directory exclusions. Hidden content can include credentials. Backups are unencrypted, so choose who can access the destination.

**Preview backup** scans the selected trees and reports planned output paths, space estimates, and skipped mounts or special entries. Confirm **Create backup** to write and verify a new timestamped backup with a `manifest.json` that maps original folders to output names. Previous backups are preserved. A failed run can leave a hidden `.smart-backup-incomplete-*` directory for inspection. Pause applications that actively modify files for a consistent backup.

Copy requires `rsync` and preserves hard links, permissions, ownership where permitted, ACLs and extended attributes on a compatible filesystem. ZIP requires only Python and preserves file content, directory structure, and Unix mode and symlink metadata where supported by the extractor. ZIP omits hard-link relationships, ACLs and extended attributes. To restore, use the manifest to locate each copy or archive, inspect the contents, and copy or extract to a separate folder before replacing any live files.

```bash
bash setup.sh smart-backup
bash setup.sh smart-backup plan --destination /mnt/backup --home-defaults
bash setup.sh smart-backup run --destination /mnt/backup --copy Documents --zip Documents/Project-Sites --yes
```

Use `--include-hidden` to change the default, or `--hidden-in FOLDER` and `--visible-only-in FOLDER` for individual selections. Repeat `--exclude-dir NAME` for additional exclusions, or pass `--clear-default-exclusions` to start with no exclusions. Checksums are the default. `--verification quick` compares copy metadata and checks ZIP integrity.

Use `--root-files` to copy visible files directly under the source without the full preset. Use `--skip-folder RELATIVE/PATH` to exclude a subtree or clear a preset folder.

Both ZIP verification modes compare the archive's member list with the backup inventory before publishing the backup.
