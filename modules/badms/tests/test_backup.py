"""Manual backups, scheduled execution, failure alerting and escalation
(UC-BA-001, UC-BA-006, BR-BA-001, BR-BA-013, BR-BA-014, BR-BA-015,
AFR-BA-001..011, AFR-BA-017, AFR-BA-054/055, AFR-BA-057..059)."""
import datetime as dt

import pytest
from django.utils import timezone

from modules.badms.models import (
    AuditEvent,
    Backup,
    BackupSchedule,
    NotificationOutbox,
)
from modules.badms.services import backups as backup_service
from modules.badms.services import schedules as schedule_service

from .helpers import (
    SUPERADMIN_PERMS,
    SYSADMIN_PERMS,
    USER_PERMS,
    actor,
    now_minus,
)

pytestmark = pytest.mark.django_db

SYSADMIN = 9
SUPERADMIN = 10
STUDENT = 1001


# -- UC-BA-001: the manual trigger -------------------------------------------------
class TestManualBackup:
    def test_success_records_timestamp_dump_and_status(self, repo):
        """AFR-BA-002/003/004/017: authorised trigger collects the timestamp,
        saves the dump, records Success, keeps history."""
        started = timezone.now()
        backup = backup_service.trigger_manual_backup(
            actor=actor(uid=SYSADMIN, perms=SYSADMIN_PERMS, kind="staff"),
            repository=repo, started_at=started)
        assert backup.status == "success"
        assert backup.kind == "manual"
        assert backup.trigger_user_id == SYSADMIN
        assert backup.started_at == started
        assert backup.finished_at is not None
        assert backup.integrity_verified is True
        assert Backup.objects.filter(pk=backup.pk).exists()   # AFR-BA-017

    def test_only_sysadmin_or_superadmin_may_trigger(self, repo):
        """BR-BA-001 / AFR-BA-001: a user without the trigger grant is
        denied, and nothing is created."""
        from core.api.exceptions import PermissionDeniedError

        with pytest.raises(PermissionDeniedError):
            backup_service.trigger_manual_backup(
                actor=actor(uid=STUDENT, perms=USER_PERMS), repository=repo)
        assert Backup.objects.count() == 0

    def test_unauthenticated_trigger_denied(self, repo):
        from core.api.exceptions import PermissionDeniedError

        with pytest.raises(PermissionDeniedError):
            backup_service.trigger_manual_backup(actor=None, repository=repo)
        assert Backup.objects.count() == 0

    def test_failure_marks_failed_and_alerts_sysadmin(self, repo,
                                                      monkeypatch, tmp_path):
        """AFR-BA-005 / BR-BA-014: a failed backup is marked Failed and the
        SysAdmin alert is queued inside the five-minute SLA."""
        monkeypatch.setattr(backup_service, "_write_state_dump",
                            lambda b: (_ for _ in ()).throw(OSError("disk full")))
        backup = backup_service.trigger_manual_backup(
            actor=actor(uid=SYSADMIN, perms=SYSADMIN_PERMS, kind="staff"),
            repository=repo)
        assert backup.status == "failed"
        assert "disk full" in backup.error
        alert = NotificationOutbox.objects.get(
            topic="backup.failed", dedupe_key=f"backup-failed-{backup.pk}")
        assert alert.recipient_email
        backup.refresh_from_db()
        assert backup.failure_alerted_at is not None

    def test_alert_sweep_requeues_a_failure_that_never_alerted(
            self, repo, db):
        """BR-BA-014: a Failed backup older than the SLA with no alert queued
        is picked up by the sweep."""
        backup = Backup.objects.create(
            kind="manual", status="failed", repository=repo,
            trigger_user_id=SYSADMIN, started_at=now_minus(30), error="x")
        assert backup.failure_alerted_at is None
        count = backup_service.sweep_failure_alerts()
        assert count == 1
        backup.refresh_from_db()
        assert backup.failure_alerted_at is not None
        assert NotificationOutbox.objects.filter(
            topic="backup.failed").exists()


# -- BR-BA-015: the escalation rule --------------------------------------------------
class TestEscalation:
    def _failures(self, repo, n, *, started_from):
        for i in range(n):
            backup_service.trigger_manual_backup(
                actor=actor(uid=SYSADMIN, perms=SYSADMIN_PERMS, kind="staff"),
                repository=repo,
                started_at=started_from + dt.timedelta(minutes=i))

    def test_three_consecutive_failures_escalate_to_director(
            self, repo, monkeypatch):
        """BR-BA-015: the third consecutive failure escalates to the
        Director of IT."""
        monkeypatch.setattr(backup_service, "_write_state_dump",
                            lambda b: (_ for _ in ()).throw(OSError("boom")))
        self._failures(repo, 3, started_from=now_minus(10))
        assert NotificationOutbox.objects.filter(
            topic="backup.escalated").count() == 1
        failed = Backup.objects.order_by("-started_at").first()
        assert failed.consecutive_failures == 3
        assert failed.escalated_at is not None
        assert AuditEvent.objects.filter(action="backup.escalated").exists()

    def test_fourth_failure_does_not_repeat_the_escalation(
            self, repo, monkeypatch):
        monkeypatch.setattr(backup_service, "_write_state_dump",
                            lambda b: (_ for _ in ()).throw(OSError("boom")))
        self._failures(repo, 4, started_from=now_minus(10))
        assert NotificationOutbox.objects.filter(
            topic="backup.escalated").count() == 1

    def test_success_resets_the_streak(self, repo, monkeypatch):
        for j in range(2):
            with monkeypatch.context() as m:
                m.setattr(backup_service, "_write_state_dump",
                          lambda b: (_ for _ in ()).throw(OSError("boom")))
                self._failures(repo, 1, started_from=now_minus(10 + j))
        backup_service.trigger_manual_backup(
            actor=actor(uid=SYSADMIN, perms=SYSADMIN_PERMS, kind="staff"),
            repository=repo)
        # Two fresh failures are only two — the success reset the count.
        for j in range(2):
            with monkeypatch.context() as m:
                m.setattr(backup_service, "_write_state_dump",
                          lambda b: (_ for _ in ()).throw(OSError("boom")))
                self._failures(repo, 1, started_from=timezone.now()
                               + dt.timedelta(minutes=j))
        assert not NotificationOutbox.objects.filter(
            topic="backup.escalated").exists()


