[@@PREFIX@@]
user = @@DEPLOY_USER@@
group = www-data
listen = @@SOCKET@@
listen.owner = www-data
listen.group = www-data
listen.mode = 0660
pm = ondemand
pm.max_children = 5
pm.process_idle_timeout = 10s
php_admin_flag[display_errors] = off
php_admin_flag[log_errors] = on
php_admin_value[error_log] = @@SITE_ROOT@@/shared/storage/logs/php-error.log
