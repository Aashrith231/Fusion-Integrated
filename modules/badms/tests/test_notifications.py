"""Notification queue decisions and delivery (UC-BA-013, BR-BA-014).

The queue must be idempotent (dedupe key), survive a broken mail server,
reclaim stranded claims and never send one notification twice.
"""
import datetime as dt

import pytest
from django.utils import timezone

from modules.badms.models import NotificationOutbox
from modules.badms.services import notifications

pytestmark = pytest.mark.django_db

ROW = {"topic": "backup.completed", "subject": "Backup done", "body": "ok"}


def enqueue(**over):
    return notifications.enqueue(dedupe_key="d1", recipient_email="a@x.y",
                                 **{**ROW, **over})


def test_enqueue_rows_and_dedupes():
    assert enqueue().pk
    assert enqueue() is None, "the same dedupe key must not enqueue twice"
    assert NotificationOutbox.objects.count() == 1


def test_enqueue_rejects_unknown_topic():
    with pytest.raises(ValueError):
        notifications.enqueue(dedupe_key="d2", recipient_email="a@x.y",
                              topic="not-a-topic", subject="s", body="b")


def test_enqueue_rejects_recipientless():
    with pytest.raises(ValueError):
        notifications.enqueue(dedupe_key="d3", topic="backup.completed",
                          subject="s", body="b")


def test_deliver_sends_and_marks_sent(monkeypatch):
    row = enqueue()
    sent = []
    monkeypatch.setattr(notifications, "send_mail",
                        lambda **kw: sent.append(kw["recipient_list"]))
    report = notifications.deliver_pending()
    assert report.sent == 1 and report.failed == 0
    row.refresh_from_db()
    assert row.status == "sent" and sent == [["a@x.y"]]


def test_deliver_failure_keeps_row_pending_with_backoff(monkeypatch):
    row = enqueue()

    def boom(**kw):
        raise ConnectionError("smtp down")

    monkeypatch.setattr(notifications, "send_mail", boom)
    report = notifications.deliver_pending()
    assert report.failed == 1
    row.refresh_from_db()
    assert row.status == "pending" and row.attempts == 1

    # Inside the backoff window: deferred, not re-sent.
    later = row.updated_at + dt.timedelta(seconds=30)
    report = notifications.deliver_pending(now=later)
    assert report.deferred == 1 and report.sent == 0


def test_deliver_gives_up_after_max_attempts(monkeypatch):
    row = enqueue()
    monkeypatch.setattr(notifications, "send_mail",
                        lambda **kw: (_ for _ in ()).throw(ConnectionError("x")))
    for _ in range(5):
        notifications.deliver_pending(now=timezone.now()
                                      + dt.timedelta(days=row.attempts))
        row.refresh_from_db()
    assert row.status == "failed"


def test_deliver_reports_recipient_without_address(monkeypatch):
    row = notifications.enqueue(dedupe_key="d4", topic="backup.completed",
                                subject="s", body="b",
                                recipient_user_id=99999)
    monkeypatch.setattr(notifications, "send_mail", lambda **kw: None)
    report = notifications.deliver_pending()
    assert report.failed == 1
    row.refresh_from_db()
    assert "No email address" in row.last_error


def test_deliver_resolves_user_addresses_from_the_projection(monkeypatch):
    from django.apps import apps
    user_ref = apps.get_model("directory", "UserRef")
    user_ref.objects.create(user_id=4242, username="u4242",
                            display_name="U", kind="staff",
                            email="u4242@iiitdmj.ac.in")
    notifications.enqueue(dedupe_key="d5", topic="backup.completed",
                          subject="s", body="b", recipient_user_id=4242)
    sent = []
    monkeypatch.setattr(notifications, "send_mail",
                        lambda **kw: sent.append(kw["recipient_list"]))
    report = notifications.deliver_pending()
    assert report.sent == 1 and sent == [["u4242@iiitdmj.ac.in"]]


def test_a_broken_projection_does_not_stop_delivery(monkeypatch):
    notifications.enqueue(dedupe_key="d6", topic="backup.completed",
                          subject="s", body="b", recipient_user_id=7)
    monkeypatch.setattr(notifications.directory, "get_users",
                        lambda ids: (_ for _ in ()).throw(RuntimeError("db")))
    report = notifications.deliver_pending()
    assert report.failed == 1 and report.sent == 0


def test_two_workers_never_send_one_row_twice(monkeypatch):
    """The conditional claim means the second worker sees nothing to send."""
    enqueue()
    monkeypatch.setattr(notifications, "send_mail", lambda **kw: None)
    first = notifications.deliver_pending()
    second = notifications.deliver_pending()
    assert first.sent == 1 and second.sent == 0


def test_stranded_claims_are_reclaimed():
    row = enqueue()
    now = timezone.now()
    NotificationOutbox.objects.filter(pk=row.pk).update(
        status="sending", claimed_at=now - dt.timedelta(minutes=11))
    report = notifications.deliver_pending(now=now)
    assert report.deferred + report.sent + report.failed == 1
    row.refresh_from_db()
    assert row.status in ("sent", "pending"), "the row left `sending`"
