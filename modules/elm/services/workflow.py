"""The ELM workflow engine.

Every state change on a :model:`elm.LeaveRequest` goes through
:func:`apply_transition`, which:

1. looks the move up in the state-transition table — anything
   not in the table is refused before anything else happens,
2. verifies the caller is the actor that move belongs to
   (the right office-holder, not merely a permission holder),
3. completes the task the move answers,
4. applies the state change and its decision bookkeeping,
5. performs the terminal side effects (posting the leave,
   restoring or charging the balance), and
6. spawns the next task, which notifies its assignee.

Services never set ``status`` directly.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from core.api.exceptions import ConflictError, PermissionDeniedError
from modules.elm.domain import state_machine as machine
from modules.elm.domain.errors import InvalidTransition
from modules.elm.domain.leave_types import (
    ACTOR_EMPLOYEE,
    ACTOR_ESTABLISHMENT,
    ACTOR_SANCTIONING,
    ACTOR_SUBSTITUTE,
    ACTOR_UNIT_HEAD,
    APPROVED,
    AWAITING_DIRECTOR_SELF_SANCTION,
    AWAITING_ESTABLISHMENT_ROUTING,
    AWAITING_EXTENSION_SUBSTITUTE,
    AWAITING_EXTENSION_UNIT_HEAD,
    AWAITING_FINAL_SANCTION_DECISION,
    AWAITING_SUBSTITUTE_RESPONSE,
    AWAITING_UNIT_HEAD_REVIEW,
    CANCELLATION_PENDING_ESTABLISHMENT,
    CANCELLATION_PENDING_FINAL,
    CANCELLATION_PENDING_UNIT_HEAD,
    EXTENSION_PENDING_ESTABLISHMENT,
    EXTENSION_PENDING_FINAL,
    HALF_FULL,
    KIND_CANCELLATION,
    KIND_EXTENSION,
    KIND_NEW,
    REJECTED,
    TERMINAL_STATES,
    WITHDRAWN,
)
from modules.elm.domain.policy import LeaveInterval, count_days
from modules.elm.domain.routing import (
    ROLE_DIRECTOR_SELF,
    ROLE_ESTABLISHMENT,
    ROLE_SANCTIONING_AUTHORITY,
    ROLE_SUBSTITUTE,
    ROLE_UNIT_HEAD,
)
from modules.elm.models import (
    EmployeeProfile,
    LeaveAccount,
    LeaveRecord,
    LeaveRequest,
    LeaveTask,
    RequestEvent,
    SubstituteNomination,
)
from modules.elm.selectors.requests import closed_dates
from modules.elm.services import authz, notifications
from modules.elm.services import policy as policy_service

log = logging.getLogger("fusion.elm.workflow")

ZERO = Decimal("0")


# -- audit and tasks ------------------------------------------------------


def _log(request: LeaveRequest | None, event: str, *,
           from_status: str = "", to_status: str = "",
           actor: int | None = None, actor_label: str = "",
           outcome: str = "", reason: str = "",
           payload: dict | None = None) -> RequestEvent:
    return RequestEvent.objects.create(
        request=request, event=event, from_status=from_status,
        to_status=to_status, actor_user_id=actor,
        actor_label=actor_label, outcome=outcome, reason=reason,
        payload=payload or {},
    )


def _pending_task(request: LeaveRequest,
                    task_class: str) -> LeaveTask | None:
    return LeaveTask.objects.filter(
        request=request, task_class=task_class,
        status="pending").first()


def _complete_task(task: LeaveTask, *, outcome: str,
                     reason: str, user_id: int) -> None:
    task.status = "completed"
    task.outcome = outcome
    task.reason = reason
    task.completed_at = timezone.now()
    task.save()
    _log(task.request, "task_completed", actor=user_id,
           outcome=outcome, reason=reason,
           payload={"task_id": task.id,
                    "task_class": task.task_class})
    # First mover wins: a multi-holder office (Registrar,
    # Dean's office) carries one pending task per holder;
    # the decision that lands first retires the rest.
    _cancel_tasks(
        LeaveTask.objects.filter(
            request=task.request, task_class=task.task_class,
            status="pending").exclude(id=task.id),
        reason="Completed by another office-holder")


def _cancel_tasks(tasks: Sequence[LeaveTask],
                    *, reason: str = "") -> None:
    for task in tasks:
        task.status = "cancelled"
        task.reason = reason
        task.completed_at = timezone.now()
        task.save()
        _log(task.request, "task_cancelled",
               outcome=task.task_class, reason=reason,
               payload={"task_id": task.id,
                        "task_class": task.task_class,
                        "assignee_user_id": task.assignee_user_id})


def spawn_tasks(request: LeaveRequest) -> None:
    """Create the task(s) the request's current state awaits.

    Called after every state change; a no-op for terminal
    states and for states that await nobody (the applicant
    action state after a substitute decline).
    """
    nxt = _next_task_for(request)
    if nxt is None:
        return
    task_class, assignee_role, assignee_ids = nxt
    sla = None
    from modules.elm.models import SlaConfig

    sla = SlaConfig.objects.filter(
        task_class=task_class).first()
    now = timezone.now()
    for user_id in assignee_ids:
        task = LeaveTask.objects.create(
            request=request, task_class=task_class,
            assignee_user_id=user_id,
            assignee_role=assignee_role,
            reminder_at=(now + timedelta(
                hours=sla.reminder_hours)) if sla else None,
            escalation_at=(now + timedelta(
                hours=sla.escalation_hours)) if sla else None,
        )
        _log(request, "task_assigned", outcome=task_class,
               payload={"task_id": task.id,
                        "task_class": task_class,
                        "assignee_user_id": user_id})
        notifications.notify_task_assigned(task)


def _next_task_for(request: LeaveRequest):
    """(task_class, assignee_role, assignee_ids) the current
    state awaits, or ``None``."""
    status = request.status
    if status in (AWAITING_SUBSTITUTE_RESPONSE,
                  AWAITING_EXTENSION_SUBSTITUTE):
        nomination = _active_nomination(request)
        if nomination is None:
            return None
        return ("substitute_response", ROLE_SUBSTITUTE,
                [nomination.nominee_user_id])

    route = list(request.route or [])
    if not route:
        return None
    if status in (AWAITING_UNIT_HEAD_REVIEW,
                  CANCELLATION_PENDING_UNIT_HEAD,
                  AWAITING_EXTENSION_UNIT_HEAD):
        step = route[0]
    elif status in (AWAITING_ESTABLISHMENT_ROUTING,
                    CANCELLATION_PENDING_ESTABLISHMENT,
                    EXTENSION_PENDING_ESTABLISHMENT):
        step = route[1] if len(route) > 1 else route[-1]
    elif status in (AWAITING_FINAL_SANCTION_DECISION,
                    CANCELLATION_PENDING_FINAL,
                    EXTENSION_PENDING_FINAL,
                    AWAITING_DIRECTOR_SELF_SANCTION):
        step = route[-1]
    else:
        return None

    role = step.get("role")
    task_class = {
        ROLE_UNIT_HEAD: "unit_head_review",
        ROLE_ESTABLISHMENT: "establishment_routing",
        ROLE_SANCTIONING_AUTHORITY: "final_sanction",
        ROLE_DIRECTOR_SELF: "final_sanction",
    }.get(role)
    if task_class is None:
        return None
    return task_class, role, _resolve_assignees(request, step)


def _resolve_assignees(request: LeaveRequest,
                         step: dict) -> list[int]:
    """Which people a route step lands on."""
    role = step.get("role")
    if role == ROLE_UNIT_HEAD:
        unit = authz.applicant_unit(request.user_id)
        if unit is None or unit.head_user_id is None:
            raise ConflictError(
                "No Unit Head is configured for the "
                "applicant's organizational unit.",
                code="no_unit_head_configured")
        return [unit.head_user_id]
    if role == ROLE_ESTABLISHMENT:
        designations = policy_service.establishment_designations()
        ids = list(EmployeeProfile.objects.filter(
            designation_name__in=designations,
            is_active=True).values_list("user_id", flat=True))
        if not ids:
            raise ConflictError(
                "No one holds an Establishment processing "
                "designation.", code="no_establishment_role")
        return sorted(ids)
    if role == ROLE_SANCTIONING_AUTHORITY:
        authority = step.get("authority")
        ids = list(EmployeeProfile.objects.filter(
            designation_name=authority,
            is_active=True).values_list("user_id", flat=True))
        if not ids:
            raise ConflictError(
                f"No one holds the {authority} designation "
                "the resolved route names as final authority.",
                code="no_sanctioning_authority")
        return sorted(ids)
    if role == ROLE_DIRECTOR_SELF:
        return [request.user_id]
    raise ConflictError(
        f"Unknown route step role {role!r}.",
        code="unknown_route_role")


# -- the engine -------------------------------------------------------------


def _verify_actor(request: LeaveRequest, actor: str,
                    principal) -> None:
    """The right office-holder, not merely a permission
    holder. A Unit Head elsewhere in the institute is not
    the reviewer for this applicant."""
    if actor == ACTOR_EMPLOYEE:
        if principal.user_id != request.user_id:
            raise PermissionDeniedError(
                "Only the applicant may do this.",
                code="not_actor")
    elif actor == ACTOR_SUBSTITUTE:
        nomination = _active_nomination(request)
        if (nomination is None
                or nomination.nominee_user_id != principal.user_id):
            raise PermissionDeniedError(
                "You are not the nominated substitute for "
                "this request.", code="not_actor")
    elif actor == ACTOR_UNIT_HEAD:
        authz.require_permission(principal, "elm.review.unit_head")
        if not authz.is_unit_head_of(principal, request.user_id):
            raise PermissionDeniedError(
                "You are not the Unit Head of the applicant's "
                "organizational unit.", code="not_actor")
    elif actor == ACTOR_ESTABLISHMENT:
        authz.require_permission(
            principal, "elm.review.establishment")
        if not authz.is_establishment_role(principal):
            raise PermissionDeniedError(
                "You do not hold an Establishment processing "
                "designation.", code="not_actor")
    elif actor == ACTOR_SANCTIONING:
        authz.require_permission(principal, "elm.sanction.final")
        final_step = (list(request.route or [{}]))[-1]
        if final_step.get("role") == ROLE_DIRECTOR_SELF:
            if principal.user_id != request.user_id:
                raise PermissionDeniedError(
                    "On the Director self-sanction path only "
                    "the applicant decides.", code="not_actor")
        elif not authz.is_final_authority(
                principal, final_step.get("authority") or ""):
            raise PermissionDeniedError(
                f"This decision rests with the "
                f"{final_step.get('authority')}.",
                code="not_actor")


def apply_transition(request: LeaveRequest, *, actor: str,
                       guard: str, outcome: str, reason: str,
                       principal) -> LeaveRequest:
    """Take one state-machine move. Raises before mutating
    anything when the move is not legal for this caller.

    The whole move — task retirement, state change, decision
    bookkeeping, side effects and the next task spawn — is one
    transaction: a failure halfway through must leave neither a
    half-completed task nor a taskless state behind.
    """
    with transaction.atomic():
        try:
            transition_ = machine.transition(
                request.kind, request.status, actor, guard)
        except InvalidTransition as exc:
            raise ConflictError(
                f"A {request.kind} request cannot move from "
                f"{request.status!r} by that action.",
                code="invalid_transition",
                details=[{"from": request.status,
                          "guard": guard, "actor": actor}],
            ) from exc

        _verify_actor(request, actor, principal)

        from_status = request.status

        # The task this move answers retires first.
        if transition_.task:
            task = _pending_task(request, transition_.task)
            if task is not None:
                _complete_task(task, outcome=outcome or guard,
                                 reason=reason,
                                 user_id=principal.user_id)

        request.status = transition_.to

        # Decision bookkeeping, keyed off the guard that fired.
        if guard in ("higher_recommend_establishment",
                     "higher_recommend_no_establishment"):
            request.recommendation = (
                "recommended" if outcome == "recommended"
                else "not_recommended")
            request.recommendation_reason = reason
        if (guard.startswith(("cl_rh_final",
                              "director_self_sanction"))
                or guard in ("sanction_approve",
                             "sanction_reject")):
            request.decided_by_user_id = principal.user_id
            request.decided_at = timezone.now()
            request.decision_reason = reason

        _log(request, "state_change", from_status=from_status,
                 to_status=transition_.to, actor=principal.user_id,
                 actor_label=authz.user_label(principal),
                 outcome=outcome, reason=reason)

        request.save()

        # Terminal side effects: the leave itself, and the money.
        if transition_.to == APPROVED:
            _on_approved(request, principal)
        elif transition_.to == REJECTED:
            notifications.notify_request_outcome(request, "rejected")

        spawn_tasks(request)
        return request


def _on_approved(request: LeaveRequest, principal) -> None:
    if request.kind == KIND_NEW:
        _post_leave(request, principal)
    elif request.kind == KIND_CANCELLATION:
        _apply_cancellation(request, principal)
    elif request.kind == KIND_EXTENSION:
        _post_extension(request, principal)
    notifications.notify_request_outcome(request, "approved")


# -- balance and ledger ------------------------------------------------------


def _account_for(request: LeaveRequest) -> LeaveAccount:
    """The applicant's account for this leave year and
    category, created on demand.

    A lazily created account seeds ``entitled_days`` from
    the policy entitlement — otherwise an account born at
    approval time would carry zero entitlement and show a
    negative balance.
    """
    from modules.elm.selectors import balances as balance_selector

    account, created = LeaveAccount.objects.get_or_create(
        user_id=request.user_id, leave_year=request.leave_year,
        category=request.category)
    if created and account.entitled_days == 0:
        profile = authz.employee_profile(request.user_id)
        account.entitled_days = policy_service.entitlement_for(
            request.category,
            profile.employee_kind if profile else None)
        account.save()
    return account


def _ledger(account: LeaveAccount, *, delta: Decimal, kind: str,
              request: LeaveRequest | None = None,
              offline_record=None, actor: int | None = None,
              reason: str = ""):
    balance_after = (account.opening_days
                     + account.entitled_days - account.used_days)
    return account.transactions.create(
        delta=delta, balance_after=balance_after, kind=kind,
        reason=reason, request=request,
        offline_record=offline_record, actor_user_id=actor,
    )


# -- terminal side effects ----------------------------------------------------


def _post_leave(request: LeaveRequest, principal) -> None:
    """Approval of a new application: post the leave and
    deduct the days (BR-EL-028/029)."""
    account = _account_for(request)
    account.used_days += request.days
    account.save()
    _ledger(account, delta=-request.days, kind="approval",
              request=request, actor=principal.user_id,
              reason="Leave sanctioned")
    record = LeaveRecord.objects.create(
        user_id=request.user_id, leave_year=request.leave_year,
        category=request.category,
        start_date=request.start_date, end_date=request.end_date,
        start_half=request.start_half, end_half=request.end_half,
        days=request.days, status="ongoing",
        station_leave=request.station_leave,
        station_details=request.station_details,
        source_request=request,
    )
    request.leave_record = record
    request.save(update_fields=["leave_record"])
    _log(request, "balance_posted", actor=principal.user_id,
           outcome="approval",
           payload={"days": str(request.days),
                    "record_id": record.id})


def _apply_cancellation(request: LeaveRequest,
                          principal) -> None:
    """Approval of a cancellation: mark the leave cancelled
    and restore the unexpired days (BR-EL-027)."""
    base = request.base_request
    record = base.leave_record
    if record is None or record.status != "ongoing":
        raise ConflictError(
            "The approved leave is no longer in force.",
            code="leave_not_active")
    effective = timezone.now().date()
    cancelled_days = remaining_days(record, effective)
    record.status = "cancelled"
    record.save(update_fields=["status", "updated_at"])
    if cancelled_days > ZERO:
        account = _account_for(base)
        account.used_days -= cancelled_days
        account.save()
        _ledger(account, delta=cancelled_days,
                  kind="cancellation_restoration",
                  request=request, actor=principal.user_id,
                  reason="Approved leave cancelled")
    _log(request, "balance_posted", actor=principal.user_id,
           outcome="cancellation_approved",
           payload={"days": str(cancelled_days)})


def _post_extension(request: LeaveRequest, principal) -> None:
    """Approval of an extension: only the incremental period
    is posted; the original approval stays the base (PS §9)."""
    base_record = request.base_request.leave_record
    if base_record is None or base_record.status != "ongoing":
        raise ConflictError(
            "The ongoing leave is no longer in force.",
            code="leave_not_active")
    record = LeaveRecord.objects.create(
        user_id=request.user_id, leave_year=request.leave_year,
        category=request.category,
        start_date=request.start_date, end_date=request.end_date,
        start_half=request.start_half, end_half=request.end_half,
        days=request.days, status="ongoing",
        extends_record=base_record, source_request=request,
    )
    account = _account_for(request)
    account.used_days += request.days
    account.save()
    _ledger(account, delta=-request.days,
              kind="extension_posting", request=request,
              actor=principal.user_id,
              reason="Extension sanctioned")
    _log(request, "balance_posted", actor=principal.user_id,
           outcome="extension_approved",
           payload={"days": str(request.days),
                    "record_id": record.id})


def remaining_days(record: LeaveRecord,
                     effective) -> Decimal:
    """Days of an ongoing record from ``effective`` to its
    end, under the category's counting rule."""
    if effective > record.end_date:
        return ZERO
    start = max(effective, record.start_date)
    interval = LeaveInterval(
        category=record.category, start=start,
        end=record.end_date,
        start_half=(record.start_half
                    if start == record.start_date else HALF_FULL),
        end_half=record.end_half,
    )
    return count_days(interval, closed=closed_dates())


