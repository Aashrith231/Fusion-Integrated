"""Frozen design: UC_DESIGN.json — every use case's main flow and its
explicitly specified alternatives."""
import datetime as dt

import pytest

from core.api.exceptions import ConflictError, DomainError
from modules.badms.models import (
    ArchivalRequest,
    Backup,
    NotificationOutbox,
    SpecialArchivalRecord,
)
from modules.badms.selectors import scoping
from modules.badms.services import archival as archival_service
from modules.badms.services import backups as backup_service
from modules.badms.services import restoration as restoration_service
from modules.badms.services import schedules as schedule_service
from modules.badms.services import security as security_service
from modules.badms.services import special as special_service
from modules.badms.services import storage as storage_service

from ..helpers import (
    DEPT,
    T0,
    give_department,
    hod,
    itsec,
    make_archival,
    student,
    super_admin,
    sysadmin,
)

pytestmark = pytest.mark.django_db


def test_uc_001_ba_uc_001_main_flow(repo):
    """UC-001 / BA-UC-001 Main Flow: manual backup succeeds."""
    backup = backup_service.trigger_manual_backup(actor=sysadmin(),
                                                  repository=repo)
    assert backup.status == "success"


def test_uc_002_ba_uc_001_alternative_no_repository(settings):
    """UC-002 / BA-UC-001 Alternative: no repository configured."""
    from modules.badms.models import BackupRepository
    BackupRepository.objects.all().delete()
    with pytest.raises(ValueError):
        backup_service.trigger_manual_backup(actor=sysadmin())
    assert Backup.objects.count() == 0


def test_uc_003_ba_uc_002_main_flow():
    """UC-003 / BA-UC-002 Main Flow: submission routed to the HoD."""
    owner = student()
    give_department(owner.user_id, DEPT)
    hod(dept=DEPT)
    request = archival_service.submit_request(
        actor=owner, file_name="a.pdf", file_date=dt.date(2026, 8, 1),
        owners="O", file_type="pdf", reason="r", attachment="a://x")
    assert request.status == "submitted"


def test_uc_004_ba_uc_002_alternative_quota_exceeded():
    """UC-004 / BA-UC-002 Alternative: quota-exceeded submission refused.

    The quota gate lives in the storage profile; a request whose attachment
    size exceeds the remaining quota is refused (AFR-BA-021).
    """
    owner = student()
    storage_service.ensure_profile(user_id=owner.user_id)
    storage_service.record_usage(user_id=owner.user_id, used_bytes=1000,
                                 quota_bytes=1000)
    with pytest.raises(DomainError):
        archival_service.submit_request(
            actor=owner, file_name="a.pdf", file_date=dt.date(2026, 8, 1),
            owners="O", file_type="pdf", reason="r",
            attachment="a://x", attachment_size_bytes=9999)
    assert ArchivalRequest.objects.count() == 0


def test_uc_005_ba_uc_003_main_flow():
    """UC-005 / BA-UC-003 Main Flow: HoD approval."""
    owner = student()
    give_department(owner.user_id, DEPT)
    request = archival_service.submit_request(
        actor=owner, file_name="a.pdf", file_date=dt.date(2026, 8, 1),
        owners="O", file_type="pdf", reason="r", attachment="a://x")
    decided = archival_service.decide_request(actor=hod(dept=DEPT),
                                              request_id=request.pk,
                                              decision="approve")
    assert decided.status == "hod_approved"


def test_uc_006_ba_uc_003_alternative_rejection():
    """UC-006 / BA-UC-003 Alternative: HoD rejection + notification."""
    owner = student()
    give_department(owner.user_id, DEPT)
    request = archival_service.submit_request(
        actor=owner, file_name="a.pdf", file_date=dt.date(2026, 8, 1),
        owners="O", file_type="pdf", reason="r", attachment="a://x")
    decided = archival_service.decide_request(actor=hod(dept=DEPT),
                                              request_id=request.pk,
                                              decision="reject")
    assert decided.status == "rejected"
    assert NotificationOutbox.objects.filter(
        recipient_user_id=owner.user_id, topic="archival.decided").exists()


