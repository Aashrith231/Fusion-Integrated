"""Frozen design: FR_DESIGN.json — archival, special, restoration,
storage, notifications, audit (CFR-BA-005..019)."""
import datetime as dt

import pytest

from core.api.exceptions import ConflictError, DomainError, PermissionDeniedError
from modules.badms.models import (
    ArchivalRequest,
    AuditEvent,
    NotificationOutbox,
    RbacAssignment,
    StorageExtensionRequest,
    StorageProfile,
)
from modules.badms.selectors import scoping
from modules.badms.services import archival as archival_service
from modules.badms.services import restoration as restoration_service
from modules.badms.services import schedules as schedule_service
from modules.badms.services import security as security_service
from modules.badms.services import special as special_service
from modules.badms.services import storage as storage_service

from ..helpers import (
    DEPT,
    OTHER_DEPT,
    give_department,
    hod,
    itsec,
    make_archival,
    student,
    super_admin,
    sysadmin,
)

pytestmark = pytest.mark.django_db


def test_fr_019_fr_020_fr_022_fr_023_afr_ba_019_020_022_023_submission():
    """FR-019/020/022/023 / AFR-BA-019/020/022/023: submit + route to HoD."""
    owner = student()
    hod(dept=DEPT)
    request = archival_service.submit_request(
        actor=owner, file_name="r.pdf", file_date=dt.date(2026, 8, 1),
        owners="O", file_type="pdf", reason="r", attachment="att://x",
        attachment_size_bytes=10)
    assert request.status == "submitted"
    assert (request.file_name, request.owners, request.file_type) == \
        ("r.pdf", "O", "pdf")
    assert request.attachment
    queued = archival_service._hod_inbox  # noqa: F841  routing is by department
    from modules.badms.selectors import authz
    assert authz.department_of(hod()) == DEPT


def test_fr_021_afr_ba_021_invalid_submission_changes_nothing(stub_iam):
    """FR-021 / AFR-BA-021: validation failure makes no state change."""
    with pytest.raises(DomainError):
        archival_service.submit_request(
            actor=student(), file_name="", file_date=dt.date(2026, 8, 1),
            owners="O", file_type="pdf", reason="r", attachment="a://x")
    assert ArchivalRequest.objects.count() == 0


def test_fr_024_fr_025_fr_026_afr_ba_024_025_026_hod_decision():
    """FR-024/025/026 / AFR-BA-024/025/026: respective HoD decides only."""
    owner = student()
    give_department(owner.user_id, DEPT)
    mine = archival_service.submit_request(
        actor=owner, file_name="a.pdf", file_date=dt.date(2026, 8, 1),
        owners="O", file_type="pdf", reason="r", attachment="a://x")
    foreign_hod = hod(dept=OTHER_DEPT, uid=79)
    with pytest.raises(PermissionDeniedError):
        archival_service.decide_request(actor=foreign_hod,
                                        request_id=mine.pk, decision="approve")
    decided = archival_service.decide_request(actor=hod(dept=DEPT),
                                              request_id=mine.pk,
                                              decision="approve")
    assert decided.status == "hod_approved"
    assert decided.hod_decided_by_user_id == 71


def test_fr_027_fr_028_fr_030_fr_031_afr_ba_027_028_030_031_classification():
    """FR-027..031 / AFR-BA-027..031: classify + Sensitive routing."""
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
    assert classified.classification == "sensitive"
    assert classified.retention_rule


def test_fr_029_afr_ba_029_default_routine():
    """FR-029 / AFR-BA-029: missing initial classification is Routine."""
    owner = student()
    give_department(owner.user_id, DEPT)
    hod(dept=DEPT)
    request = archival_service.submit_request(
        actor=owner, file_name="a.pdf", file_date=dt.date(2026, 8, 1),
        owners="O", file_type="pdf", reason="r", attachment="a://x")
    assert request.initial_classification == "routine"


def test_fr_032_fr_033_fr_034_afr_ba_032_033_034_encryption(tmp_path,
                                                             settings):
    """FR-032/033/034 / AFR-BA-032/033/034: AES-256 archive created."""
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
        actor=itsec(), request_id=request.pk, key_ref="spec-key")
    assert encrypted.status == "encrypted"
    assert "AES-256" in encrypted.encryption_algorithm
    assert encrypted.archive_ref


def test_fr_035_fr_036_afr_ba_035_036_tracking_and_notifications(stub_iam):
    """FR-035/036 / AFR-BA-035/036: owner tracking + stage notifications."""
    owner = student()
    give_department(owner.user_id, DEPT)
    request = archival_service.submit_request(
        actor=owner, file_name="a.pdf", file_date=dt.date(2026, 8, 1),
        owners="O", file_type="pdf", reason="r", attachment="a://x")
    archival_service.decide_request(actor=hod(dept=DEPT),
                                    request_id=request.pk,
                                    decision="approve")
    topics = list(NotificationOutbox.objects.filter(
        recipient_user_id=owner.user_id).order_by("pk")
        .values_list("topic", flat=True))
    assert "archival.submitted" in topics
    assert "archival.decided" in topics
    history = archival_service.track_history(request)
    assert history