# -- shared actors ------------------------------------------------------------


def _active_nomination(request: LeaveRequest):
    return SubstituteNomination.objects.filter(
        request=request, is_active=True).first()


def create_resumption_task(resumption, assignee_user_ids) -> list[LeaveTask]:
    """Queue the resumption review with the applicable
    Sanctioning Authority (EL-UC-011).

    The task hangs off the original application when the
    leave went through ELM; for offline-recorded leave
    there is no application, so the task stands alone and
    points at the resumption itself. Where the authority is
    an office held by several people, each holder gets
    their own task — first mover wins (BR-EL-027).
    """
    tasks = []
    for user_id in assignee_user_ids:
        task = LeaveTask.objects.create(
            request=resumption.request,
            resumption=resumption,
            task_class="resumption_review",
            assignee_user_id=user_id,
            assignee_role=ROLE_SANCTIONING_AUTHORITY,
        )
        _log(resumption.request, "task_assigned",
             outcome="resumption_review",
             payload={"task_id": task.id,
                      "resumption_id": resumption.id,
                      "record_id": resumption.record_id,
                      "assignee_user_id": user_id})
        notifications.notify_task_assigned(task)
        tasks.append(task)
    return tasks


def route_is_director(request: LeaveRequest) -> bool:
    route = list(request.route or [])
    return bool(route) and route[0].get("role") == ROLE_DIRECTOR_SELF


