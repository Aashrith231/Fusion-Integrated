"""Storage monitoring and extension requests (PS 3.4, UC-BA-022, CW-BA-02).

The threshold monitor keeps each user's full-quota status current (AFR-BA-051);
the extension service validates a request against the user's usage
(BR-BA-016) and the available infrastructure (AFR-BA-052) before routing it
to the user's HoD. Processing ends with the recorded HoD decision — no
post-approval action is required in this version.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from core.api.exceptions import DomainError, PermissionDeniedError
from modules.badms.domain import storage_rules
from modules.badms.models import (
    StorageExtensionRequest,
    StorageInfrastructure,
    StorageProfile,
)
from modules.badms.selectors import authz
from modules.badms.services import audit as audit_service
from modules.badms.services import locking, notifications

log = logging.getLogger("fusion.badms.storage")


def ensure_profile(user_id: int) -> StorageProfile:
    """The user's quota row, created on first touch so submission validation
    never needs a "no profile" branch."""
    profile, _ = StorageProfile.objects.get_or_create(user_id=user_id)
    return profile


def record_usage(user_id: int, used_bytes: int, *,
                 quota_bytes: int | None = None) -> StorageProfile:
    """Write a usage reading and re-evaluate the threshold (UC-BA-022 M1..M3).

    E1: an unusable reading (negative) preserves the previous status and
    asserts nothing new.
    """
    if used_bytes < 0:
        raise ValueError("A storage reading cannot be negative.")
    profile = ensure_profile(user_id)
    if quota_bytes is not None:
        profile.quota_bytes = quota_bytes
    profile.used_bytes = used_bytes
    profile.full = storage_rules.is_full(used_bytes, profile.quota_bytes)
    profile.checked_at = timezone.now()
    profile.save(update_fields=["used_bytes", "full", "checked_at",
                                "quota_bytes", "updated_at"])
    return profile


def monitor_all(*, now=None) -> int:
    """The beat entry point: re-evaluate every profile against its quota."""
    count = 0
    for profile in StorageProfile.objects.all():
        was_full = profile.full
        profile.full = storage_rules.is_full(profile.used_bytes,
                                             profile.quota_bytes)
        profile.checked_at = now or timezone.now()
        profile.save(update_fields=["full", "checked_at", "updated_at"])
        if profile.full != was_full:
            log.info("badms.storage.threshold_crossed user=%s full=%s",
                     profile.user_id, profile.full)
        count += 1
    return count


def primary_infrastructure() -> StorageInfrastructure:
    """The pool user quotas draw from; created on first touch."""
    pool, _ = StorageInfrastructure.objects.get_or_create(
        name="primary",
        defaults={"capacity_bytes": 100 * 1024 * 1024 * 1024,
                  "allocated_bytes": 0})
    return pool


def submit_extension(*, actor, requested_bytes: int, justification: str,
                     attachment: str = "") -> StorageExtensionRequest:
    """Submit a storage-extension request (UC-BA-007).

    The request is valid only when the user's quota is full (BR-BA-016) and
    the requested amount does not exceed the available infrastructure
    (AFR-BA-052). Validation failure raises before any row is created (E1).
    """
    if actor is None:
        raise PermissionDeniedError("Authentication required.")
    justification = (justification or "").strip()
    if not justification:
        raise DomainError("A justification is required.",
                              code="invalid_extension")
    if requested_bytes is None or requested_bytes <= 0:
        raise DomainError("The requested extension must be a positive "
                              "amount of storage.", code="invalid_extension")

    uid = getattr(actor, "user_id", 0) or 0
    profile = ensure_profile(uid)
    reason = storage_rules.extension_usage_check(profile.used_bytes,
                                                 profile.quota_bytes)
    if reason:
        raise DomainError(reason, code="quota_not_full")
    pool = primary_infrastructure()
    reason = storage_rules.extension_infra_check(requested_bytes,
                                                 pool.available_bytes)
    if reason:
        raise DomainError(reason, code="insufficient_infrastructure")
    department = authz.department_of(actor)

    with transaction.atomic():
        request = StorageExtensionRequest.objects.create(
            user_id=uid, department=department, requested_bytes=requested_bytes,
            justification=justification, attachment=attachment or "",
            usage_at_request=profile.used_bytes,
            quota_at_request=profile.quota_bytes, status="submitted")
        audit_service.record_event(
            action="storage_extension.submitted", actor=actor,
            object_type="storage_extension", object_id=request.pk)
        notifications.enqueue(
            topic="storage.submitted",
            dedupe_key=f"storage-submitted-{request.pk}",
            subject="Storage-extension request received",
            body="Your storage-extension request was received and routed to "
                 "your department head.",
            recipient_user_id=uid)
        if department:
            notifications.enqueue(
                topic="storage.submitted",
                dedupe_key=f"storage-hod-{request.pk}",
                subject="New storage-extension request to review",
                body=f"A storage-extension request from department "
                     f"{department} is awaiting review.",
                recipient_email=f"{department.lower()}-hod@iiitdmj.ac.in")
    return request


def decide_extension(*, actor, request_id: int, decision: str,
                     note: str = "") -> StorageExtensionRequest:
    """The HoD approves or rejects (UC-BA-008, BR-BA-009, BR-BA-010).

    Only the respective HoD may decide, and the decision is informed by the
    request's recorded criteria — usage, justification, attachment and the
    infrastructure picture the API supplies (BR-BA-017).
    """
    if actor is None or not authz.has_permission(actor, "badms.storage.decide"):
        raise PermissionDeniedError(
            "Only a department head may decide a storage-extension request.")
    request = StorageExtensionRequest.objects.filter(pk=request_id).first()
    if request is None:
        raise LookupError("No such storage-extension request.")
    if not authz.in_department(actor, request.department):
        raise PermissionDeniedError(
            "This request belongs to another department.")
    decision = (decision or "").strip().lower()
    if decision not in ("approve", "reject"):
        raise DomainError("Decision must be approve or reject.",
                              code="invalid_decision")

    from modules.badms.domain import states
    uid = getattr(actor, "user_id", 0) or 0
    with transaction.atomic():
        request = locking.locked(StorageExtensionRequest.objects, request_id)
        if request is None:
            raise LookupError("No such storage-extension request.")
        if not authz.in_department(actor, request.department):
            raise PermissionDeniedError(
                "This request belongs to another department.")
        request.status = states.extension_transition(
            request.status, "approve" if decision == "approve" else "reject")
        request.decided_by_user_id = uid
        request.decided_at = timezone.now()
        request.save(update_fields=["status", "decided_by_user_id",
                                    "decided_at", "updated_at"])
        audit_service.record_event(
            action=f"storage_extension.{decision}d", actor=actor,
            actor_kind="admin", object_type="storage_extension",
            object_id=request.pk)
        notifications.enqueue(
            topic="storage.decided",
            dedupe_key=f"storage-decision-{request.pk}-{decision}",
            subject=f"Storage-extension request {decision}d",
            body=("Your storage-extension request was approved."
                  if decision == "approve"
                  else "Your storage-extension request was rejected."),
            recipient_user_id=request.user_id)
    return request