def test_uc_007_ba_uc_004_main_flow_routine():
    """UC-007 / BA-UC-004 Main Flow: classify Routine."""
    owner = student()
    give_department(owner.user_id, DEPT)
    request = archival_service.submit_request(
        actor=owner, file_name="a.pdf", file_date=dt.date(2026, 8, 1),
        owners="O", file_type="pdf", reason="r", attachment="a://x")
    archival_service.decide_request(actor=hod(dept=DEPT),
                                    request_id=request.pk,
                                    decision="approve")
    classified = archival_service.classify_request(
        actor=sysadmin(), request_id=request.pk, classification="routine")
    assert classified.status == "classified" and classified.retention_rule


def test_uc_008_ba_uc_004_alternative_sensitive():
    """UC-008 / BA-UC-004 Alternative: Sensitive routes to IT Security."""
    owner = student()
    give_department(owner.user_id, DEPT)
    request = archival_service.submit_request(
        actor=owner, file_name="a.pdf", file_date=dt.date(2026, 8, 1),
        owners="O", file_type="pdf", reason="r", attachment="a://x")
    archival_service.decide_request(actor=hod(dept=DEPT),
                                    request_id=request.pk,
                                    decision="approve")
    classified = archival_service.classify_request(
        actor=sysadmin(), request_id=request.pk, classification="sensitive")
    assert classified.status == "routed_to_security"


def test_uc_009_ba_uc_005_main_flow(tmp_path, settings):
    """UC-009 / BA-UC-005 Main Flow: encryption configured."""
    owner = student()
    give_department(owner.user_id, DEPT)
    request = archival_service.submit_request(
        actor=owner, file_name="a.pdf", file_date=dt.date(2026, 8, 1),
        owners="O", file_type="pdf", reason="r", attachment="a://x")
    archival_service.decide_request(actor=hod(dept=DEPT),
                                    request_id=request.pk,
                                    decision="approve")
    archival_service.classify_request(actor=sysadmin(),
                                      request_id=request.pk,
                                      classification="sensitive")
    settings.BADMS_ARCHIVE_ROOT = tmp_path
    encrypted = archival_service.configure_encryption(
        actor=itsec(), request_id=request.pk, key_ref="uc-key")
    assert encrypted.status == "encrypted"
    assert "AES-256" in encrypted.encryption_algorithm


def test_uc_010_ba_uc_005_alternative_failure(tmp_path, settings):
    """UC-010 / BA-UC-005 Alternative: encryption failure recorded."""
    owner = student()
    give_department(owner.user_id, DEPT)
    request = archival_service.submit_request(
        actor=owner, file_name="a.pdf", file_date=dt.date(2026, 8, 1),
        owners="O", file_type="pdf", reason="r", attachment="a://x")
    archival_service.decide_request(actor=hod(dept=DEPT),
                                    request_id=request.pk,
                                    decision="approve")
    archival_service.classify_request(actor=sysadmin(),
                                      request_id=request.pk,
                                      classification="sensitive")
    blocker = tmp_path / "occupied"
    blocker.write_text("x")
    settings.BADMS_ARCHIVE_ROOT = blocker
    with pytest.raises(ConflictError):
        archival_service.configure_encryption(actor=itsec(),
                                              request_id=request.pk,
                                              key_ref="k")
    request.refresh_from_db()
    assert request.status == "encryption_failed"


def test_uc_011_ba_uc_006_main_flow(repo):
    """UC-011 / BA-UC-006 Main Flow: scheduled backup executes."""
    schedule_service.create_local_schedule(
        actor=sysadmin(), dataset="uc-db", frequency="daily",
        run_at=dt.time(2, 0), repository_id=repo.pk)
    assert backup_service.run_due_backups(now=T0) == 1
    assert Backup.objects.filter(kind="scheduled", status="success").exists()


def test_uc_012_ba_uc_006_alternative_unreachable(dead_repo):
    """UC-012 / BA-UC-006 Alternative: unreachable repository."""
    schedule = schedule_service.create_local_schedule(
        actor=sysadmin(), dataset="uc-db", frequency="daily",
        run_at=dt.time(2, 0), repository_id=dead_repo.pk)
    backup = backup_service.run_scheduled_backup(schedule, started_at=T0)
    assert backup.status == "failed"


