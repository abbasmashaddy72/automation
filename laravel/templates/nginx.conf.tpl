server {
    listen 80;
    server_name @@DOMAIN@@;
    root @@SITE_ROOT@@/current/public;
    index index.php;
    location ^~ /.well-known/acme-challenge/ { root @@SITE_ROOT@@/acme; }
    location / { try_files $uri $uri/ /index.php?$query_string; }
    location = /index.php {
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $realpath_root/index.php;
        fastcgi_param DOCUMENT_ROOT $realpath_root;
        fastcgi_pass unix:@@SOCKET@@;
        fastcgi_hide_header X-Powered-By;
    }
    location ~ \.php$ { return 404; }
    location ~ /\.(?!well-known).* { deny all; }
    client_max_body_size 64m;
}
