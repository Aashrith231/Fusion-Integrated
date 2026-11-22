"""Notification decisions and delivery.

Every notification is written to the outbox in the same transaction as the
event that caused it, so a request and its email commit together and a broken
mail server can never fail a submission. `dedupe_key` makes redelivery
idempotent.

The backup-failure alert (BR-BA-014) is enqueued at the moment the failure is
recorded, and the delivery beat runs every minute — so the SysAdmin sees a
failure far inside the five-minute SLA. A sweep re-queues any failure whose
alert never made it out.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from modules.badms.models import NotificationOutbox
from modules.directory import contracts as directory

log = logging.getLogger("fusion.badms.notify")

TOPICS = {
    "backup.completed", "backup.failed", "backup.escalated",
    "archival.submitted", "archival.decided", "archival.encrypted",
    "storage.submitted", "storage.decided",
    "restoration.decided", "restoration.completed",
}


def enqueue(*, topic: str, dedupe_key: str, subject: str, body: str,
            recipient_user_id: int | None = None,
            recipient_email: str = "") -> NotificationOutbox | None:
    """Queue one notification, inside the caller's transaction. None if it
    was already queued."""
    if topic not in TOPICS:
        raise ValueError(f"Unknown notification topic {topic!r}.")
    if recipient_user_id is None and not recipient_email:
        raise ValueError("A notification needs a recipient.")

    try:
        # Nested, so a duplicate key cannot poison the caller's transaction.
        with transaction.atomic():
            return NotificationOutbox.objects.create(
                topic=topic, dedupe_key=dedupe_key, subject=subject, body=body,
                recipient_user_id=recipient_user_id,
                recipient_email=recipient_email)
    except IntegrityError:
        log.debug("badms.notify.duplicate key=%s", dedupe_key)
        return None


@dataclass
class DeliveryReport:
    sent: int = 0
    failed: int = 0
    deferred: int = 0

    def __str__(self) -> str:
        return f"sent={self.sent} failed={self.failed} deferred={self.deferred}"


#: A row unresolved this long is assumed orphaned and returned to the queue.
CLAIM_TIMEOUT = timedelta(minutes=10)


def _backoff_ready(row: NotificationOutbox, now) -> bool:
    if row.attempts == 0:
        return True
    return (now - row.updated_at) >= timedelta(minutes=2 ** (row.attempts - 1))


def _reclaim_stranded(now) -> int:
    return (NotificationOutbox.objects
            .filter(status="sending", claimed_at__lt=now - CLAIM_TIMEOUT)
            .update(status="pending", claimed_at=None))


def _claim(row) -> bool:
    """Take exclusive ownership of a row with one conditional UPDATE, so two
    workers can never send the same notification twice."""
    return NotificationOutbox.objects.filter(
        pk=row.pk, status="pending",
    ).update(status="sending", claimed_at=timezone.now()) == 1


def _fail(row: NotificationOutbox, error: str, max_attempts: int) -> None:
    row.attempts += 1
    row.last_error = error
    row.status = "failed" if row.attempts >= max_attempts else "pending"
    row.claimed_at = None
    row.save(update_fields=["attempts", "last_error", "status", "claimed_at",
                            "updated_at"])


def _resolve_addresses(rows: list[NotificationOutbox]) -> dict[int, str]:
    ids = {r.recipient_user_id for r in rows
           if r.recipient_user_id and not r.recipient_email}
    if not ids:
        return {}
    try:
        people = directory.get_users(sorted(ids))
    except Exception as exc:                                   # noqa: BLE001
        log.warning("badms.notify.directory_unavailable err=%s", exc)
        return {}
    return {uid: p.email for uid, p in people.items() if p.email}


def deliver_pending(*, limit: int | None = None, now=None) -> DeliveryReport:
    """Drain the outbox. Safe to run concurrently and safe to re-run."""
    now = now or timezone.now()
    _reclaim_stranded(now)
    limit = limit or getattr(settings, "NOTIFY_MAX_PER_RUN", 500)
    max_attempts = getattr(settings, "NOTIFY_MAX_ATTEMPTS", 5)
    report = DeliveryReport()

    queue = list(NotificationOutbox.objects
                 .filter(status="pending")
                 .order_by("created_at")[:limit])
    addresses = _resolve_addresses(queue)

    for row in queue:
        if not _backoff_ready(row, now):
            report.deferred += 1
            continue

        to = row.recipient_email or addresses.get(row.recipient_user_id or -1, "")
        if not to:
            _fail(row, "No email address on record for this recipient.",
                  max_attempts)
            report.failed += 1
            continue

        if not _claim(row):
            report.deferred += 1
            continue

        try:
            send_mail(
                subject=row.subject, message=row.body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[to], fail_silently=False,
            )
        except Exception as exc:                               # noqa: BLE001
            _fail(row, f"{exc.__class__.__name__}: {exc}"[:300], max_attempts)
            report.failed += 1
            continue

        row.status = "sent"
        row.sent_at = timezone.now()
        row.attempts += 1
        row.last_error = ""
        row.claimed_at = None
        row.save(update_fields=["status", "sent_at", "attempts", "last_error",
                                "claimed_at", "updated_at"])
        report.sent += 1
    return report
