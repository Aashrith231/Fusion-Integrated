"""Local schedule management and the global default (UC-BA-009, UC-BA-011,
BR-BA-011, BR-BA-012, BR-BA-019, AFR-BA-012..016, AFR-BA-053..055)."""
import datetime as dt

import pytest
from django.utils import timezone

from core.api.exceptions import DomainError
from modules.badms.domain import rules as schedule_rules
from modules.badms.models import BackupSchedule, ScheduleChangeLog
from modules.badms.services import schedules as schedule_service

from .helpers import SUPERADMIN_PERMS, SYSADMIN_PERMS, USER_PERMS, actor

pytestmark = pytest.mark.django_db

SYSADMIN = 9
SUPERADMIN = 10
STUDENT = 1001
NOON = dt.time(12, 0)


def _sysadmin():
    return actor(uid=SYSADMIN, perms=SYSADMIN_PERMS, kind="staff")


def _superadmin():
    return actor(uid=SUPERADMIN, perms=SUPERADMIN_PERMS, kind="staff")


def _student():
    return actor(uid=STUDENT, perms=USER_PERMS)


class TestScheduleValidation:
    def test_create_local_schedule_applies_and_logs(self, repo):
        """AFR-BA-013/015/016: a valid schedule is applied and its change is
        logged."""
        schedule = schedule_service.create_local_schedule(
            actor=_sysadmin(), dataset="students", frequency="daily",
            run_at=NOON, repository_id=repo.pk)
        assert schedule.scope == "local"
        assert schedule.dataset == "students"
        log = ScheduleChangeLog.objects.get(schedule=schedule)
        assert log.action == "create"

    def test_invalid_frequency_rejected_without_applying(self, repo):
        """BR-BA-012 / AFR-BA-014: an invalid configuration is rejected and
        nothing is applied."""
        with pytest.raises(DomainError):
            schedule_service.create_local_schedule(
                actor=_sysadmin(), dataset="students", frequency="hourly",
                run_at=NOON, repository_id=repo.pk)
        assert BackupSchedule.objects.count() == 0

    def test_unknown_classification_filter_rejected(self, repo):
        with pytest.raises(DomainError):
            schedule_service.create_local_schedule(
                actor=_sysadmin(), dataset="students", frequency="daily",
                run_at=NOON,
                classification_filter=["secret"], repository_id=repo.pk)
        assert BackupSchedule.objects.count() == 0

    def test_conflicting_schedule_rejected_and_existing_kept(self, repo):
        """BR-BA-012: a conflicting configuration is rejected and the
        existing effective schedule is preserved."""
        first = schedule_service.create_local_schedule(
            actor=_sysadmin(), dataset="students", frequency="daily",
            run_at=NOON, repository_id=repo.pk)
        with pytest.raises(DomainError):
            schedule_service.create_local_schedule(
                actor=_sysadmin(), dataset="students", frequency="daily",
                run_at=NOON, repository_id=repo.pk)
        assert BackupSchedule.objects.count() == 1
        assert BackupSchedule.objects.get().pk == first.pk

    def test_nearby_runs_conflict_but_distant_days_do_not(self, repo):
        schedule_service.create_local_schedule(
            actor=_sysadmin(), dataset="students", frequency="daily",
            run_at=NOON, repository_id=repo.pk)
        # Half an hour away, same daily pattern: a conflict.
        with pytest.raises(DomainError):
            schedule_service.create_local_schedule(
                actor=_sysadmin(), dataset="students", frequency="daily",
                run_at=dt.time(12, 30), repository_id=repo.pk)
        # A different dataset is never a conflict.
        schedule_service.create_local_schedule(
            actor=_sysadmin(), dataset="finance", frequency="daily",
            run_at=NOON, repository_id=repo.pk)
        assert BackupSchedule.objects.count() == 2

    def test_modify_validates_again_and_logs(self, repo):
        """UC-BA-009 A2 / E1: modification runs the same rules and an invalid
        change leaves the schedule untouched."""
        schedule = schedule_service.create_local_schedule(
            actor=_sysadmin(), dataset="students", frequency="daily",
            run_at=NOON, repository_id=repo.pk)
        schedule_service.modify_local_schedule(
            actor=_sysadmin(), schedule_id=schedule.pk,
            run_at=dt.time(15, 0))
        schedule.refresh_from_db()
        assert schedule.run_at == dt.time(15, 0)
        assert ScheduleChangeLog.objects.filter(
            schedule=schedule, action="modify").count() == 1
        with pytest.raises(DomainError):
            schedule_service.modify_local_schedule(
                actor=_sysadmin(), schedule_id=schedule.pk, frequency="hourly")
        schedule.refresh_from_db()
        assert schedule.frequency == "daily"

    def test_only_authorized_sysadmin_manages_local_schedules(self, repo):
        """AFR-BA-012/013: unauthorized actors are denied."""
        with pytest.raises(DomainError):
            schedule_service.create_local_schedule(
                actor=_student(), dataset="students", frequency="daily",
                run_at=NOON, repository_id=repo.pk)
        assert BackupSchedule.objects.count() == 0

    def test_weekly_schedule_needs_a_weekday(self, repo):
        from modules.badms.domain.rules import ScheduleInvalid
        with pytest.raises(ScheduleInvalid):
            schedule_rules.validate_parameters(frequency="weekly",
                                               run_at=NOON,
                                               classification_filter=None)


