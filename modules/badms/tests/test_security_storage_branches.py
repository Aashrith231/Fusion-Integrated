"""Branch coverage for the security, storage and operator-command paths."""

import pytest
from django.core.management import call_command

from core.api.exceptions import ConflictError, DomainError
from modules.badms.models import (
    RbacAssignment,
    SecurityPolicy,
    StorageExtensionRequest,
)
from modules.badms.services import security, storage

from .helpers import DEPT, ITSEC_PERMS, actor, give_department

pytestmark = pytest.mark.django_db


def itsec():
    return actor(uid=81, perms=ITSEC_PERMS, kind="staff",
                 roles=("it_security",))


# --- security.py branches (UC-BA-019/020, BR-BA-021) --------------------------

def test_grant_refuses_a_non_badms_permission():
    with pytest.raises(DomainError):
        security.grant_permission(actor=itsec(), user_id=801,
                                  permission_code="placement_cell.view")


def test_grant_refuses_a_blank_user():
    with pytest.raises(DomainError):
        security.grant_permission(actor=itsec(), user_id=0,
                                  permission_code="badms.backup.view")


def test_revoking_an_unknown_assignment_conflicts():
    with pytest.raises(ConflictError):
        security.revoke_permission(actor=itsec(), user_id=802,
                                   permission_code="badms.backup.trigger")


def test_a_grant_is_re_granted_and_then_revoked():
    first = security.grant_permission(actor=itsec(), user_id=803,
                                      permission_code="badms.backup.trigger")
    assert first.is_active
    security.revoke_permission(actor=itsec(), user_id=803,
                               permission_code="badms.backup.trigger")
    # a second grant re-activates the same row rather than duplicating it
    second = security.grant_permission(actor=itsec(), user_id=803,
                                       permission_code="badms.backup.trigger")
    assert second.pk == first.pk and second.is_active
    assert RbacAssignment.objects.filter(user_id=803).count() == 1


def test_policy_define_update_and_validation():
    with pytest.raises(DomainError):
        security.define_policy(actor=itsec(), name="", statement="s")
    policy = security.define_policy(actor=itsec(), name="Retention",
                                    statement="Keep archives for the rule.")
    assert policy.name == "Retention"
    updated = security.update_policy(actor=itsec(), policy_id=policy.pk,
                                     statement="Amended statement.")
    assert updated.statement == "Amended statement."
    assert SecurityPolicy.objects.count() == 1


# --- storage.py branches (BR-BA-016, AFR-BA-052) -------------------------------

def test_a_negative_usage_reading_is_refused():
    with pytest.raises(ValueError):
        storage.record_usage(user_id=811, used_bytes=-1)


def test_extension_submission_validates_input_and_infrastructure(stub_iam):
    profile = storage.ensure_profile(user_id=812)
    profile.quota_bytes = 1_000
    profile.used_bytes = 1_000
    profile.full = True
    profile.save()

    principal = actor(uid=812, perms=("badms.storage.request",))
    with pytest.raises(DomainError):
        storage.submit_extension(actor=principal, requested_bytes=4096,
                                 justification="")
    with pytest.raises(DomainError):
        storage.submit_extension(actor=principal, requested_bytes=0,
                                 justification="j")
    # available infrastructure is finite (AFR-BA-052)
    from modules.badms.models import StorageInfrastructure
    StorageInfrastructure.objects.create(
        name="primary", capacity_bytes=8_000, allocated_bytes=0)
    with pytest.raises(DomainError):
        storage.submit_extension(actor=principal, requested_bytes=999_999,
                                 justification="j")


def test_extension_decision_re_checks_department_under_the_lock(stub_iam):
    give_department(813, DEPT)
    StorageExtensionRequest.objects.create(
        user_id=814, department=DEPT, requested_bytes=1,
        justification="j", attachment="a://x")
    principal = actor(uid=813, perms=("badms.storage.decide",), kind="staff",
                      roles=("hod",))
    request_id = StorageExtensionRequest.objects.first().pk
    with pytest.raises(DomainError):
        storage.decide_extension(actor=principal, request_id=request_id,
                                 decision="sideways")


# --- the operator commands (each scheduled task, run by hand) -------------------

def test_every_operator_command_runs_read_only(capsys):
    call_command("deliver_notifications", "--status")
    call_command("monitor_storage")
    call_command("run_backup_schedules")
    call_command("sweep_backup_alerts")
    captured = capsys.readouterr()
    assert "outbox empty" in captured.out
    assert "monitored 0 profile" in captured.out
    assert "ran 0 schedule" in captured.out


def test_deliver_command_reports_a_queue(monkeypatch, capsys):
    from modules.badms.services import notifications

    notifications.enqueue(dedupe_key="c1", topic="backup.completed",
                          subject="s", body="b", recipient_email="a@x.y")
    monkeypatch.setattr(notifications, "send_mail", lambda **kw: None)
    call_command("deliver_notifications")
    out = capsys.readouterr().out
    assert "sent=1" in out
