"""Storage monitoring and extension requests (UC-BA-022, UC-BA-007,
UC-BA-008, CW-BA-02, BR-BA-009, BR-BA-010, BR-BA-016, BR-BA-017, AFR-BA-045..
052, AFR-BA-060)."""
import pytest

from core.api.exceptions import DomainError, PermissionDeniedError
from modules.badms.models import (
    NotificationOutbox,
    StorageExtensionRequest,
    StorageProfile,
)
from modules.badms.services import storage

from .helpers import (
    DEPT,
    HOD_PERMS,
    OTHER_DEPT,
    USER_PERMS,
    actor,
    give_department,
)

pytestmark = pytest.mark.django_db

STUDENT = 1001
STUDENT2 = 1002
HOD = 20
OTHER_HOD = 21
GIB = 1024 * 1024 * 1024


def _student(uid=STUDENT):
    return actor(uid=uid, perms=USER_PERMS)


def _hod(dept=DEPT):
    give_department(HOD, dept)
    return actor(uid=HOD, perms=HOD_PERMS, kind="staff", roles=("hod",))


# -- UC-BA-022: threshold monitoring --------------------------------------------------
class TestThresholdMonitoring:
    def test_monitor_marks_full_when_usage_reaches_quota(self, profile_factory):
        """UC-BA-022 M1..M3: the evaluated condition is maintained."""
        profile_factory(STUDENT, used=512, quota=1024)
        profile = storage.record_usage(STUDENT, 1024)
        assert profile.full is True

    def test_below_threshold_stays_not_full(self, profile_factory):
        """UC-BA-022 A1: below the threshold nothing forces an extension."""
        profile_factory(STUDENT, used=1024, quota=1024)
        profile = storage.record_usage(STUDENT, 512)
        assert profile.full is False

    def test_unusable_reading_preserves_previous_status(self, profile_factory):
        """UC-BA-022 E1: an unusable reading changes nothing."""
        profile_factory(STUDENT, used=1024, quota=1024)
        before = StorageProfile.objects.get(user_id=STUDENT).full
        with pytest.raises(ValueError):
            storage.record_usage(STUDENT, -5)
        assert StorageProfile.objects.get(user_id=STUDENT).full == before

    def test_monitor_all_updates_every_profile(self, profile_factory):
        profile_factory(STUDENT, used=2000, quota=1024)
        profile_factory(STUDENT2, used=10, quota=1024)
        storage.monitor_all()
        assert StorageProfile.objects.get(user_id=STUDENT).full is True
        assert StorageProfile.objects.get(user_id=STUDENT2).full is False


# -- UC-BA-007: submission --------------------------------------------------------------
class TestExtensionSubmission:
    def _full(self, profile_factory):
        profile_factory(STUDENT, used=1024, quota=1024)
        give_department(STUDENT, DEPT)

    def test_full_quota_request_submits_and_routes_to_hod(self,
                                                          profile_factory):
        """AFR-BA-045/047: a full quota allows submission and routes to the
        requester's HoD."""
        self._full(profile_factory)
        request = storage.submit_extension(
            actor=_student(), requested_bytes=GIB, justification="Thesis data")
        assert request.status == "submitted"
        assert request.department == DEPT

    def test_not_full_quota_is_rejected(self, profile_factory):
        """BR-BA-016: usage conditions not satisfied — the request is
        refused with no state change."""
        profile_factory(STUDENT, used=10, quota=1024)
        with pytest.raises(DomainError):
            storage.submit_extension(actor=_student(), requested_bytes=GIB,
                                     justification="More room")
        assert StorageExtensionRequest.objects.count() == 0

    def test_requested_amount_exceeding_infrastructure_is_detected(
            self, profile_factory):
        """AFR-BA-052: the request is validated against available
        infrastructure."""
        self._full(profile_factory)
        pool = storage.primary_infrastructure()
        pool.capacity_bytes = 2 * GIB
        pool.allocated_bytes = 2 * GIB
        pool.save(update_fields=["capacity_bytes", "allocated_bytes"])
        with pytest.raises(DomainError):
            storage.submit_extension(actor=_student(), requested_bytes=GIB,
                                     justification="Too big")
        assert StorageExtensionRequest.objects.count() == 0

    def test_missing_justification_rejected(self, profile_factory):
        self._full(profile_factory)
        with pytest.raises(DomainError):
            storage.submit_extension(actor=_student(), requested_bytes=GIB,
                                     justification="")
        assert StorageExtensionRequest.objects.count() == 0

    def test_submission_notification_confirms_to_requester(
            self, profile_factory):
        """AFR-BA-060: submission notification."""
        self._full(profile_factory)
        request = storage.submit_extension(
            actor=_student(), requested_bytes=GIB, justification="Data")
        assert NotificationOutbox.objects.filter(
            dedupe_key=f"storage-submitted-{request.pk}").exists()


# -- UC-BA-008: the decision ---------------------------------------------------------------
class TestExtensionDecision:
    def _submitted(self, profile_factory):
        profile_factory(STUDENT, used=1024, quota=1024)
        give_department(STUDENT, DEPT)
        return storage.submit_extension(actor=_student(),
                                        requested_bytes=GIB,
                                        justification="Thesis data")

    def test_respective_hod_approves_and_records(self, profile_factory):
        """BW-BA-05: approval is recorded and the requester is notified."""
        request = self._submitted(profile_factory)
        storage.decide_extension(actor=_hod(), request_id=request.pk,
                                 decision="approve")
        request.refresh_from_db()
        assert request.status == "approved"
        assert request.decided_by_user_id == HOD
        assert NotificationOutbox.objects.filter(
            dedupe_key=f"storage-decision-{request.pk}-approve").exists()

    def test_rejection_recorded(self, profile_factory):
        """BW-BA-04: rejection is recorded."""
        request = self._submitted(profile_factory)
        storage.decide_extension(actor=_hod(), request_id=request.pk,
                                 decision="reject")
        request.refresh_from_db()
        assert request.status == "rejected"

    def test_hod_of_another_department_denied(self, profile_factory):
        """BR-BA-010 / UC-BA-008 E1: outside the department — denied."""
        request = self._submitted(profile_factory)
        give_department(OTHER_HOD, OTHER_DEPT)
        other_hod = actor(uid=OTHER_HOD, perms=HOD_PERMS, kind="staff",
                          roles=("hod",))
        with pytest.raises(PermissionDeniedError):
            storage.decide_extension(actor=other_hod, request_id=request.pk,
                                     decision="approve")
        request.refresh_from_db()
        assert request.status == "submitted"

    def test_no_generic_admin_approval(self, profile_factory):
        """BR-BA-009: no approval by a generic 'Admin' — the decide grant is
        the HoD's; a SysAdmin without it is denied."""
        from .helpers import SYSADMIN_PERMS
        request = self._submitted(profile_factory)
        sysadmin = actor(uid=9, perms=SYSADMIN_PERMS, kind="staff")
        with pytest.raises(PermissionDeniedError):
            storage.decide_extension(actor=sysadmin, request_id=request.pk,
                                     decision="approve")
        request.refresh_from_db()
        assert request.status == "submitted"

    def test_decision_is_informed_by_recorded_criteria(self, profile_factory):
        """BR-BA-017: the record carries what the HoD reviews — usage,
        quota, justification, and the infrastructure picture is served by
        the API."""
        request = self._submitted(profile_factory)
        assert request.usage_at_request == 1024
        assert request.quota_at_request == 1024
        assert request.justification == "Thesis data"
        pool = storage.primary_infrastructure()
        assert pool.available_bytes >= 0