# -- actor entry points ---------------------------------------------------------


def withdraw(request: LeaveRequest, principal, *,
               reason: str = "") -> LeaveRequest:
    """Withdraw a pending request (EL-UC-007, BR-EL-022/023).

    Valid from every pending pre-final state. Retires every
    remaining task, releases the substitute gate and informs
    the concerned roles — everyone holding a live task on the
    request, plus the applicant's confirmation (BR-EL-035).
    """
    if principal.user_id != request.user_id:
        raise PermissionDeniedError(
            "Only the applicant may withdraw the request.",
            code="not_actor")
    if request.status in TERMINAL_STATES:
        raise ConflictError(
            "This request is already closed.",
            code="invalid_transition")
    try:
        machine.transition(request.kind, request.status,
                           ACTOR_EMPLOYEE, "withdraw_before_final")
    except InvalidTransition as exc:
        raise ConflictError(
            "This request is no longer in a state that can be "
            "withdrawn.", code="invalid_transition") from exc

    with transaction.atomic():
        from_status = request.status
        # The concerned roles are whoever holds a live task on
        # the request right now — capture them before the
        # tasks are retired.
        watchers = sorted({
            t.assignee_user_id
            for t in LeaveTask.objects.filter(request=request,
                                              status="pending")})

        request.status = WITHDRAWN
        request.withdrawn_at = timezone.now()
        request.withdraw_reason = reason
        request.save()

        _cancel_tasks(
            LeaveTask.objects.filter(request=request,
                                     status="pending"),
            reason="Request withdrawn")
        nomination = _active_nomination(request)
        if nomination is not None:
            nomination.status = "withdrawn"
            nomination.is_active = False
            nomination.save()

        _log(request, "state_change", from_status=from_status,
             to_status=WITHDRAWN, actor=principal.user_id,
             actor_label=authz.user_label(principal),
             outcome="withdrawn", reason=reason)
        notifications.notify_request_withdrawn(request, watchers)
    return request