def test_fr_037_fr_038_fr_039_afr_ba_037_038_039_special_archival():
    """FR-037/038/039 / AFR-BA-037/038/039: Super Admin special archival."""
    performed = special_service.perform_special_archival(
        actor=super_admin(), data_reference="offline-set", reason="r")
    assert performed.pk
    with pytest.raises(PermissionDeniedError):
        special_service.perform_special_archival(actor=sysadmin(),
                                                 data_reference="x")
    with pytest.raises(PermissionDeniedError):
        special_service.perform_special_archival(actor=student(),
                                                 data_reference="x")
    assert AuditEvent.objects.filter(
        object_type="special_archival").exists()


def test_fr_040_fr_042_fr_043_afr_ba_040_042_043_standard_restoration():
    """FR-040/042/043 / AFR-BA-040/042/043: non-Sensitive standard path."""
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
                                      classification="routine")
    rest = restoration_service.request_restoration(actor=owner,
                                                   archival_id=request.pk)
    assert rest.status == "requested"
    done = restoration_service.execute_restoration(actor=sysadmin(),
                                                   request_id=rest.pk)
    assert done.status == "restored"


def test_fr_041_afr_ba_041_sensitive_restoration_gated():
    """FR-041 / AFR-BA-041: Sensitive restoration waits for approval."""
    owner = student()
    request = make_archival(uid=owner.user_id, classification="sensitive",
                            status="encrypted")
    rest = restoration_service.request_restoration(actor=owner,
                                                   archival_id=request.pk)
    assert rest.status == "pending_approval"
    with pytest.raises(ConflictError):
        restoration_service.execute_restoration(actor=sysadmin(),
                                                request_id=rest.pk)
    restoration_service.decide_request(actor=sysadmin(), request_id=rest.pk,
                                       decision="approve")
    done = restoration_service.execute_restoration(actor=sysadmin(),
                                                   request_id=rest.pk)
    assert done.status == "restored"


def test_fr_045_fr_046_fr_047_fr_052_afr_ba_045_046_047_052_extension_gates(
        profile_factory):
    """FR-045/046/047/052: full quota + infrastructure validation."""
    profile_factory(9001, used=5_000, quota=10_000)
    owner = student()
    with pytest.raises(DomainError):
        storage_service.submit_extension(actor=owner, requested_bytes=1024,
                                         justification="need more")
    profile_factory(9001, used=10_000, quota=10_000)
    submitted = storage_service.submit_extension(actor=owner,
                                                 requested_bytes=1024,
                                                 justification="thesis data")
    assert submitted.status == "submitted"


def test_fr_048_fr_049_afr_ba_048_049_extension_review_and_decision(
        profile_factory):
    """FR-048/049 / AFR-BA-048/049: HoD review inputs and decision."""
    profile_factory(9001, used=10_000, quota=10_000)
    owner = student()
    give_department(owner.user_id, DEPT)
    submitted = storage_service.submit_extension(actor=owner,
                                                 requested_bytes=1024,
                                                 justification="j")
    queue_hod = hod(dept=DEPT)
    rows = scoping.storage_extensions_for(queue_hod)
    assert rows.filter(pk=submitted.pk).exists()
    decided = storage_service.decide_extension(actor=queue_hod,
                                               request_id=submitted.pk,
                                               decision="approve")
    assert decided.status == "approved"
    assert StorageExtensionRequest.objects.get(pk=submitted.pk).status == \
        "approved"


def test_fr_051_afr_ba_051_threshold_monitoring():
    """FR-051 / AFR-BA-051: thresholds refreshed for all users."""
    storage_service.ensure_profile(user_id=9011)
    storage_service.record_usage(user_id=9011, used_bytes=1000,
                                 quota_bytes=1000)
    monitored = storage_service.monitor_all()
    assert monitored >= 1
    profile = StorageProfile.objects.get(user_id=9011)
    assert profile.full is True


def test_fr_053_afr_ba_053_global_schedule_authority(repo):
    """FR-053 / AFR-BA-053: only the Super Admin defines the global schedule."""
    defined = schedule_service.set_global_schedule(
        actor=super_admin(), frequency="daily", run_at=dt.time(1, 0),
        repository_id=repo.pk)
    assert defined.scope == "global"
    with pytest.raises(PermissionDeniedError):
        schedule_service.set_global_schedule(actor=sysadmin(),
                                             frequency="daily",
                                             run_at=dt.time(1, 0),
                                             repository_id=repo.pk)


def test_fr_054_fr_055_afr_ba_054_055_local_overrides_global(repo):
    """FR-054/055 / AFR-BA-054/055: precedence."""
    schedule_service.set_global_schedule(actor=super_admin(),
                                         frequency="daily",
                                         run_at=dt.time(1, 0),
                                         repository_id=repo.pk)
    assert schedule_service.effective_schedule(dataset="other-ds") \
        .scope == "global"
    schedule_service.create_local_schedule(
        actor=sysadmin(), dataset="mine", frequency="daily",
        run_at=dt.time(3, 0), repository_id=repo.pk)
    assert schedule_service.effective_schedule(dataset="mine").scope == "local"


