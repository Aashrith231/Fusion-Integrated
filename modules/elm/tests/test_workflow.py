"""The review/decision machinery: Unit-Head finality, recommendations,
Establishment routing, final sanction, the Director path, withdrawal
and the substitute consent gate."""
from datetime import date
from decimal import Decimal as D

import pytest

from core.api.exceptions import ConflictError, PermissionDeniedError

from .support import (
    APP,
    COLLEAGUE,
    DIRECTOR,
    EST,
    EST2,
    HEAD,
    applicant,
    dean,
    director,
    establishment,
    head,
    principal,
)

pytestmark = pytest.mark.django_db

MON, TUE, WED, THU, FRI = (date(2026, 3, d) for d in (2, 3, 4, 5, 6))
EL_START, EL_END = date(2026, 3, 16), date(2026, 3, 20)


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


def pending_tasks(request):
    from modules.elm.models import LeaveTask

    return list(LeaveTask.objects.filter(request=request, status="pending"))


def notify_log(user_id):
    from modules.elm.models import Notification

    return list(Notification.objects.filter(recipient_user_id=user_id))


class TestUnitHeadFinalCL:
    """BR-EL-016: CL/RH end at the Unit Head."""

    def test_approve_posts_the_leave(self, world):
        from modules.elm.models import LeaveAccount, LeaveTransaction
        from modules.elm.services import workflow

        request = apply(applicant())
        result = workflow.unit_head_decide(request, head(),
                                           outcome="approve", reason="Fine")
        assert result.status == "approved"
        assert result.decided_by_user_id == HEAD
        record = result.leave_record
        assert record is not None and record.status == "ongoing"
        assert record.days == D("4")
        # The balance was charged and the ledger recorded it.
        account = LeaveAccount.objects.get(
            user_id=APP, category="CL", leave_year=request.leave_year)
        assert account.used_days == D("4")
        entry = LeaveTransaction.objects.get(
            account=account, kind="approval", request=request)
        assert entry.delta == D("-4")

    def test_reject_leaves_the_balance_untouched(self, world):
        from modules.elm.models import LeaveAccount
        from modules.elm.services import workflow

        request = apply(applicant())
        workflow.unit_head_decide(request, head(), outcome="reject",
                                  reason="No")
        request.refresh_from_db()
        assert request.status == "rejected"
        assert LeaveAccount.objects.get(
            user_id=APP, category="CL").used_days == D("0")

    def test_only_the_applicants_unit_head_may_decide(self, world):
        from modules.elm.models import OrgUnit
        from modules.elm.services import workflow

        OrgUnit.objects.create(code="ee", name="Electrical",
                               unit_type="department", head_user_id=999)
        request = apply(applicant())
        other = principal(999, permissions=("elm.review.unit_head",))
        with pytest.raises(PermissionDeniedError):
            workflow.unit_head_decide(request, other, outcome="approve")


