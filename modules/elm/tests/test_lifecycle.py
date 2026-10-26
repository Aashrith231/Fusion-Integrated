"""Cancellation, extension and resumption (EL-UC-008/009/010/011),
against BR-EL-023/025/027/028."""
from datetime import date
from decimal import Decimal as D

import pytest

from core.api.exceptions import ConflictError, NotFoundError, PermissionDeniedError

from .support import (
    APP,
    COLLEAGUE,
    FACULTY,
    VACATION,
    applicant,
    dean,
    establishment,
    head,
    principal,
)

pytestmark = pytest.mark.django_db

MON = date(2026, 3, 2)
FRI = date(2026, 3, 6)
EL_START, EL_END = date(2026, 3, 16), date(2026, 3, 20)
CL_FUTURE = (date(2026, 3, 16), date(2026, 3, 20))   # starts 2 weeks out


def apply(principal_, category="CL", start=MON, end=FRI, **fields):
    from modules.elm.services import applications as applications_service

    # substitute and reason fields belong to ``submit`` —
    # create_draft only takes plain LeaveRequest fields.
    substitute_required = fields.pop("substitute_required", None)
    substitute_user_id = fields.pop("substitute_user_id", None)
    reason = fields.pop("reason", None)
    draft = applications_service.create_draft(
        principal_, category=category, start_date=start, end_date=end,
        **fields)
    submit_kwargs = {}
    if substitute_required is not None:
        submit_kwargs["substitute_required"] = substitute_required
    if substitute_user_id is not None:
        submit_kwargs["substitute_user_id"] = substitute_user_id
    if reason is not None:
        submit_kwargs["reason"] = reason
    return applications_service.submit(draft, principal_, **submit_kwargs)


def approve(request):
    """Push a request through its configured hierarchy to approval."""
    from modules.elm.services import workflow

    route = [s["role"] for s in request.route]
    if "unit_head" in route:
        workflow.unit_head_decide(request, head(), outcome=(
            "approve" if request.category in ("CL", "RH")
            else "recommended"))
    if "establishment" in route:
        workflow.establishment_forward(request, establishment())
    if "sanctioning_authority" in route:
        workflow.final_decide(request, dean(), outcome="approve")
    request.refresh_from_db()
    return request


def account_for(request):
    from modules.elm.models import LeaveAccount

    return LeaveAccount.objects.get(
        user_id=request.user_id, category=request.category,
        leave_year=request.leave_year)


# -- cancellation (EL-UC-008, CW-EL-02, BR-EL-023) -------------------------

class TestCancellation:

    def test_cancellation_request_before_the_leave_starts(self, world):
        base = approve(apply(applicant(), "CL", *CL_FUTURE))
        from modules.elm.services import lifecycle

        cancellation = lifecycle.request_cancellation(
            applicant(), base_request_id=base.id)
        assert cancellation.kind == "cancellation"
        assert cancellation.base_request_id == base.id
        assert cancellation.status == "cancellation_pending_unit_head_review"
        # Same hierarchy as the original leave, carried over.
        assert cancellation.route == base.route

    def test_cancellation_only_before_the_start_date(self, world):
        """BR-EL-023: an approved leave may be cancelled only before
        its start date; once started, extension/resumption applies."""
        from modules.elm.services import lifecycle

        base = apply(applicant(), "CL", date(2026, 2, 20), date(2026, 2, 25))
        approve(base)
        # Today is frozen at 2026-03-02 — well past the leave's start.
        with pytest.raises(ConflictError) as err:
            lifecycle.request_cancellation(applicant(),
                                           base_request_id=base.id)
        assert err.value.code == "leave_already_started"

    def test_cancellation_of_a_future_leave_restores_every_day(self, world):
        from modules.elm.services import lifecycle, workflow

        base = approve(apply(applicant(), "CL", *CL_FUTURE))   # 5 days
        assert account_for(base).used_days == D("5")
        cancellation = lifecycle.request_cancellation(
            applicant(), base_request_id=base.id)
        workflow.unit_head_decide(cancellation, head(), outcome="approve")
        cancellation.refresh_from_db()
        assert cancellation.status == "approved"
        base.leave_record.refresh_from_db()
        assert base.leave_record.status == "cancelled"
        assert account_for(base).used_days == D("0")

    def test_cancellation_rejection_changes_nothing(self, world):
        from modules.elm.models import LeaveRecord
        from modules.elm.services import lifecycle, workflow

        base = approve(apply(applicant(), "CL", *CL_FUTURE))
        cancellation = lifecycle.request_cancellation(
            applicant(), base_request_id=base.id)
        workflow.unit_head_decide(cancellation, head(), outcome="reject")
        cancellation.refresh_from_db()
        assert cancellation.status == "rejected"
        base.refresh_from_db()
        assert base.status == "approved"           # untouched (A2)
        record = LeaveRecord.objects.get(id=base.leave_record_id)
        assert record.status == "ongoing"
        assert account_for(base).used_days == D("5")

    def test_no_two_pending_cancellations_for_one_leave(self, world):
        from modules.elm.services import lifecycle

        base = approve(apply(applicant(), "CL", *CL_FUTURE))
        lifecycle.request_cancellation(applicant(), base_request_id=base.id)
        with pytest.raises(ConflictError) as err:
            lifecycle.request_cancellation(applicant(),
                                           base_request_id=base.id)
        assert err.value.code == "cancellation_pending"

    def test_cancellation_needs_the_own_approved_application(self, world):
        from modules.elm.services import lifecycle

        base = apply(applicant())
        with pytest.raises(NotFoundError):
            lifecycle.request_cancellation(applicant(),
                                           base_request_id=base.id + 1000)


