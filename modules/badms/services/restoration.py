"""Data restoration (PS 3.3, UC-BA-016..018, CW-BA-03).

Non-Sensitive archived data takes the standard path: request, then the
SysAdmin executes the technical restoration. Sensitive data is blocked until
a SysAdmin approval is recorded (BR-BA-005) — and there is no HoD
restoration-authorization route in this version.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from core.api.exceptions import ConflictError, DomainError, NotFoundError, PermissionDeniedError
from modules.badms.domain import states
from modules.badms.models import ArchivalRequest, RestorationRequest
from modules.badms.selectors import authz
from modules.badms.services import audit as audit_service
from modules.badms.services import notifications

log = logging.getLogger("fusion.badms.restoration")

#: Only archived data can be restored.
RESTORABLE_STATUSES = ("classified", "encrypted")


def request_restoration(*, actor, archival_id: int,
                        note: str = "") -> RestorationRequest:
    """Request restoration of archived data (UC-BA-016).

    E1: an archive that cannot be located, or one the requester may not
    access, is refused without creating a request.
    """
    if actor is None:
        raise PermissionDeniedError("Authentication required.")
    archival = ArchivalRequest.objects.filter(pk=archival_id).first()
    if archival is None or archival.status not in RESTORABLE_STATUSES:
        raise NotFoundError("No such archived data.")
    uid = getattr(actor, "user_id", 0) or 0
    if archival.user_id != uid:
        raise PermissionDeniedError(
            "You may request restoration only of your own archived data.")

    classification = archival.classification or archival.initial_classification
    from modules.badms.domain import policy
    to_state = "pending_approval" if classification == policy.SENSITIVE \
        else "requested"

    with transaction.atomic():
        request = RestorationRequest.objects.create(
            user_id=uid, archival=archival, classification=classification,
            status=to_state, note=note or "")
        audit_service.record_event(
            action="restoration.requested", actor=actor,
            object_type="restoration", object_id=request.pk,
            detail=f"classification={classification}")
        if to_state == "pending_approval":
            notifications.enqueue(
                topic="restoration.decided",
                dedupe_key=f"restoration-pending-{request.pk}",
                subject="Sensitive restoration awaiting approval",
                body=f"A restoration request for {archival.file_name!r} "
                     f"awaits SysAdmin approval.",
                recipient_email=_sysadmin_inbox())
    return request


def _sysadmin_inbox() -> str:
    from django.conf import settings
    return getattr(settings, "BADMS_SYSADMIN_ALERT_EMAIL",
                   "sysadmin-alert@iiitdmj.ac.in")


def decide_request(*, actor, request_id: int, decision: str,
                   note: str = "") -> RestorationRequest:
    """Approve or reject a Sensitive restoration (UC-BA-017, BR-BA-005)."""
    if actor is None or not authz.has_permission(
            actor, "badms.restoration.approve"):
        raise PermissionDeniedError(
            "Only a SysAdmin may approve a Sensitive restoration.")
    request = RestorationRequest.objects.filter(pk=request_id).first()
    if request is None:
        raise LookupError("No such restoration request.")
    if request.status != "pending_approval":
        raise ConflictError(
            "Only a Sensitive restoration awaiting approval can be decided.",
            code="invalid_state")
    decision = (decision or "").strip().lower()
    if decision not in ("approve", "reject"):
        raise DomainError("Decision must be approve or reject.",
                              code="invalid_decision")

    uid = getattr(actor, "user_id", 0) or 0
    with transaction.atomic():
        request.status = states.restoration_transition(
            "pending_approval", "approve" if decision == "approve" else "reject")
        request.decided_by_user_id = uid
        request.decided_at = timezone.now()
        request.save(update_fields=["status", "decided_by_user_id",
                                    "decided_at", "updated_at"])
        audit_service.record_event(
            action=f"restoration.{decision}d", actor=actor, actor_kind="admin",
            object_type="restoration", object_id=request.pk)
        notifications.enqueue(
            topic="restoration.decided",
            dedupe_key=f"restoration-decision-{request.pk}-{decision}",
            subject=f"Restoration request {decision}d",
            body=("Your restoration request was approved and may proceed."
                  if decision == "approve"
                  else "Your restoration request was rejected."),
            recipient_user_id=request.user_id)
    return request


def execute_restoration(*, actor, request_id: int) -> RestorationRequest:
    """Technically restore archived data (UC-BA-018).

    A Sensitive request must already be approved; a non-Sensitive request
    takes the standard path straight from `requested`. Retrieval failure is
    recorded as a failure with the audit history preserved (E1).
    """
    if actor is None or not authz.has_permission(
            actor, "badms.restoration.execute"):
        raise PermissionDeniedError(
            "Only a SysAdmin may execute a restoration.")
    request = RestorationRequest.objects.filter(pk=request_id).select_related(
        "archival").first()
    if request is None:
        raise LookupError("No such restoration request.")
    if request.status not in ("requested", "approved_for_restoration"):
        raise ConflictError(
            "This restoration request is not eligible for execution.",
            code="invalid_state")
    if request.status == "approved_for_restoration" \
            and request.classification != "sensitive":
        raise ConflictError("State and classification disagree.",
                            code="invalid_state")

    uid = getattr(actor, "user_id", 0) or 0
    failure = _perform_restore(request)
    with transaction.atomic():
        if failure is None:
            request.status = states.restoration_transition(
                request.status, "execute")
        else:
            request.status = states.restoration_transition(
                request.status, "execute_failed")
            request.error = failure[:300]
        request.executed_by_user_id = uid
        request.executed_at = timezone.now()
        request.save(update_fields=["status", "executed_by_user_id",
                                    "executed_at", "error", "updated_at"])
        audit_service.record_event(
            action="restoration.executed",
            outcome="success" if failure is None else "failure",
            actor=actor, actor_kind="admin",
            object_type="restoration", object_id=request.pk,
            detail=failure or "")
        notifications.enqueue(
            topic="restoration.completed",
            dedupe_key=f"restoration-executed-{request.pk}",
            subject=("Restoration completed" if failure is None
                     else "Restoration failed"),
            body=("Your archived data was restored." if failure is None
                  else f"Restoration of {request.archival.file_name!r} "
                       f"failed: {failure}"),
            recipient_user_id=request.user_id)
    return request


def _perform_restore(request: RestorationRequest) -> str | None:
    """The technical restoration itself. Returns None on success or a failure
    reason.

    A referenced artifact that cannot be located is a real failure. An
    archive with no artifact (non-Sensitive data, whose workflow ends at the
    classified state) is restored as a recorded operation.
    """
    from pathlib import Path

    from django.conf import settings

    archive_ref = request.archival.archive_ref
    if not archive_ref:
        return None
    source = Path(archive_ref)
    if not source.exists():
        return "The archived artifact could not be located."
    target_root = Path(getattr(
        settings, "BADMS_RESTORE_ROOT",
        Path(settings.BASE_DIR) / "var" / "badms" / "restored"))
    target_root.mkdir(parents=True, exist_ok=True)
    target = target_root / source.name
    try:
        target.write_bytes(source.read_bytes())
    except OSError as exc:
        return f"{exc.__class__.__name__}: {exc}"
    return None