class TestHigherSanction:
    """BR-EL-017/018: recommendation, then the configured authority."""

    def test_recommendation_records_and_advances(self, world):
        from modules.elm.models import LeaveTask
        from modules.elm.services import workflow

        request = apply(applicant(), "EL", EL_START, EL_END)
        result = workflow.unit_head_decide(request, head(),
                                           outcome="recommended",
                                           reason="Work covered")
        assert result.status == "awaiting_establishment_routing"
        assert result.recommendation == "recommended"
        # The Establishment desk now holds the task — the office is
        # multi-holder, so both desk holders hold one each.
        pending = list(LeaveTask.objects.filter(
            request=request, task_class="establishment_routing",
            status="pending"))
        assert {t.assignee_user_id for t in pending} == {EST, EST2}

    def test_not_recommended_is_not_a_veto(self, world):
        """BR-EL-017: Not Recommended still continues routing."""
        from modules.elm.services import workflow

        request = apply(applicant(), "EL", EL_START, EL_END)
        result = workflow.unit_head_decide(request, head(),
                                           outcome="not_recommended",
                                           reason="Short notice")
        assert result.status == "awaiting_establishment_routing"
        assert result.recommendation == "not_recommended"

    def test_outcome_vocabulary_is_state_specific(self, world):
        """BR-EL-017: higher-sanction Unit Heads record Recommended /
        Not Recommended — approve/reject is not their vocabulary."""
        from modules.elm.services import workflow

        request = apply(applicant(), "EL", EL_START, EL_END)
        with pytest.raises(ConflictError) as err:
            workflow.unit_head_decide(request, head(), outcome="approve")
        assert err.value.code == "invalid_outcome"

    def test_recommendation_is_not_the_cl_rh_vocabulary(self, world):
        from modules.elm.services import workflow

        request = apply(applicant(), "CL")
        with pytest.raises(ConflictError):
            workflow.unit_head_decide(request, head(),
                                      outcome="recommended")

    def test_establishment_forwards_and_never_decides(self, world):
        from modules.elm.services import workflow

        request = apply(applicant(), "EL", EL_START, EL_END)
        workflow.unit_head_decide(request, head(), outcome="recommended")
        workflow.establishment_forward(request, establishment(),
                                       reason="Verified")
        request.refresh_from_db()
        assert request.status == "awaiting_final_sanction_decision"

    def test_first_mover_wins_in_a_multi_holder_office(self, world):
        from modules.elm.models import LeaveTask
        from modules.elm.services import workflow

        request = apply(applicant(), "EL", EL_START, EL_END)
        workflow.unit_head_decide(request, head(), outcome="recommended")
        # Two Establishment holders each hold a pending routing task.
        pending = list(LeaveTask.objects.filter(
            request=request, task_class="establishment_routing",
            status="pending"))
        assert {t.assignee_user_id for t in pending} == {EST, EST2}
        workflow.establishment_forward(request, establishment())
        assert not LeaveTask.objects.filter(
            task_class="establishment_routing", status="pending").exists()

    def test_dean_sanctions_and_the_leave_is_posted(self, world):
        from modules.elm.models import LeaveAccount
        from modules.elm.services import workflow

        request = apply(applicant(), "EL", EL_START, EL_END)
        workflow.unit_head_decide(request, head(), outcome="recommended")
        workflow.establishment_forward(request, establishment())
        workflow.final_decide(request, dean(), outcome="approve")
        request.refresh_from_db()
        assert request.status == "approved"
        assert request.days == D("5")
        assert LeaveAccount.objects.get(
            user_id=APP, category="EL").used_days == D("5")

    def test_establishment_may_not_approve(self, world):
        from modules.elm.api.views import _dispatch_decide

        request = apply(applicant(), "EL", EL_START, EL_END)
        from modules.elm.services import workflow

        workflow.unit_head_decide(request, head(), outcome="recommended")
        with pytest.raises(ConflictError) as err:
            _dispatch_decide(request, establishment(), outcome="approve")
        assert err.value.code == "invalid_outcome"

    def test_wrong_final_authority_is_refused(self, world):
        """The Dean decides — a Registrar designation is not this
        request's authority."""
        from modules.elm.models import EmployeeProfile
        from modules.elm.services import workflow

        request = apply(applicant(), "EL", EL_START, EL_END)
        workflow.unit_head_decide(request, head(), outcome="recommended")
        workflow.establishment_forward(request, establishment())
        EmployeeProfile.objects.create(user_id=402, employee_kind="staff",
                                       designation_name="Registrar")
        registrar = principal(402, permissions=("elm.sanction.final",))
        with pytest.raises(PermissionDeniedError):
            workflow.final_decide(request, registrar, outcome="approve")


