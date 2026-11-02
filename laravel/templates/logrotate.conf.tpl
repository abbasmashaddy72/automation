@@SITE_ROOT@@/shared/storage/logs/*.log {
    daily
    rotate 14
    missingok
    notifempty
    compress
    delaycompress
    su @@DEPLOY_USER@@ www-data
    copytruncate
}