# -- extension (EL-UC-009, CW-EL-03, BR-EL-025) ------------------------------

class TestExtension:

    def test_extension_of_ongoing_el(self, world):
        from modules.elm.services import lifecycle

        base = approve(apply(applicant(), "EL", EL_START, EL_END))
        extension = lifecycle.request_extension(
            applicant(), base_request_id=base.id,
            start_date=date(2026, 3, 21), end_date=date(2026, 3, 25),
            purpose="Work continues")
        assert extension.kind == "extension"
        assert extension.status == "awaiting_extension_unit_head_review"
        assert extension.days == D("5")

    def test_extension_must_continue_without_a_gap(self, world):
        from modules.elm.services import lifecycle

        base = approve(apply(applicant(), "EL", EL_START, EL_END))
        with pytest.raises(ConflictError) as err:
            lifecycle.request_extension(
                applicant(), base_request_id=base.id,
                start_date=date(2026, 3, 23), end_date=date(2026, 3, 27),
                purpose="Work continues")
        assert err.value.code == "extension_gap"

    def test_extension_applies_to_el_col_vl_only(self, world):
        from modules.elm.services import lifecycle

        base = approve(apply(applicant(), "CL", EL_START, EL_END))
        with pytest.raises(ConflictError) as err:
            lifecycle.request_extension(
                applicant(), base_request_id=base.id,
                start_date=date(2026, 3, 21), end_date=date(2026, 3, 25),
                purpose="More days")
        assert err.value.code == "extension_not_applicable"

    def test_extension_checks_the_balance(self, world):
        from modules.elm.services import lifecycle

        base = approve(apply(applicant(), "EL", EL_START, EL_END))
        account = account_for(base)
        account.used_days = D("30")                # balance exhausted
        account.save()
        with pytest.raises(ConflictError) as err:
            lifecycle.request_extension(
                applicant(), base_request_id=base.id,
                start_date=date(2026, 3, 21), end_date=date(2026, 3, 25),
                purpose="Work continues")
        assert err.value.code == "insufficient_balance"

    def test_vl_extension_must_stay_inside_the_vacation_period(self, world):
        """BR-EL-006 rides along on extensions: a VL extension must sit
        inside a published vacation period like any VL application."""
        from modules.elm.services import lifecycle

        faculty = principal(FACULTY, kind="faculty")
        base = approve(apply(faculty, "VL", VACATION[0], VACATION[1]))
        with pytest.raises(ConflictError) as err:
            lifecycle.request_extension(
                faculty, base_request_id=base.id,
                start_date=date(2026, 6, 1), end_date=date(2026, 6, 5),
                purpose="Extended vacation")
        assert err.value.code == "calendar_violation"

    def test_vl_extension_inside_the_vacation_period(self, world):
        from modules.elm.services import lifecycle

        faculty = principal(FACULTY, kind="faculty")
        base = approve(apply(faculty, "VL", VACATION[0], date(2026, 5, 22)))
        extension = lifecycle.request_extension(
            faculty, base_request_id=base.id,
            start_date=date(2026, 5, 23), end_date=VACATION[1],
            purpose="Extended vacation")
        assert extension.status == "awaiting_extension_unit_head_review"

    def test_extension_approval_posts_only_the_increment(self, world):
        """BR-EL-025: approval posts only the incremental period; the
        original approval stays the base."""
        from modules.elm.models import LeaveRecord
        from modules.elm.services import lifecycle, workflow

        base = approve(apply(applicant(), "EL", EL_START, EL_END))
        extension = lifecycle.request_extension(
            applicant(), base_request_id=base.id,
            start_date=date(2026, 3, 21), end_date=date(2026, 3, 25),
            purpose="Work continues")
        workflow.unit_head_decide(extension, head(), outcome="recommended")
        workflow.establishment_forward(extension, establishment())
        workflow.final_decide(extension, dean(), outcome="approve")
        extension.refresh_from_db()
        assert extension.status == "approved"
        increment = LeaveRecord.objects.get(
            source_request=extension, extends_record=base.leave_record)
        assert increment.days == D("5")
        assert account_for(base).used_days == D("10")   # 5 + 5

    def test_extension_rejection_preserves_the_original(self, world):
        from modules.elm.services import lifecycle, workflow

        base = approve(apply(applicant(), "EL", EL_START, EL_END))
        extension = lifecycle.request_extension(
            applicant(), base_request_id=base.id,
            start_date=date(2026, 3, 21), end_date=date(2026, 3, 25),
            purpose="Work continues")
        workflow.unit_head_decide(extension, head(), outcome="recommended")
        workflow.establishment_forward(extension, establishment())
        workflow.final_decide(extension, dean(), outcome="reject")
        extension.refresh_from_db()
        assert extension.status == "rejected"
        assert account_for(base).used_days == D("5")    # unchanged

    def test_extension_with_substitute_waits_for_consent(self, world):
        from modules.elm.services import lifecycle, workflow

        base = approve(apply(applicant(), "EL", EL_START, EL_END))
        extension = lifecycle.request_extension(
            applicant(), base_request_id=base.id,
            start_date=date(2026, 3, 21), end_date=date(2026, 3, 25),
            purpose="Work continues", substitute_required=True,
            substitute_user_id=COLLEAGUE)
        assert extension.status == "awaiting_extension_substitute_response"
        workflow.respond_substitute(extension, principal(COLLEAGUE),
                                    accept=True)
        extension.refresh_from_db()
        assert extension.status == "awaiting_extension_unit_head_review"

    def test_extension_of_a_cancelled_leave_is_refused(self, world):
        """The record must still be in force."""
        from modules.elm.services import lifecycle, workflow

        base = approve(apply(applicant(), "EL", EL_START, EL_END))
        cancellation = lifecycle.request_cancellation(
            applicant(), base_request_id=base.id)
        # An EL cancellation follows the higher-sanction path:
        # recommendation, establishment, final decision.
        workflow.unit_head_decide(cancellation, head(),
                                  outcome="recommended")
        workflow.establishment_forward(cancellation, establishment())
        workflow.final_decide(cancellation, dean(), outcome="approve")
        with pytest.raises(ConflictError) as err:
            lifecycle.request_extension(
                applicant(), base_request_id=base.id,
                start_date=date(2026, 3, 21), end_date=date(2026, 3, 25),
                purpose="More")
        assert err.value.code == "leave_not_active"