def test_uc_013_ba_uc_007_main_flow(repo):
    """UC-013 / BA-UC-007 Main Flow: local schedule created."""
    schedule = schedule_service.create_local_schedule(
        actor=sysadmin(), dataset="uc-db", frequency="daily",
        run_at=dt.time(2, 0), repository_id=repo.pk)
    assert schedule.is_active


def test_uc_014_ba_uc_007_alternative_conflict(repo):
    """UC-014 / BA-UC-007 Alternative: conflicting schedule refused."""
    schedule_service.create_local_schedule(
        actor=sysadmin(), dataset="uc-db", frequency="daily",
        run_at=dt.time(2, 0), repository_id=repo.pk)
    with pytest.raises((DomainError, ConflictError)):
        schedule_service.create_local_schedule(
            actor=sysadmin(), dataset="uc-db", frequency="daily",
            run_at=dt.time(2, 15), repository_id=repo.pk)


def test_uc_015_ba_uc_008_main_flow(profile_factory):
    """UC-015 / BA-UC-008 Main Flow: extension submitted at full quota."""
    profile_factory(9001, used=10_000, quota=10_000)
    owner = student()
    give_department(owner.user_id, DEPT)
    submitted = storage_service.submit_extension(actor=owner,
                                                 requested_bytes=1024,
                                                 justification="j")
    assert submitted.status == "submitted"


def test_uc_016_ba_uc_008_alternative_not_full(profile_factory):
    """UC-016 / BA-UC-008 Alternative: not-full quota refused."""
    profile_factory(9001, used=1_000, quota=10_000)
    with pytest.raises(DomainError):
        storage_service.submit_extension(actor=student(),
                                         requested_bytes=1024,
                                         justification="j")


def test_uc_017_ba_uc_008_main_flow_decide(profile_factory):
    """UC-017 / BA-UC-008 (decide) Main Flow: HoD approves."""
    profile_factory(9001, used=10_000, quota=10_000)
    owner = student()
    give_department(owner.user_id, DEPT)
    submitted = storage_service.submit_extension(actor=owner,
                                                 requested_bytes=1024,
                                                 justification="j")
    decided = storage_service.decide_extension(actor=hod(dept=DEPT),
                                               request_id=submitted.pk,
                                               decision="approve")
    assert decided.status == "approved"


def test_uc_018_ba_uc_008_alternative_rejection(profile_factory):
    """UC-018 / BA-UC-008 Alternative: HoD rejects."""
    profile_factory(9001, used=10_000, quota=10_000)
    owner = student()
    give_department(owner.user_id, DEPT)
    submitted = storage_service.submit_extension(actor=owner,
                                                 requested_bytes=1024,
                                                 justification="j")
    decided = storage_service.decide_extension(actor=hod(dept=DEPT),
                                               request_id=submitted.pk,
                                               decision="reject")
    assert decided.status == "rejected"


def test_uc_019_ba_uc_010_main_flow():
    """UC-019 / BA-UC-010 Main Flow: special archival performed."""
    record = special_service.perform_special_archival(
        actor=super_admin(), data_reference="offline", reason="r")
    assert SpecialArchivalRecord.objects.filter(pk=record.pk).exists()


def test_uc_020_ba_uc_011_main_flow(repo):
    """UC-020 / BA-UC-011 Main Flow: global schedule defined."""
    defined = schedule_service.set_global_schedule(
        actor=super_admin(), frequency="daily", run_at=dt.time(1, 0),
        repository_id=repo.pk)
    assert defined.scope == "global"


def test_uc_021_ba_uc_012_main_flow():
    """UC-021 / BA-UC-012 Main Flow: audit log view is sysadmin-gated."""
    from modules.badms.selectors import authz
    assert authz.has_permission(sysadmin(), "badms.audit.view")
    assert not authz.has_permission(student(), "badms.audit.view")


def test_uc_022_ba_uc_013_main_flow():
    """UC-022 / BA-UC-013 Main Flow: security audit for IT Security."""
    from modules.badms.selectors import authz
    assert authz.has_permission(itsec(), "badms.security.audit")


def test_uc_023_ba_uc_014_main_flow():
    """UC-023 / BA-UC-014 Main Flow: backup history visible."""
    assert scoping.backups_for(student()).count() == 0