@transaction.atomic
def respond_substitute(request: LeaveRequest, principal, *,
                         accept: bool,
                         reason: str = "") -> LeaveRequest:
    """The substitute accepts or declines (EL-UC-002).

    Accept releases the consent gate and routing proceeds;
    decline does not release it — the request waits for the
    applicant to nominate another substitute or withdraw
    (BR-EL-015/016).
    """
    nomination = _active_nomination(request)
    if (nomination is None
            or nomination.nominee_user_id != principal.user_id):
        raise PermissionDeniedError(
            "You are not the nominated substitute for this "
            "request.", code="not_actor")
    if request.status not in (AWAITING_SUBSTITUTE_RESPONSE,
                              AWAITING_EXTENSION_SUBSTITUTE):
        raise ConflictError(
            "No substitute response is awaited right now.",
            code="invalid_transition")

    if accept:
        if request.kind == KIND_NEW:
            guard = ("substitute_accepted_director"
                     if route_is_director(request)
                     else "substitute_accepted_not_director")
        elif route_is_director(request):
            guard = "substitute_accepted_director"
        else:
            guard = "substitute_accepted"
        outcome = "accepted"
    else:
        guard = "substitute_declined"
        outcome = "declined"

    # The transition first — it re-verifies the actor against
    # the still-active nomination — then record the response.
    result = apply_transition(
        request, actor=ACTOR_SUBSTITUTE, guard=guard,
        outcome=outcome, reason=reason, principal=principal)
    nomination.status = outcome
    nomination.responded_at = timezone.now()
    nomination.response_reason = reason
    nomination.is_active = accept
    nomination.save()
    return result


