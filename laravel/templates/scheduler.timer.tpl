[Unit]
Description=Laravel scheduler @@DOMAIN@@
[Timer]
OnCalendar=*-*-* *:*:00
Persistent=false
Unit=@@PREFIX@@-schedule.service
[Install]
WantedBy=timers.target