# -- resumption (EL-UC-010/011, CW-EL-04, BR-EL-027/028) ---------------------

class TestResumption:

    def approved_el(self, world):
        return approve(apply(applicant(), "EL", EL_START, EL_END))

    def test_normal_resumption_is_the_approved_end_date(self, world):
        """BR-EL-028: actual == approved end date → reviewed with no
        adjustment to the period or the balance."""
        from modules.elm.services import lifecycle

        base = self.approved_el(world)
        resumption = lifecycle.submit_resumption(
            applicant(), record_id=base.leave_record_id,
            actual_resumption_date=EL_END)
        assert resumption.status == "review_pending"
        reviewed = lifecycle.review_resumption(resumption, dean(),
                                               outcome="normal")
        assert reviewed.status == "reviewed_normal"
        assert reviewed.adjustment_days is None
        base.leave_record.refresh_from_db()
        assert base.leave_record.actual_end_date == EL_END
        assert account_for(base).used_days == D("5")   # untouched

    def test_early_resumption_restores_the_unused_days_after_review(
            self, world):
        from modules.elm.services import lifecycle

        base = self.approved_el(world)
        resumption = lifecycle.submit_resumption(
            applicant(), record_id=base.leave_record_id,
            actual_resumption_date=date(2026, 3, 18))
        reviewed = lifecycle.review_resumption(resumption, dean(),
                                               outcome="early")
        assert reviewed.status == "reviewed_early"
        assert reviewed.adjustment_days == D("3")      # 18th, 19th, 20th
        assert account_for(base).used_days == D("2")   # 5 - 3
        base.leave_record.refresh_from_db()
        assert base.leave_record.actual_end_date == date(2026, 3, 18)

    def test_late_resumption_charges_the_extra_days_after_review(self, world):
        from modules.elm.services import lifecycle

        base = self.approved_el(world)
        resumption = lifecycle.submit_resumption(
            applicant(), record_id=base.leave_record_id,
            actual_resumption_date=date(2026, 3, 23))
        reviewed = lifecycle.review_resumption(resumption, dean(),
                                               outcome="late")
        assert reviewed.status == "reviewed_late"
        # 21st and 22nd (Sat, Sun) are EL days — continuous counting.
        assert reviewed.adjustment_days == D("-2")
        assert account_for(base).used_days == D("7")

    def test_outcomes_must_match_the_actual_date(self, world):
        from modules.elm.services import lifecycle

        base = self.approved_el(world)
        for outcome, actual in [("normal", date(2026, 3, 18)),
                                ("early", EL_END),
                                ("late", date(2026, 3, 19))]:
            resumption = lifecycle.submit_resumption(
                applicant(), record_id=base.leave_record_id,
                actual_resumption_date=actual)
            with pytest.raises(ConflictError) as err:
                lifecycle.review_resumption(resumption, dean(),
                                            outcome=outcome)
            assert err.value.code == "resumption_mismatch"
            resumption.delete()   # free the pending slot for the next case

    def test_only_the_sanctioning_authority_reviews(self, world):
        from modules.elm.services import lifecycle

        base = self.approved_el(world)
        resumption = lifecycle.submit_resumption(
            applicant(), record_id=base.leave_record_id,
            actual_resumption_date=EL_END)
        stranger = principal(999, permissions=("elm.resume.review",))
        with pytest.raises(PermissionDeniedError):
            lifecycle.review_resumption(resumption, stranger,
                                        outcome="normal")

    def test_a_second_resumption_waits_for_the_first_review(self, world):
        from modules.elm.services import lifecycle

        base = self.approved_el(world)
        lifecycle.submit_resumption(
            applicant(), record_id=base.leave_record_id,
            actual_resumption_date=EL_END)
        with pytest.raises(ConflictError) as err:
            lifecycle.submit_resumption(
                applicant(), record_id=base.leave_record_id,
                actual_resumption_date=EL_END)
        assert err.value.code == "resumption_pending"

    def test_resumption_applies_to_el_col_vl_only(self, world):
        from modules.elm.services import lifecycle

        base = approve(apply(applicant(), "CL", EL_START, EL_END))
        with pytest.raises(NotFoundError):
            lifecycle.submit_resumption(
                applicant(), record_id=base.leave_record_id,
                actual_resumption_date=EL_END)

    def test_only_your_own_record(self, world):
        from modules.elm.services import lifecycle

        base = self.approved_el(world)
        with pytest.raises(NotFoundError):
            lifecycle.submit_resumption(
                principal(999, permissions=("elm.leave.resume",)),
                record_id=base.leave_record_id,
                actual_resumption_date=EL_END)

    def test_resumption_task_goes_to_the_sanctioning_authority(self, world):
        """BR-EL-027: the applicable Sanctioning Authority reviews —
        for ELM leave, whoever made the final decision."""
        from modules.elm.models import LeaveTask
        from modules.elm.services import lifecycle

        base = self.approved_el(world)
        resumption = lifecycle.submit_resumption(
            applicant(), record_id=base.leave_record_id,
            actual_resumption_date=EL_END)
        task = LeaveTask.objects.get(
            task_class="resumption_review", status="pending")
        assert task.assignee_user_id == dean().user_id
        assert resumption.id is not None

    def test_resumption_task_never_lands_on_the_applicant(self, world):
        """The applicant can never be assigned their own resumption
        review — that would deadlock the leave in review_pending."""
        from modules.elm.models import LeaveTask
        from modules.elm.services import lifecycle

        base = self.approved_el(world)
        lifecycle.submit_resumption(
            applicant(), record_id=base.leave_record_id,
            actual_resumption_date=EL_END)
        task = LeaveTask.objects.get(
            task_class="resumption_review", status="pending")
        assert task.assignee_user_id != APP
