"""Special archival (PS 3.4, UC-BA-010, BR-BA-018).

The request originates offline — from any authority — and never enters a
BADMS workflow. What BADMS models is the Super Admin performing the
corresponding operation for Sensitive research data and recording the
outcome with an audit event.
"""
from __future__ import annotations

from django.db import transaction

from core.api.exceptions import DomainError, PermissionDeniedError
from modules.badms.models import SpecialArchivalRecord
from modules.badms.selectors import authz
from modules.badms.services import audit as audit_service


def perform_special_archival(*, actor, data_reference: str, reason: str = "",
                             note: str = "") -> SpecialArchivalRecord:
    """Perform and record a special archival operation.

    Only the Super Admin may perform it (AFR-BA-038): the service re-checks
    the grant because nothing else gates a management-command call.
    """
    if actor is None or not authz.has_permission(
            actor, "badms.special_archival.perform"):
        raise PermissionDeniedError(
            "Only the Super Admin may perform a special archival operation.")
    data_reference = (data_reference or "").strip()
    if not data_reference:
        raise DomainError("The data covered by the offline request must "
                              "be identified.", code="invalid_special_archival")

    with transaction.atomic():
        record = SpecialArchivalRecord.objects.create(
            performed_by_user_id=getattr(actor, "user_id", 0) or 0,
            data_reference=data_reference, reason=reason or "",
            outcome="completed", note=note or "")
        audit_service.record_event(
            action="special_archival.performed", actor=actor,
            actor_kind="admin", object_type="special_archival",
            object_id=record.pk, detail=data_reference)
    return record


def fail_special_archival(*, actor, data_reference: str, error: str) -> None:
    """The operation could not be completed (UC-BA-010 E1): nothing is
    recorded as completed and the failure reaches the Super Admin as an
    error, with the prior stored-data state preserved."""
    if actor is None or not authz.has_permission(
            actor, "badms.special_archival.perform"):
        raise PermissionDeniedError(
            "Only the Super Admin may perform a special archival operation.")
    audit_service.record_event(
        action="special_archival.failed", actor=actor, actor_kind="admin",
        object_type="special_archival", object_id="",
        detail=f"{data_reference}: {error}"[:300])
