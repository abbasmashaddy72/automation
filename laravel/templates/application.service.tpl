[Unit]
Description=Laravel @@DOMAIN@@
After=network.target
ConditionPathExists=@@SITE_ROOT@@/current/artisan
[Service]
User=@@DEPLOY_USER@@
Group=www-data
WorkingDirectory=@@SITE_ROOT@@/current
ExecStart=/usr/bin/php@@PHP_VERSION@@ @@SITE_ROOT@@/current/artisan @@COMMAND@@
NoNewPrivileges=true
PrivateTmp=true
@@SERVICE_OPTIONS@@
