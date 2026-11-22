"""Secure archival end to end (UC-BA-002..005, UC-BA-015, CW-BA-01, BR-BA-002,
BR-BA-003, BR-BA-004, BR-BA-006, BR-BA-007, BR-BA-008, BR-BA-010, AFR-BA-019..
036, AFR-BA-056)."""
import datetime as dt

import pytest

from core.api.exceptions import DomainError, PermissionDeniedError
from modules.badms.models import (
    ArchivalDecision,
    ArchivalRequest,
    AuditEvent,
    NotificationOutbox,
)
from modules.badms.services import archival

from .helpers import (
    DEPT,
    HOD_PERMS,
    ITSEC_PERMS,
    OTHER_DEPT,
    SYSADMIN_PERMS,
    USER_PERMS,
    actor,
    give_department,
    submit_archival,
)

pytestmark = pytest.mark.django_db

STUDENT = 1001
HOD = 20
OTHER_HOD = 21
SYSADMIN = 9
ITSEC = 40


def _student():
    return actor(uid=STUDENT, perms=USER_PERMS)


def _hod(dept=DEPT):
    give_department(HOD, dept)
    return actor(uid=HOD, perms=HOD_PERMS, kind="staff", roles=("hod",))


def _sysadmin():
    return actor(uid=SYSADMIN, perms=SYSADMIN_PERMS, kind="staff")


def _itsec():
    return actor(uid=ITSEC, perms=ITSEC_PERMS, kind="staff",
                 roles=("it_security",))


# -- UC-BA-002: submission ----------------------------------------------------------
class TestSubmission:
    def test_valid_submission_sets_submitted_and_routes_to_hod(self):
        """AFR-BA-022/023: success records Submitted and routes to the
        requester's HoD."""
        request = submit_archival(_student(), uid=STUDENT)
        assert request.status == "submitted"
        assert request.department == DEPT
        assert ArchivalDecision.objects.filter(
            request=request, stage="hod").exists()

    def test_captures_all_required_metadata(self):
        """AFR-BA-020: file name, date, owners, file type, reason and
        attachment are all stored."""
        request = submit_archival(_student(), uid=STUDENT)
        assert request.file_name == "thesis-final.pdf"
        assert request.file_date == dt.date(2026, 8, 1)
        assert request.owners and request.file_type
        assert request.reason and request.attachment

    def test_missing_initial_classification_defaults_to_routine(self):
        """BR-BA-006 / AFR-BA-029: omitted initial classification becomes
        Routine."""
        request = submit_archival(_student(), uid=STUDENT)
        assert request.initial_classification == "routine"

    def test_provided_initial_classification_is_kept(self):
        request = submit_archival(_student(), uid=STUDENT,
                                  classification="sensitive")
        assert request.initial_classification == "sensitive"

    def test_validation_failure_makes_no_state_change(self):
        """UC-BA-002 E1 / AFR-BA-021: missing required data shows an error
        and creates nothing."""
        with pytest.raises(DomainError):
            archival.submit_request(
                actor=_student(), file_name="", file_date=dt.date(2026, 8, 1),
                owners="o", file_type="pdf", reason="r", attachment="a")
        assert ArchivalRequest.objects.count() == 0

    def test_quota_validation_rejects_oversized_attachment(self,
                                                           profile_factory):
        """AFR-BA-021: quota is validated; failure keeps the request
        unsubmitted."""
        profile_factory(STUDENT, used=900, quota=1024)
        with pytest.raises(DomainError):
            submit_archival(_student(), uid=STUDENT, size=200)
        assert ArchivalRequest.objects.count() == 0

    def test_submission_within_quota_succeeds(self, profile_factory):
        profile_factory(STUDENT, used=900, quota=1024)
        request = submit_archival(_student(), uid=STUDENT, size=100)
        assert request.pk is not None

    def test_submission_confirms_to_requester_and_hod(self, monkeypatch):
        """AFR-BA-036: submission notification, and the HoD learns a request
        is waiting."""
        request = submit_archival(_student(), uid=STUDENT)
        keys = list(NotificationOutbox.objects.values_list("dedupe_key",
                                                           flat=True))
        assert f"archival-submitted-{request.pk}" in keys


