"""Offline-sanctioned leave records (EL-UC-016/017) and the record
list / maintenance surface (BR-EL-036/037)."""
from datetime import date
from decimal import Decimal as D

import pytest
from core.api.exceptions import ConflictError, PermissionDeniedError

from .support import (
    APP,
    DEAN,
    admin,
    applicant,
    dean,
)

pytestmark = pytest.mark.django_db

START, END = date(2026, 2, 16), date(2026, 2, 20)   # Mon–Fri, in the past


def record_offline(principal_=None, **overrides):
    from modules.elm.services import offline as offline_service

    fields = dict(
        user_id=APP, category="CL", start_date=START, end_date=END,
        sanction_reference="FILE/2026/001", sanction_date=date(2026, 2, 10),
        sanctioning_authority="Deputy Registrar (Estt.)",
        evidence_description="Paper file with the sanction order",
        reason_elm_unavailable="ELM was offline that week",
    )
    fields.update(overrides)
    return offline_service.record_offline(principal_ or admin(), **fields)


class TestOfflineRecords:

    def test_recording_posts_the_ledger_and_the_book(self, world):
        entry = record_offline()
        assert entry.days == D("5")             # Mon–Fri, no holidays
        assert entry.consistency_check["overlaps"] == []
        from modules.elm.models import LeaveAccount, LeaveRecord, \
            LeaveTransaction

        record = LeaveRecord.objects.get(id=entry.leave_record_id)
        assert record.status == "ongoing"
        assert record.offline_record_id == entry.id
        account = LeaveAccount.objects.get(
            user_id=APP, category="CL", leave_year=entry.leave_record.
            leave_year)
        assert account.used_days == D("5")
        movement = LeaveTransaction.objects.get(
            account=account, kind="offline_record", offline_record=entry)
        assert movement.delta == D("-5")

    def test_evidence_and_reference_are_mandatory(self, world):
        with pytest.raises(ConflictError) as err:
            record_offline(evidence_description="   ")
        assert err.value.code == "evidence_required"
        with pytest.raises(ConflictError) as err:
            record_offline(sanction_reference="")
        assert err.value.code == "reference_required"

    def test_no_workflow_is_started(self, world):
        """BR-EL-029/037: recording is synchronization, not a second
        approval — no tasks, no sanctioning decision."""
        entry = record_offline()
        from modules.elm.models import LeaveTask

        assert not LeaveTask.objects.exists()
        assert entry.leave_record.status == "ongoing"

    def test_entry_must_not_contradict_the_book(self, world):
        """An overlapping ongoing record fails the consistency check."""
        from modules.elm.services import offline as offline_service
        from modules.elm.models import LeaveRecord

        LeaveRecord.objects.create(
            user_id=APP, leave_year="2025-26", category="EL",
            start_date=date(2026, 2, 18), end_date=date(2026, 2, 25),
            days=D("8"), status="ongoing")
        with pytest.raises(ConflictError) as err:
            record_offline()
        assert err.value.code == "record_inconsistent"

    def test_recording_permission_is_required(self, world):
        with pytest.raises(PermissionDeniedError):
            record_offline(applicant())

    def test_resumption_task_for_offline_leave_names_the_authority(self, world):
        """BR-EL-027: the applicable Sanctioning Authority reviews a
        resumption even for offline-recorded leave — the entry names
        the authority, and the review goes to its holders, never to
        the applicant."""
        from modules.elm.models import LeaveTask
        from modules.elm.services import lifecycle

        entry = record_offline(sanctioning_authority="Dean",
                               category="EL")
        record = entry.leave_record
        resumption = lifecycle.submit_resumption(
            applicant(), record_id=record.id,
            actual_resumption_date=date(2026, 2, 20))
        task = LeaveTask.objects.get(task_class="resumption_review",
                                     status="pending")
        assert task.assignee_user_id == DEAN
        assert task.assignee_user_id != APP
        assert resumption.status == "review_pending"

    def test_offline_resumption_review_by_the_named_authority(self, world):
        """Only a holder of the entry's sanctioning-authority
        designation may review; the applicant may never."""
        from modules.elm.services import lifecycle

        entry = record_offline(sanctioning_authority="Dean",
                               category="EL")
        resumption = lifecycle.submit_resumption(
            applicant(), record_id=entry.leave_record.id,
            actual_resumption_date=date(2026, 2, 20))
        with pytest.raises(PermissionDeniedError):
            lifecycle.review_resumption(resumption, applicant(),
                                        outcome="normal")
        reviewed = lifecycle.review_resumption(resumption, dean(),
                                               outcome="normal")
        assert reviewed.status == "reviewed_normal"

    def test_assignment_notification_for_a_requestless_task(self, world):
        """BR-EL-035: a task with no application behind it (offline
        leave) must still notify its assignee without crashing."""
        from modules.elm.models import Notification
        from modules.elm.services import lifecycle

        entry = record_offline(sanctioning_authority="Dean",
                               category="EL")
        lifecycle.submit_resumption(
            applicant(), record_id=entry.leave_record.id,
            actual_resumption_date=date(2026, 2, 20))
        notifications = Notification.objects.filter(
            topic="task_assigned", recipient_user_id=DEAN)
        assert notifications.exists()


# The world fixture already creates user 401 (DEAN) with the "Dean"
# designation, so "Dean" resolves to that holder for the offline
# resumption routing above.