def test_uc_024_ba_uc_015_main_flow():
    """UC-024 / BA-UC-015 Main Flow: owner tracks the request."""
    owner = student()
    request = make_archival(uid=owner.user_id)
    rows = scoping.archival_requests_for(owner)
    assert rows.filter(pk=request.pk).exists()


def test_uc_025_ba_uc_016_main_flow():
    """UC-025 / BA-UC-016 Main Flow: non-Sensitive restoration request."""
    owner = student()
    request = make_archival(uid=owner.user_id, status="classified")
    rest = restoration_service.request_restoration(actor=owner,
                                                   archival_id=request.pk)
    assert rest.status == "requested"


def test_uc_026_ba_uc_017_main_flow():
    """UC-026 / BA-UC-017 Main Flow: Sensitive restoration approved."""
    owner = student()
    request = make_archival(uid=owner.user_id, status="encrypted",
                            classification="sensitive")
    rest = restoration_service.request_restoration(actor=owner,
                                                   archival_id=request.pk)
    approved = restoration_service.decide_request(actor=sysadmin(),
                                                  request_id=rest.pk,
                                                  decision="approve")
    assert approved.status == "approved_for_restoration"


def test_uc_027_ba_uc_017_alternative_rejection():
    """UC-027 / BA-UC-017 Alternative: Sensitive restoration rejected."""
    owner = student()
    request = make_archival(uid=owner.user_id, status="encrypted",
                            classification="sensitive")
    rest = restoration_service.request_restoration(actor=owner,
                                                   archival_id=request.pk)
    rejected = restoration_service.decide_request(actor=sysadmin(),
                                                  request_id=rest.pk,
                                                  decision="reject")
    assert rejected.status == "rejected"


def test_uc_028_ba_uc_018_main_flow():
    """UC-028 / BA-UC-018 Main Flow: restoration executed."""
    owner = student()
    request = make_archival(uid=owner.user_id, status="classified")
    rest = restoration_service.request_restoration(actor=owner,
                                                   archival_id=request.pk)
    done = restoration_service.execute_restoration(actor=sysadmin(),
                                                   request_id=rest.pk)
    assert done.status == "restored"


def test_uc_029_ba_uc_018_alternative_failure(tmp_path):
    """UC-029 / BA-UC-018 Alternative: missing artifact fails."""
    owner = student()
    request = make_archival(uid=owner.user_id, status="classified",
                            classification="routine")
    request.archive_ref = str(tmp_path / "missing.bin")
    request.save(update_fields=["archive_ref"])
    rest = restoration_service.request_restoration(actor=owner,
                                                   archival_id=request.pk)
    done = restoration_service.execute_restoration(actor=sysadmin(),
                                                   request_id=rest.pk)
    assert done.status == "failed" and done.error


def test_uc_030_ba_uc_019_main_flow():
    """UC-030 / BA-UC-019 Main Flow: grant then revoke."""
    security_p = itsec()
    granted = security_service.grant_permission(
        actor=security_p, user_id=9002,
        permission_code="badms.archival.decide")
    assert granted.is_active
    security_service.revoke_permission(actor=security_p, user_id=9002,
                                       permission_code="badms.archival.decide")
    from modules.badms.models import RbacAssignment
    assert not RbacAssignment.objects.filter(
        user_id=9002, is_active=True).exists()


def test_uc_031_ba_uc_020_main_flow():
    """UC-031 / BA-UC-020 Main Flow: policy defined and updated."""
    security_p = itsec()
    policy = security_service.define_policy(actor=security_p,
                                            name="UC Policy",
                                            statement="s")
    updated = security_service.update_policy(actor=security_p,
                                             policy_id=policy.pk,
                                             statement="s2")
    assert updated.statement == "s2"


def test_uc_032_ba_uc_021_main_flow():
    """UC-032 / BA-UC-021 Main Flow: department report for own dept."""
    from modules.badms.services import reports
    give_department(71, DEPT)
    report = reports.department_report(actor=hod(dept=DEPT),
                                       department=DEPT)
    assert "archival_total" in report


def test_uc_033_ba_uc_022_main_flow(profile_factory):
    """UC-033 / BA-UC-022 Main Flow: threshold monitor refreshes."""
    profile_factory(9003, used=500, quota=1000)
    assert storage_service.monitor_all() >= 1