class TestDirectorPath:
    """BR-EL-019/020: the Director's own leave self-sanctions —
    including their cancellations and extensions."""

    def test_director_sanctions_own_application(self, world):
        from modules.elm.services import workflow

        p = director()
        request = apply(p, "CL", MON, WED)
        workflow.final_decide(request, p, outcome="approve")
        request.refresh_from_db()
        assert request.status == "approved"
        assert request.decided_by_user_id == DIRECTOR

    def test_nobody_else_sanctions_a_director_request(self, world):
        from modules.elm.services import workflow

        request = apply(director(), "CL", MON, WED)
        with pytest.raises(PermissionDeniedError):
            workflow.final_decide(request, dean(), outcome="approve")

    def test_director_cancellation_carries_the_director_route(self, world):
        """The derived request must sit at the final state of its kind —
        a Unit-Head stop with a director route would deadlock the
        workflow (the Director is nobody's Unit Head)."""
        from modules.elm.models import LeaveTask
        from modules.elm.services import lifecycle, workflow

        p = director()
        base = apply(p, "CL", date(2026, 3, 16), date(2026, 3, 20))
        workflow.final_decide(base, p, outcome="approve")

        cancellation = lifecycle.request_cancellation(
            p, base_request_id=base.id)
        assert cancellation.status == "cancellation_pending_final_decision"
        pending = LeaveTask.objects.get(request=cancellation,
                                        status="pending")
        assert pending.task_class == "final_sanction"
        assert pending.assignee_user_id == DIRECTOR

    def test_director_cancellation_round_trip(self, world):
        """The Director approves their own cancellation; the leave is
        cancelled and the days restored."""
        from modules.elm.models import LeaveAccount
        from modules.elm.services import lifecycle, workflow

        p = director()
        base = apply(p, "CL", date(2026, 3, 16), date(2026, 3, 20))
        workflow.final_decide(base, p, outcome="approve")
        account = LeaveAccount.objects.get(
            user_id=DIRECTOR, category="CL", leave_year=base.leave_year)
        assert account.used_days == D("5")

        cancellation = lifecycle.request_cancellation(
            p, base_request_id=base.id)
        workflow.final_decide(cancellation, p, outcome="approve")
        cancellation.refresh_from_db()
        assert cancellation.status == "approved"
        base.leave_record.refresh_from_db()
        assert base.leave_record.status == "cancelled"
        account.refresh_from_db()
        assert account.used_days == D("0")

    def test_director_extension_starts_at_the_final_state(self, world):
        """A derived request on the director path is born at its
        kind's final state — VL, which the faculty Director
        actually holds."""
        from modules.elm.services import lifecycle, workflow

        p = director()
        base = apply(p, "VL", date(2026, 5, 18), date(2026, 5, 22))
        workflow.final_decide(base, p, outcome="approve")
        extension = lifecycle.request_extension(
            p, base_request_id=base.id, start_date=date(2026, 5, 23),
            end_date=date(2026, 5, 27), purpose="More rest")
        assert extension.status == "extension_pending_final_decision"


class TestSubstituteGate:
    """BR-EL-014/015: exactly one nominee, consent first."""

    def test_submission_with_substitute_waits_for_consent(self, world):
        from modules.elm.models import LeaveTask, SubstituteNomination

        request = apply(applicant(), substitute_required=True,
                        substitute_user_id=COLLEAGUE)
        assert request.status == "awaiting_substitute_response"
        nomination = SubstituteNomination.objects.get(request=request)
        assert nomination.nominee_user_id == COLLEAGUE
        assert nomination.is_active
        task = LeaveTask.objects.get(request=request, status="pending")
        assert task.task_class == "substitute_response"
        assert task.assignee_user_id == COLLEAGUE

    def test_accept_releases_the_gate(self, world):
        from modules.elm.services import workflow

        request = apply(applicant(), substitute_required=True,
                        substitute_user_id=COLLEAGUE)
        workflow.respond_substitute(request, principal(COLLEAGUE),
                                    accept=True)
        request.refresh_from_db()
        assert request.status == "awaiting_unit_head_review"

    def test_decline_closes_the_gate_for_the_applicant(self, world):
        from modules.elm.services import workflow

        request = apply(applicant(), substitute_required=True,
                        substitute_user_id=COLLEAGUE)
        workflow.respond_substitute(request, principal(COLLEAGUE),
                                    accept=False, reason="Away")
        request.refresh_from_db()
        assert request.status == "applicant_action_required"
        # Nobody holds a pending task while the applicant decides.
        assert pending_tasks(request) == []

    def test_replacement_nomination_reopens_the_gate(self, world):
        from modules.elm.models import LeaveTask, SubstituteNomination
        from modules.elm.services import workflow

        request = apply(applicant(), substitute_required=True,
                        substitute_user_id=COLLEAGUE)
        workflow.respond_substitute(request, principal(COLLEAGUE),
                                    accept=False)

        # EL-UC-019: the applicant nominates someone else; the declined
        # nomination is superseded and the gate re-opens.
        from modules.elm.models import EmployeeProfile

        EmployeeProfile.objects.create(user_id=104, employee_kind="staff",
                                       designation_name="Assistant Professor",
                                       unit_code_id="cse")
        request = workflow.nominate_replacement(
            request, applicant(), nominee_user_id=104)
        request.refresh_from_db()
        assert request.status == "awaiting_substitute_response"
        nomination = SubstituteNomination.objects.get(
            request=request, is_active=True)
        assert nomination.nominee_user_id == 104
        # The new nominee now holds the consent task.
        task = LeaveTask.objects.get(request=request, status="pending")
        assert task.task_class == "substitute_response"
        assert task.assignee_user_id == 104

    def test_applicant_cannot_be_their_own_substitute(self, world):
        with pytest.raises(ConflictError) as err:
            apply(applicant(), substitute_required=True,
                  substitute_user_id=APP)
        assert err.value.code == "substitute_ineligible"

    def test_only_the_nominee_may_respond(self, world):
        from modules.elm.services import workflow

        request = apply(applicant(), substitute_required=True,
                        substitute_user_id=COLLEAGUE)
        with pytest.raises(PermissionDeniedError):
            workflow.respond_substitute(request, principal(999),
                                        accept=True)