def nominate_replacement(request: LeaveRequest, principal, *,
                           nominee_user_id: int,
                           reason: str = "") -> LeaveRequest:
    """Nominate a replacement substitute after a decline
    (EL-UC-019, BR-EL-014/015).

    Only the applicant, and only while the request sits in
    the applicant-action state a decline left it in. The
    nominee must satisfy the same eligibility rules as the
    original (BR-EL-014); on success the consent gate
    re-opens with a fresh task for the new nominee.
    """
    if principal.user_id != request.user_id:
        raise PermissionDeniedError(
            "Only the applicant may nominate a replacement "
            "substitute.", code="not_actor")
    applicant_action = (
        machine.EXTENSION_APPLICANT_ACTION_REQUIRED
        if request.kind == KIND_EXTENSION
        else machine.APPLICANT_ACTION_REQUIRED)
    if request.status != applicant_action:
        raise ConflictError(
            "A replacement substitute can be nominated only "
            "after a decline.", code="invalid_transition")

    from modules.elm.services.applications import _validate_nominee

    _validate_nominee(request, nominee_user_id)
    SubstituteNomination.objects.create(
        request=request, nominee_user_id=nominee_user_id)
    return apply_transition(
        request, actor=ACTOR_EMPLOYEE, guard="replacement_nominated",
        outcome="replacement_nominated", reason=reason,
        principal=principal)