class TestGlobalSchedule:
    def test_global_schedule_applies_when_no_local_exists(self, repo):
        """AFR-BA-054: the global schedule covers datasets without a local
        override."""
        schedule_service.set_global_schedule(
            actor=_superadmin(), frequency="daily", run_at=dt.time(2, 0),
            repository_id=repo.pk)
        effective = schedule_service.effective_schedule("anything")
        assert effective.scope == "global"

    def test_local_overrides_global(self, repo):
        """AFR-BA-055 / BR-BA-011: precedence of the local schedule."""
        schedule_service.set_global_schedule(
            actor=_superadmin(), frequency="daily", run_at=dt.time(2, 0),
            repository_id=repo.pk)
        schedule_service.create_local_schedule(
            actor=_sysadmin(), dataset="students", frequency="weekly",
            run_at=dt.time(3, 0), weekday=0, repository_id=repo.pk)
        assert schedule_service.effective_schedule("students").scope == "local"
        assert schedule_service.effective_schedule("other").scope == "global"

    def test_only_super_admin_defines_the_global_schedule(self, repo):
        """BR-BA-019 / AFR-BA-053: the global grant belongs to the Super
        Admin alone."""
        with pytest.raises(DomainError):
            schedule_service.set_global_schedule(
                actor=_sysadmin(), frequency="daily", run_at=dt.time(2, 0),
                repository_id=repo.pk)
        with pytest.raises(DomainError):
            schedule_service.set_global_schedule(
                actor=_student(), frequency="daily", run_at=dt.time(2, 0),
                repository_id=repo.pk)
        assert BackupSchedule.objects.filter(scope="global").count() == 0

    def test_global_update_keeps_one_row_and_logs(self, repo):
        """UC-BA-011: defining then updating keeps a single global row, each
        change logged."""
        first = schedule_service.set_global_schedule(
            actor=_superadmin(), frequency="daily", run_at=dt.time(2, 0),
            repository_id=repo.pk)
        second = schedule_service.set_global_schedule(
            actor=_superadmin(), frequency="weekly", run_at=dt.time(3, 0),
            weekday=6, repository_id=repo.pk)
        assert first.pk == second.pk
        assert ScheduleChangeLog.objects.filter(
            schedule=first.pk).count() == 2
        assert second.frequency == "weekly"

    def test_invalid_global_configuration_rejected(self, repo):
        """UC-BA-011 E1: an invalid configuration is rejected and the prior
        global configuration stays effective."""
        schedule_service.set_global_schedule(
            actor=_superadmin(), frequency="daily", run_at=dt.time(2, 0),
            repository_id=repo.pk)
        with pytest.raises(DomainError):
            schedule_service.set_global_schedule(
                actor=_superadmin(), frequency="hourly",
                run_at=dt.time(2, 0), repository_id=repo.pk)
        row = BackupSchedule.objects.filter(scope="global").get()
        assert row.frequency == "daily"


class TestDueRules:
    def test_daily_due_after_run_at(self, repo):
        from modules.badms.domain import rules
        schedule = BackupSchedule.objects.create(
            scope="local", dataset="d", frequency="daily", run_at=dt.time(2, 0),
            repository=repo, created_by_user_id=1)
        now = timezone.now().replace(hour=3, minute=0, second=0, microsecond=0)
        assert rules.is_due(schedule, now=now, last_success_for_dataset=None)
        # A success from today means it already ran.
        success_at = now.replace(hour=2, minute=30)
        assert not rules.is_due(schedule, now=now,
                                last_success_for_dataset=success_at)
        # Before the scheduled time: not due.
        early = now.replace(hour=1, minute=0)
        assert not rules.is_due(schedule, now=early,
                                last_success_for_dataset=None)

    def test_weekly_due_only_on_its_weekday(self, repo):
        from modules.badms.domain import rules
        schedule = BackupSchedule.objects.create(
            scope="local", dataset="d", frequency="weekly", run_at=NOON,
            weekday=0, repository=repo, created_by_user_id=1)  # Monday
        monday = timezone.datetime(2026, 8, 3, 13, 0,
                                   tzinfo=dt.UTC)
        friday = timezone.datetime(2026, 8, 7, 13, 0, tzinfo=dt.UTC)
        assert rules.is_due(schedule, now=monday,
                            last_success_for_dataset=None)
        assert not rules.is_due(schedule, now=friday,
                                last_success_for_dataset=None)
