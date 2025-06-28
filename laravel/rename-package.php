#!/usr/bin/env php
<?php

/**
 * rename-package.php
 * Usage:
 *   php rename-package.php old-kebab new-kebab OldPascal NewPascal
 *
 * Example:
 *   php rename-package.php message-automation notifier-kit MessageAutomation NotifierKit
 */
[$_, $oldKebab, $newKebab, $oldPascal, $newPascal] = $argv;

$basePath = __DIR__;

function renameFilesAndContent($base, $old, $new)
{
    $rii = new RecursiveIteratorIterator(
        new RecursiveDirectoryIterator($base, FilesystemIterator::SKIP_DOTS),
        RecursiveIteratorIterator::SELF_FIRST
    );

    foreach ($rii as $file) {
        $path = $file->getPathname();

        // Ignore .git
        if (strpos($path, DIRECTORY_SEPARATOR . '.git' . DIRECTORY_SEPARATOR) !== false) {
            continue;
        }

        // Rename file or directory
        if (strpos(basename($path), $old) !== false) {
            $newPath = str_replace($old, $new, $path);
            rename($path, $newPath);
            $path = $newPath;
        }

        // Only edit files
        if ($file->isFile()) {
            $content = file_get_contents($path);
            $content = str_replace($old, $new, $content);
            $content = str_replace(strtolower($old), strtolower($new), $content);
            file_put_contents($path, $content);
        }
    }
}

function updateComposerJson($path, $newKebab, $newPascal)
{
    $json = json_decode(file_get_contents($path), true);

    if (! $json) {
        echo "❌ Failed to parse composer.json\n";

        return;
    }

    $json['name'] = "zephyrit/{$newKebab}";
    $json['autoload']['psr-4'] = [
        "ZephyrIt\\\\{$newPascal}\\\\" => 'src/',
    ];

    file_put_contents($path, json_encode($json, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES));
    echo "✅ Updated composer.json\n";
}

// === RUN ===

echo "🔁 Starting rename: {$oldKebab} → {$newKebab}, {$oldPascal} → {$newPascal}\n";

renameFilesAndContent($basePath, $oldPascal, $newPascal);
renameFilesAndContent($basePath, $oldKebab, $newKebab);

// Rename config file
$configOld = "{$basePath}/config/{$oldKebab}.php";
$configNew = "{$basePath}/config/{$newKebab}.php";
if (file_exists($configOld)) {
    rename($configOld, $configNew);
    echo "✅ Renamed config file: {$oldKebab}.php → {$newKebab}.php\n";
}

// Update composer.json
updateComposerJson("{$basePath}/composer.json", $newKebab, $newPascal);

// Dump autoload
echo "⚙️  Dumping autoload...\n";
passthru('composer dump-autoload');

echo "🎉 Rename complete! Your package is now '{$newKebab}' using namespace '{$newPascal}'\n";
