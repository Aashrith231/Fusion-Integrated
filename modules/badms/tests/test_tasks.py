"""Celery tasks, the beat entries and the routes they need.

Each task is idempotent: run it twice, one effect. The beat schedule and the
queue routes must be wired into the platform's celery app (Step 2.6).
"""
import pytest

from config.celery import app as platform_app
from modules.badms import schedule as badms_schedule
from modules.badms.services import notifications

pytestmark = pytest.mark.django_db


def test_every_task_is_runnable_and_idempotent():
    from modules.badms import tasks

    # A drained outbox and no due schedules: every task is a no-op, twice.
    assert tasks.deliver_notifications() == "sent=0 failed=0 deferred=0"
    assert tasks.deliver_notifications() == "sent=0 failed=0 deferred=0"
    assert tasks.run_scheduled_backups() == 0
    assert tasks.run_scheduled_backups() == 0
    assert tasks.sweep_backup_alerts() == 0
    assert tasks.sweep_backup_alerts() == 0
    assert tasks.monitor_storage() == 0
    assert tasks.monitor_storage() == 0


def test_the_delivery_task_drains_a_queued_row(monkeypatch):
    from modules.badms import tasks

    notifications.enqueue(dedupe_key="t1", topic="backup.completed",
                          subject="s", body="b", recipient_email="a@x.y")
    monkeypatch.setattr(notifications, "send_mail", lambda **kw: None)
    assert "sent=1" in tasks.deliver_notifications()


def test_task_names_are_stable():
    from modules.badms import tasks

    assert tasks.deliver_notifications.name == "badms.deliver_notifications"
    assert tasks.run_scheduled_backups.name == "badms.run_scheduled_backups"
    assert tasks.sweep_backup_alerts.name == "badms.sweep_backup_alerts"
    assert tasks.monitor_storage.name == "badms.monitor_storage"


def test_beat_schedule_and_routes_are_wired_into_the_platform_app():
    beat = platform_app.conf.beat_schedule or {}
    for entry_name in badms_schedule.BEAT_SCHEDULE:
        assert beat.get(entry_name), f"beat entry {entry_name} missing"
    routes = platform_app.conf.task_routes or {}
    for task_name in badms_schedule.TASK_ROUTES:
        assert routes.get(task_name) == badms_schedule.TASK_ROUTES[task_name]


def test_the_delivery_beat_runs_every_minute_for_the_5_minute_sla():
    entry = badms_schedule.BEAT_SCHEDULE["badms.deliver-notifications"]
    assert entry["schedule"] <= 60.0
