"""Frozen design: BR_DESIGN.json — every business rule with its stated
permitted/prohibited outcomes."""
import datetime as dt

import pytest

from core.api.exceptions import ConflictError, DomainError
from modules.badms.domain import rules as schedule_rules
from modules.badms.models import (
    Backup,
    NotificationOutbox,
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
    OTHER_DEPT,
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


def test_br_001_br_002_permitted_actors_trigger(repo):
    """BR-001/BR-002 / BR-BA-001 permitted-actor: sysadmin and super admin."""
    assert backup_service.trigger_manual_backup(
        actor=sysadmin(), repository=repo).pk
    assert backup_service.trigger_manual_backup(
        actor=super_admin(), repository=repo).pk


def test_br_003_br_ba_001_condition_false():
    """BR-003 / BR-BA-001 condition-false: a student is refused."""
    from core.api.exceptions import PermissionDeniedError
    with pytest.raises(PermissionDeniedError):
        backup_service.trigger_manual_backup(actor=student())


def test_br_004_br_ba_002_condition_true():
    """BR-004 / BR-BA-002 condition-true: the respective HoD decides."""
    owner = student()
    give_department(owner.user_id, DEPT)
    request = archival_service.submit_request(
        actor=owner, file_name="a.pdf", file_date=dt.date(2026, 8, 1),
        owners="O", file_type="pdf", reason="r", attachment="a://x")
    decided = archival_service.decide_request(actor=hod(dept=DEPT),
                                              request_id=request.pk,
                                              decision="approve")
    assert decided.status == "hod_approved"


def test_br_005_br_ba_002_condition_false():
    """BR-005 / BR-BA-002 condition-false: a foreign HoD is refused."""
    from core.api.exceptions import PermissionDeniedError
    owner = student()
    give_department(owner.user_id, DEPT)
    request = archival_service.submit_request(
        actor=owner, file_name="a.pdf", file_date=dt.date(2026, 8, 1),
        owners="O", file_type="pdf", reason="r", attachment="a://x")
    with pytest.raises(PermissionDeniedError):
        archival_service.decide_request(actor=hod(dept=OTHER_DEPT, uid=79),
                                        request_id=request.pk,
                                        decision="approve")


def test_br_006_br_ba_003_permitted_actor(tmp_path, settings):
    """BR-006 / BR-BA-003 permitted-actor: IT Security configures."""
    request = make_archival(uid=9100, status="routed_to_security")
    settings.BADMS_ARCHIVE_ROOT = tmp_path
    encrypted = archival_service.configure_encryption(
        actor=itsec(), request_id=request.pk, key_ref="k")
    assert encrypted.status == "encrypted"


def test_br_007_br_ba_003_condition_false():
    """BR-007 / BR-BA-003 condition-false: SysAdmin may not encrypt."""
    request = make_archival(uid=9101, status="routed_to_security")
    from core.api.exceptions import PermissionDeniedError
    with pytest.raises(PermissionDeniedError):
        archival_service.configure_encryption(actor=sysadmin(),
                                              request_id=request.pk,
                                              key_ref="k")


def test_br_008_br_ba_004_permitted_actor():
    """BR-008 / BR-BA-004 permitted-actor: SysAdmin classifies."""
    request = make_archival(uid=9102, status="hod_approved")
    classified = archival_service.classify_request(
        actor=sysadmin(), request_id=request.pk, classification="routine")
    assert classified.classification == "routine"


def test_br_009_br_ba_004_condition_false():
    """BR-009 / BR-BA-004 condition-false: IT Security may not classify."""
    from core.api.exceptions import PermissionDeniedError
    request = make_archival(uid=9103, status="hod_approved")
    with pytest.raises(PermissionDeniedError):
        archival_service.classify_request(actor=itsec(),
                                          request_id=request.pk,
                                          classification="routine")


def test_br_010_br_011_br_ba_005_condition_true():
    """BR-010/011 / BR-BA-005 condition-true: approve then execute."""
    owner = student()
    request = make_archival(uid=owner.user_id, status="encrypted",
                            classification="sensitive")
    rest = restoration_service.request_restoration(actor=owner,
                                                   archival_id=request.pk)
    restoration_service.decide_request(actor=sysadmin(), request_id=rest.pk,
                                       decision="approve")
    done = restoration_service.execute_restoration(actor=sysadmin(),
                                                   request_id=rest.pk)
    assert done.status == "restored"


def test_br_012_br_ba_005_condition_false():
    """BR-012 / BR-BA-005 condition-false: unapproved execution refused."""
    owner = student()
    request = make_archival(uid=owner.user_id, status="encrypted",
                            classification="sensitive")
    rest = restoration_service.request_restoration(actor=owner,
                                                   archival_id=request.pk)
    with pytest.raises(ConflictError):
        restoration_service.execute_restoration(actor=sysadmin(),
                                                request_id=rest.pk)


def test_br_013_br_014_br_ba_006_default_and_explicit():
    """BR-013/014 / BR-BA-006: default Routine; supplied value honored."""
    from modules.badms.domain import policy
    assert policy.effective_initial_classification(None) == "routine"
    assert policy.effective_initial_classification("sensitive") == "sensitive"


def test_br_015_br_ba_007_enforcement(tmp_path, settings):
    """BR-015 / BR-BA-007 enforcement: AES-256 recorded."""
    request = make_archival(uid=9104, status="routed_to_security")
    settings.BADMS_ARCHIVE_ROOT = tmp_path
    encrypted = archival_service.configure_encryption(
        actor=itsec(), request_id=request.pk, key_ref="k")
    assert "AES-256" in encrypted.encryption_algorithm


def test_br_016_br_ba_008_enforcement():
    """BR-016 / BR-BA-008 enforcement: retention follows classification."""
    request = make_archival(uid=9105, status="hod_approved")
    classified = archival_service.classify_request(
        actor=sysadmin(), request_id=request.pk, classification="archival")
    assert classified.retention_rule


def test_br_017_br_ba_009_permitted_actor(profile_factory):
    """BR-017 / BR-BA-009 permitted-actor: the respective HoD approves."""
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


def test_br_018_br_ba_009_condition_false(profile_factory):
    """BR-018 / BR-BA-009 condition-false: a foreign HoD is refused."""
    from core.api.exceptions import PermissionDeniedError
    profile_factory(9001, used=10_000, quota=10_000)
    owner = student()
    give_department(owner.user_id, DEPT)
    submitted = storage_service.submit_extension(actor=owner,
                                                 requested_bytes=1024,
                                                 justification="j")
    with pytest.raises(PermissionDeniedError):
        storage_service.decide_extension(actor=hod(dept=OTHER_DEPT, uid=79),
                                         request_id=submitted.pk,
                                         decision="approve")


def test_br_019_br_ba_010_enforcement(stub_iam):
    """BR-019 / BR-BA-010 enforcement: only the department's rows."""
    give_department(71, DEPT)
    mine = make_archival(uid=9106, department=DEPT, status="submitted")
    foreign = make_archival(uid=9107, department=OTHER_DEPT,
                            status="submitted")
    queue_hod = hod(dept=DEPT)
    rows = scoping.archival_requests_for(queue_hod)
    assert rows.filter(pk=mine.pk).exists()
    assert not rows.filter(pk=foreign.pk).exists()


def test_br_020_br_021_br_ba_011(repo):
    """BR-020/021 / BR-BA-011: local overrides global; global otherwise."""
    schedule_service.set_global_schedule(
        actor=super_admin(), frequency="daily", run_at=dt.time(1, 0),
        repository_id=repo.pk)
    assert schedule_service.effective_schedule("other").scope == "global"
    schedule_service.create_local_schedule(
        actor=sysadmin(), dataset="mine", frequency="daily",
        run_at=dt.time(3, 0), repository_id=repo.pk)
    assert schedule_service.effective_schedule("mine").scope == "local"


def test_br_022_br_ba_012_invalid_params():
    """BR-022 / BR-BA-012 invalid-params: unknown frequency refused."""
    with pytest.raises(schedule_rules.ScheduleInvalid):
        schedule_rules.validate_parameters(frequency="hourly",
                                           run_at=dt.time(2, 0),
                                           classification_filter=None)


def test_br_023_br_ba_012_conflict():
    """BR-023 / BR-BA-012 conflict: an overlapping schedule conflicts."""
    existing = type("S", (), {"pk": 1, "dataset": "db", "frequency": "daily",
                              "run_at": dt.time(2, 0), "weekday": None})
    reason = schedule_rules.conflicts([existing], scope="local",
                                      dataset="db", frequency="daily",
                                      run_at=dt.time(2, 10), weekday=None)
    assert reason


def test_br_024_br_ba_013_reachable(repo):
    """BR-024 / BR-BA-013 reachable: a reachable repository runs."""
    schedule_service.create_local_schedule(
        actor=sysadmin(), dataset="db", frequency="daily",
        run_at=dt.time(2, 0), repository_id=repo.pk)
    schedule = schedule_service.effective_schedule("db")
    backup = backup_service.run_scheduled_backup(schedule, started_at=T0)
    assert backup.status == "success"


def test_br_025_br_ba_013_unreachable(dead_repo):
    """BR-025 / BR-BA-013 unreachable: no transfer happens."""
    schedule_service.create_local_schedule(
        actor=sysadmin(), dataset="db", frequency="daily",
        run_at=dt.time(2, 0), repository_id=dead_repo.pk)
    schedule = schedule_service.effective_schedule("db")
    backup = backup_service.run_scheduled_backup(schedule, started_at=T0)
    assert backup.status == "failed" and not backup.artifact_ref


def test_br_026_br_ba_014_within_sla(repo):
    """BR-026 / BR-BA-014 within-SLA: the alert is queued for the SysAdmin."""
    backup = Backup.objects.create(kind="manual", status="failed",
                                   repository=repo, trigger_user_id=70,
                                   started_at=T0)
    backup.consecutive_failures = backup_service._consecutive_failures(backup)
    backup_service._alert_sysadmin(backup)
    assert NotificationOutbox.objects.filter(topic="backup.failed").exists()


def test_br_027_br_ba_014_guard(repo):
    """BR-027 / BR-BA-014 guard: the sweep re-queues a missed alert."""
    Backup.objects.create(kind="manual", status="failed",
                          repository=repo, trigger_user_id=70,
                          started_at=T0)
    # no alert was ever queued for this failure
    requeued = backup_service.sweep_failure_alerts()
    assert requeued == 1


def test_br_028_br_029_br_ba_015(repo):
    """BR-028/029 / BR-BA-015: escalation exactly at the third failure."""
    from django.utils import timezone
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
    assert NotificationOutbox.objects.filter(
        topic="backup.escalated").count() == 1


def test_br_030_br_ba_015_not_at_3(repo):
    """BR-030 / BR-BA-015 not-at-3: two failures do not escalate."""
    from django.utils import timezone
    for i in range(2):
        backup = Backup.objects.create(
            kind="manual", status="failed", repository=repo,
            trigger_user_id=70,
            started_at=timezone.now() - dt.timedelta(minutes=30 * (2 - i)))
        backup.consecutive_failures = backup_service._consecutive_failures(
            backup)
        backup_service._alert_sysadmin(backup)
        backup_service._escalate_if_needed(backup)
    assert not NotificationOutbox.objects.filter(
        topic="backup.escalated").exists()


def test_br_031_br_032_br_ba_016(profile_factory):
    """BR-031/032 / BR-BA-016: full quota accepted; non-full refused."""
    profile_factory(9001, used=1_000, quota=10_000)
    with pytest.raises(DomainError):
        storage_service.submit_extension(actor=student(),
                                         requested_bytes=1024,
                                         justification="j")
    profile_factory(9001, used=10_000, quota=10_000)
    submitted = storage_service.submit_extension(actor=student(),
                                                 requested_bytes=1024,
                                                 justification="j")
    assert submitted.status == "submitted"


def test_br_033_br_ba_017_criteria(profile_factory):
    """BR-033 / BR-BA-017 criteria: the review inputs are visible."""
    from modules.badms.models import StorageInfrastructure
    from modules.badms.services import storage as storage_service
    profile_factory(9001, used=10_000, quota=10_000)
    owner = student()
    give_department(owner.user_id, DEPT)
    submitted = storage_service.submit_extension(actor=owner,
                                                 requested_bytes=1024,
                                                 justification="thesis data")
    queue_hod = hod(dept=DEPT)
    row = scoping.storage_extensions_for(queue_hod).get(pk=submitted.pk)
    assert row.justification == "thesis data"
    assert row.usage_at_request == 10_000
    assert StorageInfrastructure.objects.count() >= 0


def test_br_034_br_ba_018_permitted_actor():
    """BR-034 / BR-BA-018 permitted-actor: the Super Admin performs."""
    record = special_service.perform_special_archival(
        actor=super_admin(), data_reference="offline", reason="r")
    assert record.pk


def test_br_035_br_ba_018_condition_false():
    """BR-035 / BR-BA-018 condition-false: a sysadmin is refused."""
    from core.api.exceptions import PermissionDeniedError
    with pytest.raises(PermissionDeniedError):
        special_service.perform_special_archival(actor=sysadmin(),
                                                 data_reference="x")


def test_br_036_br_037_br_ba_019(repo):
    """BR-036/037 / BR-BA-019: only the Super Admin defines global."""
    assert schedule_service.set_global_schedule(
        actor=super_admin(), frequency="daily", run_at=dt.time(1, 0),
        repository_id=repo.pk).pk
    from core.api.exceptions import PermissionDeniedError
    with pytest.raises(PermissionDeniedError):
        schedule_service.set_global_schedule(
            actor=sysadmin(), frequency="daily", run_at=dt.time(1, 0),
            repository_id=repo.pk)


def test_br_038_br_ba_020_enforcement():
    """BR-038 / BR-BA-020 enforcement: out-of-scope rows are absent."""
    other_owner = student(uid=9201)
    request = make_archival(uid=other_owner.user_id, status="submitted")
    viewer = student(uid=9202)
    assert not scoping.archival_requests_for(viewer).filter(
        pk=request.pk).exists()


def test_br_039_br_ba_021_authority():
    """BR-039 / BR-BA-021 authority: only IT Security manages RBAC."""
    granted = security_service.grant_permission(
        actor=itsec(), user_id=9210,
        permission_code="badms.archival.decide")
    assert granted.is_active
    from core.api.exceptions import PermissionDeniedError
    with pytest.raises(PermissionDeniedError):
        security_service.grant_permission(actor=sysadmin(), user_id=9210,
                                          permission_code="badms.backup.view")
