"""Special archival, audit records, security administration and reporting
(UC-BA-010, UC-BA-012, UC-BA-013, UC-BA-019, UC-BA-020, UC-BA-021, UC-BA-023,
BR-BA-018, BR-BA-020, BR-BA-021, AFR-BA-037..039, AFR-BA-061..068)."""
import pytest

from core.api.exceptions import DomainError, PermissionDeniedError
from modules.badms.models import (
    AuditEvent,
    RbacAssignment,
    SecurityPolicy,
    SpecialArchivalRecord,
)
from modules.badms.selectors import authz
from modules.badms.services import archival, reports, special
from modules.badms.services import audit as audit_service
from modules.badms.services import security as security_service

from .helpers import (
    DEPT,
    HOD_PERMS,
    ITSEC_PERMS,
    SUPERADMIN_PERMS,
    SYSADMIN_PERMS,
    USER_PERMS,
    actor,
    give_department,
    submit_archival,
)

pytestmark = pytest.mark.django_db

STUDENT = 1001
HOD = 20
SYSADMIN = 9
ITSEC = 40
SUPERADMIN = 10


def _student():
    return actor(uid=STUDENT, perms=USER_PERMS)


def _hod():
    give_department(HOD, DEPT)
    return actor(uid=HOD, perms=HOD_PERMS, kind="staff", roles=("hod",))


def _sysadmin():
    return actor(uid=SYSADMIN, perms=SYSADMIN_PERMS, kind="staff")


def _itsec():
    return actor(uid=ITSEC, perms=ITSEC_PERMS, kind="staff",
                 roles=("it_security",))


def _superadmin():
    return actor(uid=SUPERADMIN, perms=SUPERADMIN_PERMS, kind="staff")


# -- UC-BA-010: special archival ---------------------------------------------------------
class TestSpecialArchival:
    def test_super_admin_performs_and_records(self):
        """AFR-BA-037/039: the operation completes and its outcome and audit
        event are recorded."""
        record = special.perform_special_archival(
            actor=_superadmin(), data_reference="research-dataset-7",
            reason="Extended storage of Sensitive research data")
        assert record.outcome == "completed"
        assert record.performed_by_user_id == SUPERADMIN
        assert AuditEvent.objects.filter(
            action="special_archival.performed").exists()

    def test_only_the_super_admin_may_perform(self):
        """BR-BA-018 / AFR-BA-038: every other role is denied — including the
        SysAdmin and the IT Security member."""
        for stranger in (_sysadmin(), _itsec(), _hod(), _student()):
            with pytest.raises(PermissionDeniedError):
                special.perform_special_archival(
                    actor=stranger, data_reference="research-dataset-7")
        assert SpecialArchivalRecord.objects.count() == 0

    def test_operation_needs_identified_data(self):
        with pytest.raises(DomainError):
            special.perform_special_archival(actor=_superadmin(),
                                             data_reference="")
        assert SpecialArchivalRecord.objects.count() == 0

    def test_failed_operation_preserves_state_and_records(self):
        """UC-BA-010 E1: a failure is recorded, nothing claims completion."""
        special.fail_special_archival(actor=_superadmin(),
                                      data_reference="dataset-9",
                                      error="disk offline")
        assert SpecialArchivalRecord.objects.count() == 0
        assert AuditEvent.objects.filter(
            action="special_archival.failed").exists()


# -- UC-BA-023: audit events ---------------------------------------------------------------
class TestAuditRecording:
    def test_every_stage_writes_an_audit_row(self):
        """AFR-BA-061: audit rows carry timestamp, actor, action, outcome."""
        request = submit_archival(_student(), uid=STUDENT)
        archival.decide_request(actor=_hod(), request_id=request.pk,
                                decision="approve")
        rows = AuditEvent.objects.filter(object_type="archival")
        actions = {r.action for r in rows}
        assert "archival.submitted" in actions
        assert "archival.approved" in actions
        row = AuditEvent.objects.get(action="archival.approved")
        assert row.actor_user_id == HOD
        assert row.outcome == "success"
        assert row.created_at is not None

    def test_system_events_carry_a_source_identifier(self):
        """UC-BA-023 A1: system-originated events name their source."""
        audit_service.record_event(action="backup.completed", actor=None,
                                   actor_kind="system",
                                   object_type="backup", object_id=1)
        row = AuditEvent.objects.get(action="backup.completed")
        assert row.actor_user_id is None
        assert row.actor_label == "system"

    def test_failed_audit_write_is_never_reported_stored(self, monkeypatch):
        """UC-BA-023 E1: a persistence failure returns False — no fabricated
        success."""
        monkeypatch.setattr(AuditEvent.objects, "create",
                            lambda **kw: (_ for _ in ()).throw(
                                RuntimeError("db down")))
        assert audit_service.record_event(action="x") is False

    def test_security_events_are_tagged(self):
        security_service.define_policy(actor=_itsec(), name="Encryption at rest",
                                       statement="AES-256 for Sensitive data")
        assert AuditEvent.objects.filter(
            action="security_policy.defined", actor_kind="security").exists()