def unit_head_decide(request: LeaveRequest, principal, *,
                       outcome: str,
                       reason: str = "") -> LeaveRequest:
    """Unit Head review (EL-UC-003).

    CL/RH: the Unit Head is the final authority, so the
    outcome is an approve/reject decision. Higher-sanction
    categories: the Unit Head records Recommended /
    Not Recommended and the request moves up the hierarchy —
    either way it advances; the recommendation is advice to
    the authority, not a veto. The two vocabularies are
    state-specific (BR-EL-016/017): a recommend on a CL/RH
    review, or an approve/reject on a higher-sanction review,
    is refused as invalid_outcome.
    """
    if request.category in ("CL", "RH"):
        if outcome not in ("approve", "reject"):
            raise ConflictError(
                "A CL/RH review by the Unit Head decides: the "
                "outcome is approve or reject.",
                code="invalid_outcome")
        guard = ("cl_rh_final_approve" if outcome == "approve"
                 else "cl_rh_final_reject")
    else:
        if outcome not in ("recommended", "not_recommended"):
            raise ConflictError(
                "A higher-sanction review by the Unit Head "
                "recommends: the outcome is recommended or "
                "not_recommended.", code="invalid_outcome")
        has_establishment = any(
            step.get("role") == ROLE_ESTABLISHMENT
            for step in (request.route or []))
        guard = ("higher_recommend_establishment"
                 if has_establishment
                 else "higher_recommend_no_establishment")
    return apply_transition(
        request, actor=ACTOR_UNIT_HEAD, guard=guard,
        outcome=outcome, reason=reason, principal=principal)


def establishment_forward(request: LeaveRequest, principal, *,
                            reason: str = "") -> LeaveRequest:
    """Establishment processing verifies and routes (EL-UC-004)
    — it is never a sanctioning decision (BR-EL-018)."""
    return apply_transition(
        request, actor=ACTOR_ESTABLISHMENT,
        guard="establishment_routing_valid",
        outcome="forwarded", reason=reason, principal=principal)


def final_decide(request: LeaveRequest, principal, *,
                   outcome: str,
                   reason: str = "") -> LeaveRequest:
    """The final sanctioning decision (EL-UC-005/006).

    The Director's own *application* (BR-EL-019/020) takes the
    spec's director self-sanction guards; every other final
    decision state — including a Director's own cancellation or
    extension — takes the plain sanction guards. On the
    director path only the applicant may decide, which the
    actor check enforces either way.
    """
    if request.kind == KIND_NEW and route_is_director(request):
        guard = ("director_self_sanction_approve"
                 if outcome == "approve"
                 else "director_self_sanction_reject")
    else:
        guard = ("sanction_approve" if outcome == "approve"
                 else "sanction_reject")
    return apply_transition(
        request, actor=ACTOR_SANCTIONING, guard=guard,
        outcome=outcome, reason=reason, principal=principal)
