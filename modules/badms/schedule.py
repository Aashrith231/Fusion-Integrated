"""What this module needs run on a timer.

The delivery beat runs every minute, which is what puts the backup-failure
alert inside its five-minute SLA (BR-BA-014). Scheduled backups are evaluated
every five minutes against each schedule's own due rule, so a daily 02:00
schedule fires within five minutes of 02:00 without a queue full of
per-schedule timers.
"""
from celery.schedules import crontab

TASK_ROUTES = {
    "badms.deliver_notifications": {"queue": "notifications"},
    "badms.run_scheduled_backups": {"queue": "default"},
    "badms.sweep_backup_alerts": {"queue": "default"},
    "badms.monitor_storage": {"queue": "default"},
}

BEAT_SCHEDULE = {
    "badms.deliver-notifications": {
        "task": "badms.deliver_notifications",
        "schedule": 60.0,
        "options": {"expires": 55},
    },
    "badms.run-scheduled-backups": {
        "task": "badms.run_scheduled_backups",
        "schedule": 300.0,
        "options": {"expires": 290},
    },
    # The SLA guard: re-queue a failure alert that never made it out.
    "badms.sweep-backup-alerts": {
        "task": "badms.sweep_backup_alerts",
        "schedule": 300.0,
        "options": {"expires": 290},
    },
    # Threshold monitoring keeps the full-quota condition current (UC-BA-022).
    "badms.monitor-storage": {
        "task": "badms.monitor_storage",
        "schedule": crontab(minute="*/15"),
        "options": {"expires": 800},
    },
}