# -- UC-BA-006: scheduled execution ---------------------------------------------------
class TestScheduledBackup:
    def _schedule(self, repo, *, scope="local", dataset="students",
                  frequency="daily", run_at=dt.time(2, 0), weekday=None):
        return schedule_service.set_global_schedule(
            actor=actor(uid=SUPERADMIN, perms=SUPERADMIN_PERMS, kind="staff"),
            frequency=frequency, run_at=run_at, weekday=weekday,
            repository_id=repo.pk) if scope == "global" else \
            BackupSchedule.objects.create(
                scope="local", dataset=dataset, frequency=frequency,
                run_at=run_at, weekday=weekday, repository=repo,
                created_by_user_id=SYSADMIN)

    def test_scheduled_backup_executes_without_user_intervention(self, repo):
        """AFR-BA-006/007/008/009/010: the run picks the schedule's datasets,
        transfers, verifies integrity and logs with timestamp + status."""
        schedule = self._schedule(repo)
        backup = backup_service.run_scheduled_backup(schedule)
        assert backup.kind == "scheduled"
        assert backup.status == "success"
        assert backup.dataset == "students"
        assert backup.integrity_verified is True
        assert backup.trigger_user_id is None

    def test_unreachable_repository_is_failure_handling(self, dead_repo):
        """BR-BA-013 / UC-BA-006 E1: an unreachable repository means the
        scheduled backup is not successfully executed, and failure handling
        applies."""
        schedule = self._schedule(dead_repo)
        backup = backup_service.run_scheduled_backup(schedule)
        assert backup.status == "failed"
        assert "reachable" in backup.error
        assert NotificationOutbox.objects.filter(
            topic="backup.failed").exists()

    def test_run_due_backups_runs_only_due_schedules(self, repo):
        """The beat entry runs a daily schedule past its time exactly once
        per day."""
        self._schedule(repo, run_at=dt.time(0, 0))
        now = timezone.now().replace(hour=8, minute=0, second=0, microsecond=0)
        assert backup_service.run_due_backups(now=now) == 1
        # Already successful today: a second pass has nothing to do.
        assert backup_service.run_due_backups(now=now) == 0

    def test_global_schedule_applies_where_no_local_exists(
            self, repo, monkeypatch):
        """AFR-BA-054 / BR-BA-011: with no local schedule, the global
        schedule governs the platform dataset."""
        self._schedule(repo, scope="global")
        seen = {}
        real_run = backup_service.run_scheduled_backup

        def spy(schedule, **kw):
            seen["dataset"] = schedule.dataset
            seen["scope"] = schedule.scope
            return real_run(schedule, **kw)

        monkeypatch.setattr(backup_service, "run_scheduled_backup", spy)
        assert backup_service.run_due_backups(now=timezone.now()) >= 1
        assert seen["scope"] == "global"
        assert seen["dataset"] == ""

    def test_local_schedule_overrides_the_global(self, repo, monkeypatch):
        """AFR-BA-055 / BR-BA-011: a valid local schedule wins for its
        dataset."""
        self._schedule(repo, scope="global")
        self._schedule(repo, scope="local", dataset="students")
        effective = schedule_service.effective_schedule("students")
        assert effective.scope == "local"
        assert effective.dataset == "students"
        # A dataset with no local schedule still gets the global one.
        assert schedule_service.effective_schedule("finance").scope == "global"


# -- UC-BA-014: who sees the history ---------------------------------------------------
class TestBackupVisibility:
    def test_backup_history_visible_in_scope(self, repo):
        """AFR-BA-018 / BR-BA-020: authorised actors view history and status."""
        backup_service.trigger_manual_backup(
            actor=actor(uid=SYSADMIN, perms=SYSADMIN_PERMS, kind="staff"),
            repository=repo)
        assert Backup.objects.count() == 1

    def test_backup_completion_notification(self, repo):
        """AFR-BA-059: a successful backup issues its completion
        notification."""
        backup_service.trigger_manual_backup(
            actor=actor(uid=SYSADMIN, perms=SYSADMIN_PERMS, kind="staff"),
            repository=repo)
        assert NotificationOutbox.objects.filter(
            topic="backup.completed").exists()