# -- UC-BA-019/020: security administration ---------------------------------------------------
class TestSecurityAdministration:
    def test_it_security_grants_and_revokes_rbac(self):
        """UC-BA-019 / AFR-BA-066: assignments are applied and audited."""
        assignment = security_service.grant_permission(
            actor=_itsec(), user_id=STUDENT,
            permission_code="badms.archival.decide")
        assert assignment.is_active
        assert AuditEvent.objects.filter(action="rbac.granted").exists()
        # The grant is real: authz now honours it for that user.
        holder = actor(uid=STUDENT, perms=USER_PERMS)
        assert authz.has_permission(holder, "badms.archival.decide")
        security_service.revoke_permission(actor=_itsec(), user_id=STUDENT,
                                           permission_code="badms.archival.decide")
        assert not RbacAssignment.objects.get(
            user_id=STUDENT,
            permission_code="badms.archival.decide").is_active
        assert not authz.has_permission(holder, "badms.archival.decide")

    def test_only_it_security_manages_rbac(self):
        """BR-BA-021: the SysAdmin and everyone else is denied."""
        with pytest.raises(PermissionDeniedError):
            security_service.grant_permission(
                actor=_sysadmin(), user_id=STUDENT,
                permission_code="badms.archival.decide")
        assert RbacAssignment.objects.count() == 0

    def test_unknown_permission_cannot_be_assigned(self):
        """UC-BA-019 E1: an invalid change is rejected; current permissions
        stand."""
        with pytest.raises(DomainError):
            security_service.grant_permission(
                actor=_itsec(), user_id=STUDENT, permission_code="core.admin")
        assert RbacAssignment.objects.count() == 0

    def test_it_security_defines_security_policies(self):
        """UC-BA-020 / AFR-BA-067: policies are defined, updated, audited."""
        policy = security_service.define_policy(
            actor=_itsec(), name="access-window",
            statement="Access windows for Sensitive restores",
            applies_to="restoration")
        updated = security_service.update_policy(
            actor=_itsec(), policy_id=policy.pk, statement="Tightened")
        assert updated.statement == "Tightened"
        assert AuditEvent.objects.filter(
            action="security_policy.defined").exists()
        assert AuditEvent.objects.filter(
            action="security_policy.updated").exists()

    def test_duplicate_policy_name_rejected_and_prior_kept(self):
        """UC-BA-020 E1: an invalid configuration is rejected; the prior
        configuration remains effective."""
        first = security_service.define_policy(
            actor=_itsec(), name="dup", statement="One")
        with pytest.raises(DomainError):
            security_service.define_policy(actor=_itsec(), name="dup",
                                           statement="Two")
        assert SecurityPolicy.objects.get(name="dup").pk == first.pk


# -- UC-BA-012/013/021: reading the protected information ----------------------------------------
class TestReportsAndScopes:
    def test_department_report_scoped_to_own_department(self):
        """UC-BA-021 / BR-BA-010: the HoD reads their department; a foreign
        department is denied."""
        submit_archival(_student(), uid=STUDENT)
        body = reports.department_report(actor=_hod(), department=DEPT)
        assert body["archival_total"] == 1
        with pytest.raises(PermissionDeniedError):
            reports.department_report(actor=_hod(), department="ECE")

    def test_security_report_counts_denied_events(self):
        audit_service.record_event(action="archival.decided", outcome="denied",
                                   actor=_student(), object_type="archival")
        body = reports.security_report()
        assert body["denied_events"] == 1

    def test_backup_operations_summary_counts_outcomes(self):
        from django.utils import timezone

        from modules.badms.models import Backup, BackupRepository

        repo = BackupRepository.objects.create(name="r", reachable=True)
        Backup.objects.create(kind="manual", status="success",
                              repository=repo, started_at=timezone.now())
        Backup.objects.create(kind="manual", status="failed",
                              repository=repo, started_at=timezone.now())
        summary = reports.backup_operations_summary()
        assert summary["success"] == 1
        assert summary["failed"] == 1
