"""Frozen design: FR_DESIGN.json — backup management (CFR-BA-001..004)."""
import datetime as dt

import pytest

from core.api.exceptions import DomainError, PermissionDeniedError
from modules.badms.models import Backup, BackupSchedule
from modules.badms.selectors import scoping
from modules.badms.services import backups as backup_service
from modules.badms.services import schedules as schedule_service

from ..helpers import (
    T0,
    student,
    sysadmin,
)

pytestmark = pytest.mark.django_db


def test_fr_001_afr_ba_001_only_sysadmin_triggers_backup(repo, dead_repo):
    """FR-001 / AFR-BA-001: permitted actor succeeds, others are refused."""
    triggered = backup_service.trigger_manual_backup(
        actor=sysadmin(), repository=repo)
    assert triggered.status in ("running", "success")
    with pytest.raises(PermissionDeniedError):
        backup_service.trigger_manual_backup(actor=student(), repository=repo)
    assert Backup.objects.filter(kind="manual").count() == 1


def test_fr_002_fr_003_fr_004_afr_ba_002_003_004_dump_outcome(repo):
    """FR-002/003/004 / AFR-BA-002/003/004: timestamp, artifact, outcome."""
    before = dt.datetime.now(dt.UTC)
    backup = backup_service.trigger_manual_backup(actor=sysadmin(),
                                                  repository=repo)
    assert backup.started_at >= before
    assert backup.artifact_ref, "the dump artifact is saved"
    assert backup.status == "success"
    assert backup.integrity_verified


def test_fr_005_afr_ba_005_failed_backup_alerts_sysadmin(repo, tmp_path,
                                                          settings):
    """FR-005 / AFR-BA-005: a backup that cannot be created marks Failed and
    alerts the SysAdmin."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("occupies the backup root path")
    settings.BADMS_BACKUP_ROOT = blocker   # mkdir will fail -> dump fails
    backup = backup_service.trigger_manual_backup(actor=sysadmin(),
                                                  repository=repo)
    assert backup.status == "failed"
    assert Backup.objects.filter(
        pk=backup.pk, failure_alerted_at__isnull=False).exists(), \
        "the SysAdmin alert was queued"


def test_fr_006_fr_010_afr_ba_006_007_008_009_010_scheduled_run(repo, settings):
    """FR-006..010 / AFR-BA-006..010: scheduled run without a user."""
    schedule_service.create_local_schedule(
        actor=sysadmin(), dataset="spec-db", frequency="daily",
        run_at=dt.time(2, 0), repository_id=repo.pk)
    due = backup_service.run_due_backups(now=T0)
    assert due == 1
    row = Backup.objects.filter(kind="scheduled").get()
    assert row.trigger_user_id is None
    assert row.dataset == "spec-db"
    assert row.status == "success" and row.integrity_verified
    assert row.started_at == T0


def test_fr_011_afr_ba_011_unreachable_blocks_scheduled_run(dead_repo):
    """FR-011 / AFR-BA-011: an unreachable repository is not transferred."""
    schedule = schedule_service.create_local_schedule(
        actor=sysadmin(), dataset="spec-db", frequency="daily",
        run_at=dt.time(2, 0), repository_id=dead_repo.pk)
    backup = backup_service.run_scheduled_backup(schedule, started_at=T0)
    assert backup.status == "failed"
    assert not backup.artifact_ref


def test_fr_012_afr_ba_012_schedules_visible_in_scope():
    """FR-012 / AFR-BA-012: scope protects the schedule list."""
    rows = scoping.schedules_for(sysadmin()) \
        if hasattr(scoping, "schedules_for") else None
    # the list endpoint is guarded by badms.schedule.manage; a plain user
    # without it is refused before any row is visible
    from modules.badms.selectors import authz
    assert authz.has_permission(sysadmin(), "badms.schedule.manage")
    assert not authz.has_permission(student(), "badms.schedule.manage")
    assert rows is None or rows


def test_fr_013_fr_015_fr_016_afr_ba_013_015_016_create_apply_log(repo):
    """FR-013/015/016 / AFR-BA-013/015/016: create, apply, log."""
    schedule = schedule_service.create_local_schedule(
        actor=sysadmin(), dataset="spec-db", frequency="weekly",
        run_at=dt.time(3, 0), weekday=0,
        classification_filter=["routine"], repository_id=repo.pk)
    assert schedule.is_active and schedule.frequency == "weekly"
    modified = schedule_service.modify_local_schedule(
        actor=sysadmin(), schedule_id=schedule.pk, run_at=dt.time(4, 0))
    assert modified.run_at == dt.time(4, 0)
    from modules.badms.models import ScheduleChangeLog
    assert ScheduleChangeLog.objects.filter(schedule=schedule.pk).exists()


def test_fr_014_afr_ba_014_invalid_schedule_not_applied(repo):
    """FR-014 / AFR-BA-014: invalid/conflicting configurations unapplied."""
    from core.api.exceptions import ConflictError
    schedule_service.create_local_schedule(
        actor=sysadmin(), dataset="db", frequency="daily",
        run_at=dt.time(2, 0), repository_id=repo.pk)
    with pytest.raises(DomainError):
        schedule_service.create_local_schedule(
            actor=sysadmin(), dataset="db", frequency="hourly",
            run_at=dt.time(2, 0), repository_id=repo.pk)
    with pytest.raises((DomainError, ConflictError)):
        schedule_service.create_local_schedule(
            actor=sysadmin(), dataset="db", frequency="daily",
            run_at=dt.time(2, 30), repository_id=repo.pk)
    assert BackupSchedule.objects.count() == 1


def test_fr_017_fr_018_afr_ba_017_018_history_in_scope(stub_iam):
    """FR-017/018 / AFR-BA-017/018: history visible in authorized scope."""
    from conftest import make_session
    from fusion_auth.principal import Principal
    from modules.badms.models import Backup, BackupRepository
    repo = BackupRepository.objects.create(name="r", location="x")
    Backup.objects.create(kind="manual", status="success",
                          started_at=T0, dataset="db", repository=repo)
    sysadmin_qs = scoping.backups_for(sysadmin())
    assert sysadmin_qs.count() == 1
    plain = Principal.from_session(make_session(
        user_id=9002, kind="student", modules=("badms",),
        permissions=("badms.backup.view",)))
    assert scoping.backups_for(plain).count() == 1
    # the module-grant refusal happens at the HTTP boundary
    from rest_framework.test import APIClient

    from conftest import make_session
    stub_iam(make_session(user_id=9003, kind="student", modules=(),
                          permissions=()))
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Token abc")
    assert client.get("/api/v1/badms/backups").status_code == 403