class TestWithdrawal:
    """BR-EL-022: immediate, terminates processing, informs roles."""

    def test_withdraw_pending_request(self, world):
        from modules.elm.services import workflow

        request = apply(applicant())
        workflow.withdraw(request, applicant(), reason="Changed plans")
        request.refresh_from_db()
        assert request.status == "withdrawn"
        assert request.withdrawn_at is not None
        assert pending_tasks(request) == []

    def test_withdrawal_notifies_the_waiting_roles(self, world):
        """BR-EL-022: withdrawal informs concerned roles — the substitute
        who was waiting for their consent gate gets told."""
        from modules.elm.services import workflow

        request = apply(applicant(), substitute_required=True,
                        substitute_user_id=COLLEAGUE)
        workflow.withdraw(request, applicant(), reason="Changed plans")
        subjects = [n.subject for n in notify_log(COLLEAGUE)]
        assert any("withdraw" in s.lower() for s in subjects)

    def test_withdrawal_notifies_the_unit_head(self, world):
        from modules.elm.services import workflow

        request = apply(applicant())
        workflow.withdraw(request, applicant(), reason="Changed plans")
        subjects = [n.subject for n in notify_log(HEAD)]
        assert any("withdraw" in s.lower() for s in subjects)

    def test_withdrawal_frees_the_reserved_balance(self, world):
        from modules.elm.selectors import balances as balance_selectors
        from modules.elm.services import workflow

        request = apply(applicant())
        workflow.withdraw(request, applicant())
        balance = balance_selectors.balance_for(APP, request.leave_year,
                                                "CL")
        assert balance.pending_days == D("0")
        assert balance.available_days == D("8")

    def test_only_the_applicant_may_withdraw(self, world):
        from modules.elm.services import workflow

        request = apply(applicant())
        with pytest.raises(PermissionDeniedError):
            workflow.withdraw(request, principal(999))

    def test_withdrawal_is_impossible_after_a_decision(self, world):
        from modules.elm.services import workflow

        request = apply(applicant())
        workflow.unit_head_decide(request, head(), outcome="approve")
        with pytest.raises(ConflictError):
            workflow.withdraw(request, applicant())


class TestTaskAssignmentNotifications:
    """BR-EL-035: assigning an actionable task notifies the assignee."""

    def test_unit_head_review_assignment_notifies(self, world):
        apply(applicant())
        assert any(n.topic == "task_assigned" for n in notify_log(HEAD))

    def test_task_assigned_event_in_the_audit_trail(self, world):
        from modules.elm.models import RequestEvent

        request = apply(applicant())
        assert RequestEvent.objects.filter(
            request=request, event="task_assigned").exists()

    def test_assignee_sees_the_task_in_their_queue(self, world):
        from modules.elm.selectors import queues

        apply(applicant())
        queue = queues.queue_for(HEAD)
        assert any(t.task_class == "unit_head_review" for t in queue)