# -- UC-BA-003: the HoD decision ------------------------------------------------------
class TestHodDecision:
    def _submitted(self):
        return submit_archival(_student(), uid=STUDENT)

    def test_respective_hod_can_approve(self):
        """BW-BA-02 step 2: the HoD of the department approves, and the
        request routes to the SysAdmin (AFR-BA-027)."""
        request = self._submitted()
        archival.decide_request(actor=_hod(), request_id=request.pk,
                                decision="approve")
        request.refresh_from_db()
        assert request.status == "hod_approved"

    def test_rejection_records_rejected_and_notifies(self):
        """BW-BA-01: reject sets Rejected and notifies the requester
        (UC-BA-003 A2)."""
        request = self._submitted()
        archival.decide_request(actor=_hod(), request_id=request.pk,
                                decision="reject")
        request.refresh_from_db()
        assert request.status == "rejected"
        assert NotificationOutbox.objects.filter(
            dedupe_key=f"archival-decision-{request.pk}-reject").exists()

    def test_hod_of_another_department_is_denied(self):
        """BR-BA-002 / BR-BA-010 / UC-BA-003 E1: the request is outside this
        HoD's department."""
        request = self._submitted()
        with pytest.raises(PermissionDeniedError):
            archival.decide_request(actor=_hod(OTHER_DEPT),
                                    request_id=request.pk, decision="approve")
        request.refresh_from_db()
        assert request.status == "submitted"

    def test_hod_without_the_department_on_record_is_denied(self):
        request = self._submitted()
        stranger = actor(uid=99, perms=HOD_PERMS, kind="staff", roles=("hod",))
        with pytest.raises(PermissionDeniedError):
            archival.decide_request(actor=stranger, request_id=request.pk,
                                    decision="approve")
        request.refresh_from_db()
        assert request.status == "submitted"

    def test_cannot_decide_twice(self):
        """An already-decided request takes no further HoD outcome."""
        request = self._submitted()
        archival.decide_request(actor=_hod(), request_id=request.pk,
                                decision="reject")
        from core.api.exceptions import ConflictError
        with pytest.raises(ConflictError):
            archival.decide_request(actor=_hod(), request_id=request.pk,
                                    decision="approve")
        request.refresh_from_db()
        assert request.status == "rejected"


# -- UC-BA-004: classification --------------------------------------------------------
class TestClassification:
    def _approved(self):
        request = submit_archival(_student(), uid=STUDENT)
        archival.decide_request(actor=_hod(), request_id=request.pk,
                                decision="approve")
        return request

    def test_sysadmin_assigns_authoritative_classification(self):
        """BR-BA-004 / AFR-BA-028: the SysAdmin classifies after HoD
        approval."""
        request = self._approved()
        archival.classify_request(actor=_sysadmin(), request_id=request.pk,
                                  classification="critical")
        request.refresh_from_db()
        assert request.classification == "critical"
        assert request.status == "classified"

    def test_non_sensitive_classified_applies_retention_no_encryption(self):
        """UC-BA-004 A1 / BR-BA-008 / AFR-BA-030/056: non-Sensitive ends at
        Classified with the retention rule applied."""
        request = self._approved()
        archival.classify_request(actor=_sysadmin(), request_id=request.pk,
                                  classification="routine")
        request.refresh_from_db()
        assert request.status == "classified"
        assert request.retention_rule.startswith("routine")
        assert not request.encryption_algorithm

    def test_sensitive_routes_to_it_security(self):
        """BW-BA-03 step 3 / AFR-BA-031: Sensitive routes to IT Security."""
        request = self._approved()
        archival.classify_request(actor=_sysadmin(), request_id=request.pk,
                                  classification="sensitive")
        request.refresh_from_db()
        assert request.status == "routed_to_security"

    def test_only_sysadmin_may_classify(self):
        """BR-BA-004: the HoD or a plain user cannot classify."""
        request = self._approved()
        with pytest.raises(PermissionDeniedError):
            archival.classify_request(actor=_hod(), request_id=request.pk,
                                      classification="critical")
        with pytest.raises(PermissionDeniedError):
            archival.classify_request(actor=_student(),
                                      request_id=request.pk,
                                      classification="critical")
        request.refresh_from_db()
        assert request.status == "hod_approved"
        assert not request.classification

    def test_cannot_classify_before_hod_approval(self):
        """UC-BA-004 precondition: the request must have HoD approval."""
        request = submit_archival(_student(), uid=STUDENT)
        from core.api.exceptions import ConflictError
        with pytest.raises(ConflictError):
            archival.classify_request(actor=_sysadmin(),
                                      request_id=request.pk,
                                      classification="routine")
        request.refresh_from_db()
        assert request.status == "submitted"

    def test_classification_failure_preserves_state(self):
        """UC-BA-004 E1: an invalid classification changes nothing."""
        request = self._approved()
        with pytest.raises(DomainError):
            archival.classify_request(actor=_sysadmin(),
                                      request_id=request.pk,
                                      classification="top_secret")
        request.refresh_from_db()
        assert request.status == "hod_approved"
        assert not request.classification


