"""Scheduled work.

Ids only in arguments, never ORM objects. Everything is idempotent, because
`acks_late` means a task can run twice if a worker dies mid-flight.
"""
from __future__ import annotations

import logging

from celery import shared_task

log = logging.getLogger("fusion.badms.tasks")


@shared_task(
    name="badms.deliver_notifications",
    acks_late=True, reject_on_worker_lost=True,
    soft_time_limit=270, time_limit=300,
)
def deliver_notifications(limit: int | None = None) -> str:
    from modules.badms.services import notifications

    report = notifications.deliver_pending(limit=limit)
    log.info("badms.notify.run %s", report)
    return str(report)


@shared_task(
    name="badms.run_scheduled_backups",
    acks_late=True, reject_on_worker_lost=True,
    soft_time_limit=570, time_limit=600,
)
def run_scheduled_backups() -> int:
    """Execute every schedule that is due (UC-BA-006)."""
    from modules.badms.services import backups

    ran = backups.run_due_backups()
    if ran:
        log.info("badms.backup.scheduled_run ran=%d", ran)
    return ran


@shared_task(
    name="badms.sweep_backup_alerts",
    acks_late=True, reject_on_worker_lost=True,
    soft_time_limit=270, time_limit=300,
)
def sweep_backup_alerts() -> int:
    """Re-queue failure alerts that missed the five-minute SLA (BR-BA-014)."""
    from modules.badms.services import backups

    n = backups.sweep_failure_alerts()
    if n:
        log.warning("badms.backup.alerts_requeued count=%d", n)
    return n


@shared_task(name="badms.monitor_storage", acks_late=True)
def monitor_storage() -> int:
    """Re-evaluate every user's threshold status (UC-BA-022)."""
    from modules.badms.services import storage

    n = storage.monitor_all()
    log.info("badms.storage.monitored profiles=%d", n)
    return n