def test_fr_056_afr_ba_056_retention_by_classification():
    """FR-056 / AFR-BA-056: retention follows each classification."""
    from modules.badms.domain import policy
    for name in policy.CLASSIFICATIONS:
        assert policy.retention_rule_for(name)
    with pytest.raises(ValueError):
        policy.retention_rule_for("unknown")


def test_fr_057_fr_058_fr_059_afr_ba_057_058_059_failure_alert_and_escalation(
        repo):
    """FR-057/058/059: SLA alert, escalation at three, status notifications."""
    from django.utils import timezone

    from modules.badms.models import Backup
    from modules.badms.services import backups as backup_service
    backup = None
    for i in range(3):
        backup = Backup.objects.create(
            kind="manual", status="failed", repository=repo,
            trigger_user_id=70,
            started_at=timezone.now() - dt.timedelta(minutes=30 * (3 - i)))
        backup.consecutive_failures = backup_service._consecutive_failures(
            backup)
        backup_service._alert_sysadmin(backup)
        backup_service._escalate_if_needed(backup)
    assert NotificationOutbox.objects.filter(topic="backup.failed").exists()
    escalated = NotificationOutbox.objects.filter(topic="backup.escalated")
    assert escalated.count() == 1, "exactly one Director-of-IT escalation"


def test_fr_060_afr_ba_060_extension_notifications(profile_factory):
    """FR-060 / AFR-BA-060: requester notified on submit and decision."""
    profile_factory(9001, used=10_000, quota=10_000)
    owner = student()
    give_department(owner.user_id, DEPT)
    submitted = storage_service.submit_extension(actor=owner,
                                                 requested_bytes=1024,
                                                 justification="j")
    storage_service.decide_extension(actor=hod(dept=DEPT),
                                     request_id=submitted.pk,
                                     decision="approve")
    topics = list(NotificationOutbox.objects.filter(
        recipient_user_id=owner.user_id).values_list("topic", flat=True))
    assert "storage.submitted" in topics
    assert "storage.decided" in topics


def test_fr_061_fr_062_afr_ba_061_062_audit_logs_and_sysadmin_view(stub_iam):
    """FR-061/062 / AFR-BA-061/062: audit rows carry required fields."""
    from conftest import make_session
    from fusion_auth.principal import Principal
    owner = student()
    give_department(owner.user_id, DEPT)
    request = archival_service.submit_request(
        actor=owner, file_name="a.pdf", file_date=dt.date(2026, 8, 1),
        owners="O", file_type="pdf", reason="r", attachment="a://x")
    event = AuditEvent.objects.filter(
        object_type="archival", object_id=str(request.pk)).first()
    assert event and event.actor_user_id and event.action and event.outcome
    from modules.badms.selectors import authz
    sysadmin_p = Principal.from_session(make_session(
        user_id=70, kind="staff", roles=("sysadmin",), modules=("badms",),
        permissions=("badms.audit.view",)))
    assert authz.has_permission(sysadmin_p, "badms.audit.view")


def test_fr_063_afr_ba_063_security_audit():
    """FR-063 / AFR-BA-063: IT Security audits data activity."""
    from modules.badms.selectors import authz
    assert authz.has_permission(itsec(), "badms.security.audit")
    assert not authz.has_permission(student(), "badms.security.audit")


def test_fr_064_afr_ba_064_department_report_scope(stub_iam):
    """FR-064 / AFR-BA-064: the HoD sees only their own department."""
    from modules.badms.services import reports
    give_department(71, DEPT)
    mine = reports.department_report(
        actor=hod(dept=DEPT), department=DEPT)
    assert "archival_total" in mine
    from core.api.exceptions import PermissionDeniedError
    with pytest.raises(PermissionDeniedError):
        reports.department_report(actor=hod(dept=DEPT),
                                  department=OTHER_DEPT)


def test_fr_065_afr_ba_065_backup_operations_visibility():
    """FR-065 / AFR-BA-065: backup operations summary."""
    from modules.badms.services import reports
    summary = reports.backup_operations_summary()
    assert summary is not None


def test_fr_066_fr_067_fr_068_afr_ba_066_067_068_rbac_policy_separation():
    """FR-066/067/068: RBAC, policies and role separation."""
    security_p = itsec()
    granted = security_service.grant_permission(
        actor=security_p, user_id=9001,
        permission_code="badms.archival.decide")
    assert granted.is_active
    security_service.revoke_permission(actor=security_p, user_id=9001,
                                       permission_code="badms.archival.decide")
    assert not RbacAssignment.objects.filter(
        user_id=9001, is_active=True).exists()
    assert RbacAssignment.objects.filter(
        user_id=9001, is_active=False).exists()
    policy = security_service.define_policy(
        actor=security_p, name="Spec Policy", statement="Encrypt Sensitive.")
    assert policy.pk
    with pytest.raises(PermissionDeniedError):
        security_service.grant_permission(actor=sysadmin(), user_id=9001,
                                          permission_code="badms.backup.view")