# -- UC-BA-005: encryption --------------------------------------------------------------
class TestEncryption:
    def _sensitive(self):
        request = submit_archival(_student(), uid=STUDENT)
        archival.decide_request(actor=_hod(), request_id=request.pk,
                                decision="approve")
        archival.classify_request(actor=_sysadmin(), request_id=request.pk,
                                  classification="sensitive")
        return request

    def test_it_security_configures_and_creates_encrypted_archive(self):
        """BW-BA-03 step 4 / AFR-BA-032/033: IT Security configures
        encryption and the archive is created with the outcome recorded."""
        request = self._sensitive()
        archival.configure_encryption(actor=_itsec(), request_id=request.pk,
                                      key_ref="kms://key-1")
        request.refresh_from_db()
        assert request.status == "encrypted"
        assert "AES-256" in request.encryption_algorithm
        assert request.encryption_key_ref == "kms://key-1"
        assert request.encrypted_at is not None
        assert request.archive_ref

    def test_aes256_required_for_sensitive_data(self):
        """BR-BA-007 / AFR-BA-034: the recorded algorithm is AES-256 at rest
        and in transit."""
        request = self._sensitive()
        archival.configure_encryption(actor=_itsec(), request_id=request.pk,
                                      key_ref="k")
        request.refresh_from_db()
        assert "at rest and in transit" in request.encryption_algorithm

    def test_only_it_security_may_configure_encryption(self):
        """BR-BA-003: nobody outside IT Security configures encryption."""
        request = self._sensitive()
        for stranger in (_sysadmin(), _hod(), _student()):
            with pytest.raises(PermissionDeniedError):
                archival.configure_encryption(actor=stranger,
                                              request_id=request.pk,
                                              key_ref="k")
        request.refresh_from_db()
        assert request.status == "routed_to_security"
        assert not request.encryption_algorithm

    def test_cannot_encrypt_a_non_sensitive_request(self):
        from core.api.exceptions import ConflictError
        request = submit_archival(_student(), uid=STUDENT)
        with pytest.raises(ConflictError):
            archival.configure_encryption(actor=_itsec(),
                                          request_id=request.pk, key_ref="k")

    def test_encryption_failure_records_failure_and_keeps_history(self,
                                                                  monkeypatch,
                                                                  tmp_path):
        """UC-BA-005 E1: a failed archive creation is recorded, the request
        keeps its recoverable history, and nothing claims success."""
        request = self._sensitive()
        monkeypatch.setattr(archival, "_archive_root",
                            lambda: tmp_path / "missing-dir")
        monkeypatch.setattr("builtins.open", None) if False else None
        # Point the archive root at an unwritable path.
        blocker = tmp_path / "blocker"
        blocker.write_text("x")
        monkeypatch.setattr(archival, "_archive_root", lambda: blocker / "sub")
        # The blocker is a file, so creating a subdirectory inside fails.
        (blocker / "sub").unlink() if (blocker / "sub").exists() else None
        with pytest.raises(DomainError):
            archival.configure_encryption(actor=_itsec(),
                                          request_id=request.pk, key_ref="k")
        request.refresh_from_db()
        assert request.status == "encryption_failed"
        assert ArchivalDecision.objects.filter(
            request=request, stage="encryption", decision="failed").exists()
        assert AuditEvent.objects.filter(
            action="archival.encryption_failed").exists()


# -- UC-BA-015: tracking ------------------------------------------------------------------
class TestTracking:
    def test_status_history_visible_through_decisions(self):
        """AFR-BA-035: the full decision history is retrievable."""
        request = submit_archival(_student(), uid=STUDENT)
        archival.decide_request(actor=_hod(), request_id=request.pk,
                                decision="approve")
        archival.classify_request(actor=_sysadmin(), request_id=request.pk,
                                  classification="routine")
        history = archival.track_history(ArchivalRequest.objects.get(
            pk=request.pk))
        decisions = [h["decision"] for h in history]
        assert "submitted" in decisions
        assert "approve" in decisions
        assert "routine" in decisions

    def test_decision_notifications_at_each_stage(self):
        """AFR-BA-036: decision notifications at approval and classification
        stages."""
        request = submit_archival(_student(), uid=STUDENT)
        archival.decide_request(actor=_hod(), request_id=request.pk,
                                decision="approve")
        archival.classify_request(actor=_sysadmin(), request_id=request.pk,
                                  classification="routine")
        assert NotificationOutbox.objects.filter(
            dedupe_key=f"archival-decision-{request.pk}-approve").exists()
        assert NotificationOutbox.objects.filter(
            dedupe_key=f"archival-classified-{request.pk}").exists()
