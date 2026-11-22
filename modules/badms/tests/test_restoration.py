"""Data restoration (UC-BA-016, UC-BA-017, UC-BA-018, CW-BA-03, BW-BA-06,
BW-BA-07, BR-BA-005)."""
import pytest

from core.api.exceptions import ConflictError, DomainError, PermissionDeniedError
from modules.badms.models import (
    AuditEvent,
    NotificationOutbox,
    RestorationRequest,
)
from modules.badms.services import restoration

from .helpers import (
    DEPT,
    HOD_PERMS,
    SYSADMIN_PERMS,
    USER_PERMS,
    actor,
    give_department,
    make_archival,
    submit_archival,
)

pytestmark = pytest.mark.django_db

STUDENT = 1001
STUDENT2 = 1002
HOD = 20
SYSADMIN = 9


def _student(uid=STUDENT):
    return actor(uid=uid, perms=USER_PERMS)


def _sysadmin():
    return actor(uid=SYSADMIN, perms=SYSADMIN_PERMS, kind="staff")


def _archived(classification="routine", uid=STUDENT, *, encrypted=False):
    """Archived data the requester owns, at a restorable state."""
    status = "encrypted" if encrypted else "classified"
    return make_archival(uid=uid, classification=classification, status=status,
                         encrypted=encrypted)


# -- UC-BA-016: the request ------------------------------------------------------------
class TestRestorationRequest:
    def test_non_sensitive_takes_the_standard_path(self):
        """BW-BA-06 / AFR-BA-042: non-Sensitive data goes straight to the
        standard path."""
        archived = _archived("routine")
        request = restoration.request_restoration(actor=_student(),
                                                  archival_id=archived.pk)
        assert request.status == "requested"
        assert request.classification == "routine"

    def test_sensitive_requires_sysadmin_approval(self):
        """BW-BA-07 step 1 / BR-BA-005 / AFR-BA-041: Sensitive restoration is
        blocked pending SysAdmin approval."""
        archived = _archived("sensitive", encrypted=True)
        request = restoration.request_restoration(actor=_student(),
                                                  archival_id=archived.pk)
        assert request.status == "pending_approval"

    def test_unknown_archive_is_rejected(self):
        """UC-BA-016 E1: an archive that cannot be located is refused."""
        with pytest.raises(DomainError):
            restoration.request_restoration(actor=_student(), archival_id=9999)
        assert RestorationRequest.objects.count() == 0

    def test_someone_elses_archive_is_refused(self):
        """UC-BA-016 E1 / BR-BA-020: data the requester may not access is not
        disclosed and not restorable by them."""
        archived = _archived("routine", uid=STUDENT2)
        with pytest.raises(PermissionDeniedError):
            restoration.request_restoration(actor=_student(),
                                            archival_id=archived.pk)
        assert RestorationRequest.objects.count() == 0

    def test_not_yet_archived_data_cannot_be_restored(self):
        """Only archived data is restorable — a submitted request is not."""
        submitted = submit_archival(_student(), uid=STUDENT)
        with pytest.raises(DomainError):
            restoration.request_restoration(actor=_student(),
                                            archival_id=submitted.pk)


# -- UC-BA-017: the approval ------------------------------------------------------------
class TestSensitiveApproval:
    def _pending(self, classification="sensitive"):
        archived = _archived(classification, encrypted=True)
        return restoration.request_restoration(actor=_student(),
                                               archival_id=archived.pk)

    def test_sysadmin_approval_eligible_for_execution(self):
        """BW-BA-07 step 3: approval makes the request eligible for technical
        restoration."""
        request = self._pending()
        restoration.decide_request(actor=_sysadmin(), request_id=request.pk,
                                   decision="approve")
        request.refresh_from_db()
        assert request.status == "approved_for_restoration"

    def test_sysadmin_rejection_ends_rejected(self):
        """BW-BA-07 step 2: rejection ends the request Rejected."""
        request = self._pending()
        restoration.decide_request(actor=_sysadmin(), request_id=request.pk,
                                   decision="reject")
        request.refresh_from_db()
        assert request.status == "rejected"
        assert NotificationOutbox.objects.filter(
            dedupe_key=f"restoration-decision-{request.pk}-reject").exists()

    def test_only_sysadmin_may_decide(self):
        """BR-BA-005: there is no HoD route for restoration in this version —
        the HoD holds the decide grant for archival, not for restoration."""
        request = self._pending()
        hod = actor(uid=HOD, perms=HOD_PERMS, kind="staff", roles=("hod",))
        give_department(HOD, DEPT)
        with pytest.raises(PermissionDeniedError):
            restoration.decide_request(actor=hod, request_id=request.pk,
                                       decision="approve")
        request.refresh_from_db()
        assert request.status == "pending_approval"

    def test_non_sensitive_request_needs_no_approval_step(self):
        """The standard path is decided by execution, not by approval:
        deciding a `requested` row is invalid."""
        archived = _archived("routine")
        request = restoration.request_restoration(actor=_student(),
                                                  archival_id=archived.pk)
        with pytest.raises(ConflictError):
            restoration.decide_request(actor=_sysadmin(),
                                       request_id=request.pk,
                                       decision="approve")


# -- UC-BA-018: execution -----------------------------------------------------------------
class TestExecution:
    def _approved_sensitive(self, tmp_path=None):
        archived = _archived("sensitive", encrypted=True)
        if tmp_path is not None:
            artifact = tmp_path / "archive-1.aes256"
            artifact.write_bytes(b"encrypted-bytes")
            archived.archive_ref = str(artifact)
            archived.save(update_fields=["archive_ref"])
        request = restoration.request_restoration(actor=_student(),
                                                  archival_id=archived.pk)
        restoration.decide_request(actor=_sysadmin(), request_id=request.pk,
                                   decision="approve")
        return request

    def test_approved_sensitive_restoration_executes(self, tmp_path):
        """CW-BA-03 row 6: approved Sensitive restoration completes."""
        request = self._approved_sensitive(tmp_path)
        restoration.execute_restoration(actor=_sysadmin(),
                                        request_id=request.pk)
        request.refresh_from_db()
        assert request.status == "restored"
        assert request.executed_at is not None

    def test_standard_path_executes_without_approval(self):
        """BW-BA-06 row 2: non-Sensitive runs the standard procedure."""
        archived = _archived("routine")
        request = restoration.request_restoration(actor=_student(),
                                                  archival_id=archived.pk)
        restoration.execute_restoration(actor=_sysadmin(),
                                        request_id=request.pk)
        request.refresh_from_db()
        assert request.status == "restored"

    def test_sensitive_cannot_execute_before_approval(self):
        """BR-BA-005: restoration of Sensitive data is blocked until the
        SysAdmin approval is recorded."""
        archived = _archived("sensitive", encrypted=True)
        request = restoration.request_restoration(actor=_student(),
                                                  archival_id=archived.pk)
        with pytest.raises(ConflictError):
            restoration.execute_restoration(actor=_sysadmin(),
                                            request_id=request.pk)
        request.refresh_from_db()
        assert request.status == "pending_approval"
        assert RestorationRequest.objects.get(pk=request.pk).executed_at is None

    def test_only_sysadmin_executes(self):
        """UC-BA-018 precondition: technical execution is the SysAdmin's."""
        archived = _archived("routine")
        request = restoration.request_restoration(actor=_student(),
                                                  archival_id=archived.pk)
        with pytest.raises(PermissionDeniedError):
            restoration.execute_restoration(actor=_student(),
                                            request_id=request.pk)
        request.refresh_from_db()
        assert request.status == "requested"

    def test_execution_failure_recorded_with_audit_history(self, monkeypatch):
        """UC-BA-018 E1: retrieval failure is recorded and the audit history
        is preserved."""
        archived = _archived("routine")
        archived.archive_ref = "att://nonexistent"
        archived.save(update_fields=["archive_ref"])
        request = restoration.request_restoration(actor=_student(),
                                                  archival_id=archived.pk)
        restoration.execute_restoration(actor=_sysadmin(),
                                        request_id=request.pk)
        request.refresh_from_db()
        assert request.status == "failed"
        assert request.error
        assert AuditEvent.objects.filter(
            object_type="restoration", outcome="failure").exists()

    def test_requester_notified_of_completion(self):
        archived = _archived("routine")
        request = restoration.request_restoration(actor=_student(),
                                                  archival_id=archived.pk)
        restoration.execute_restoration(actor=_sysadmin(),
                                        request_id=request.pk)
        assert NotificationOutbox.objects.filter(
            topic="restoration.completed",
            recipient_user_id=STUDENT).exists()
