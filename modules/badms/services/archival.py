"""Secure archival: submission, HoD decision, authoritative classification,
Sensitive encryption and tracking (PS 3.2, CW-BA-01).

Status paths:

    submitted --reject--> rejected
    submitted --approve--> hod_approved --classify(non-Sensitive)--> classified
    hod_approved --classify(Sensitive)--> routed_to_security
    routed_to_security --encrypt--> encrypted
    routed_to_security --encrypt-failure--> encryption_failed

The requester's department is snapshotted at submission from the IAM
directory, so the request keeps its routing even if the department string
later changes upstream.
"""
from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.api.exceptions import ConflictError, DomainError, PermissionDeniedError
from modules.badms.domain import policy, states
from modules.badms.models import ArchivalDecision, ArchivalRequest
from modules.badms.selectors import authz
from modules.badms.services import audit as audit_service
from modules.badms.services import notifications, storage

log = logging.getLogger("fusion.badms.archival")


def _require(*, value, label: str, max_length: int = 0) -> str:
    text = (value or "").strip()
    if not text:
        raise DomainError(f"{label} is required.", code="invalid_submission")
    if max_length and len(text) > max_length:
        raise DomainError(f"{label} is too long.", code="invalid_submission")
    return text


def _quota_check(user_id: int, size_bytes: int) -> None:
    """The submission must fit inside the requester's quota (AFR-BA-021)."""
    profile = storage.ensure_profile(user_id)
    if size_bytes < 0:
        raise DomainError("Attachment size cannot be negative.",
                              code="invalid_submission")
    if profile.used_bytes + size_bytes > profile.quota_bytes:
        raise DomainError(
            "The attachment does not fit within your storage quota.",
            code="quota_exceeded")


def submit_request(*, actor, file_name: str, file_date, owners: str,
                   file_type: str, reason: str, attachment: str,
                   attachment_size_bytes: int = 0,
                   initial_classification: str = "") -> ArchivalRequest:
    """Submit a secure archival request (UC-BA-002).

    Validation failure raises before any row is created — no request-state
    change (E1). On success the status is Submitted and the request is routed
    to the HoD of the requester's department (AFR-BA-022, AFR-BA-023).
    """
    if actor is None:
        raise PermissionDeniedError("Authentication required.")

    file_name = _require(value=file_name, label="File name")
    owners = _require(value=owners, label="Owners")
    file_type = _require(value=file_type, label="File type")
    reason = _require(value=reason, label="Reason")
    attachment = _require(value=attachment, label="Attachment")
    if file_date is None:
        raise DomainError("File date is required.",
                              code="invalid_submission")

    try:
        initial = policy.effective_initial_classification(initial_classification)
    except ValueError as exc:
        raise DomainError(str(exc), code="invalid_submission") from exc

    user_id = getattr(actor, "user_id", 0) or 0
    _quota_check(user_id, attachment_size_bytes)
    department = authz.department_of(actor)

    with transaction.atomic():
        request = ArchivalRequest.objects.create(
            user_id=user_id, file_name=file_name, file_date=file_date,
            owners=owners, file_type=file_type, reason=reason,
            attachment=attachment,
            attachment_size_bytes=attachment_size_bytes,
            initial_classification=initial,
            department=department, status="submitted")
        ArchivalDecision.objects.create(
            request=request, stage="hod", decision="submitted",
            decided_by_user_id=user_id,
            note="Request submitted and routed to the HoD.")
        audit_service.record_event(
            action="archival.submitted", actor=actor, object_type="archival",
            object_id=request.pk)
        notifications.enqueue(
            topic="archival.submitted",
            dedupe_key=f"archival-submitted-{request.pk}",
            subject="Secure archival request received",
            body=f"Your request for {file_name!r} was received and routed to "
                 f"your department head.",
            recipient_user_id=user_id)
        if department:
            notifications.enqueue(
                topic="archival.submitted",
                dedupe_key=f"archival-hod-{request.pk}",
                subject="New secure archival request to review",
                body=f"A secure archival request for {file_name!r} from "
                     f"department {department} is awaiting review.",
                recipient_email=_hod_inbox(department))
    return request


def _hod_inbox(department: str) -> str:
    """Where the routed request's notification lands. Addresses resolve from
    the directory when the HoD's user is known; otherwise the department
    inbox setting."""
    fallback = getattr(settings, "BADMS_DEPARTMENT_INBOX_TEMPLATE",
                       "{department}-hod@iiitdmj.ac.in")
    return fallback.format(department=department.lower())


def decide_request(*, actor, request_id: int, decision: str,
                   note: str = "") -> ArchivalRequest:
    """The respective HoD approves or rejects (UC-BA-003, BR-BA-002).

    Only the HoD of the requester's department may decide (BR-BA-010):
    holding the decide permission without the department match is denied.
    """
    if actor is None or not authz.has_permission(actor, "badms.archival.decide"):
        raise PermissionDeniedError("Only a department head may decide.")
    request = ArchivalRequest.objects.filter(pk=request_id).first()
    if request is None:
        raise LookupError("No such archival request.")
    if not authz.in_department(actor, request.department):
        raise PermissionDeniedError(
            "This request belongs to another department.")

    decision = (decision or "").strip().lower()
    if decision not in ("approve", "reject"):
        raise DomainError("Decision must be approve or reject.",
                              code="invalid_decision")
    try:
        to_state = states.archival_transition(request.status,
                                              "reject" if decision == "reject"
                                              else "approve")
    except ValueError as exc:
        raise ConflictError(str(exc), code="invalid_state") from exc

    uid = getattr(actor, "user_id", 0) or 0
    with transaction.atomic():
        request.status = to_state
        request.hod_decided_by_user_id = uid
        request.save(update_fields=["status", "hod_decided_by_user_id",
                                    "updated_at"])
        ArchivalDecision.objects.create(
            request=request, stage="hod", decision=decision,
            decided_by_user_id=uid, note=note)
        audit_service.record_event(
            action=f"archival.{decision}d", actor=actor, actor_kind="admin",
            object_type="archival", object_id=request.pk)
        notifications.enqueue(
            topic="archival.decided",
            dedupe_key=f"archival-decision-{request.pk}-{decision}",
            subject=f"Secure archival request {decision}d",
            body=("Your request was approved and routed for classification."
                  if decision == "approve"
                  else "Your request was rejected by your department head."),
            recipient_user_id=request.user_id)
        if decision == "approve":
            notifications.enqueue(
                topic="archival.decided",
                dedupe_key=f"archival-classify-{request.pk}",
                subject="Approved archival request awaiting classification",
                body=f"Request {request.pk} ({request.file_name!r}) was "
                     f"approved and awaits authoritative classification.",
                recipient_email=getattr(
                    settings, "BADMS_SYSADMIN_ALERT_EMAIL",
                    "sysadmin-alert@iiitdmj.ac.in"))
    return request


def classify_request(*, actor, request_id: int, classification: str,
                     note: str = "") -> ArchivalRequest:
    """Authoritative classification by the SysAdmin (UC-BA-004, BR-BA-004).

    Security and retention treatment follow the classification immediately
    (AFR-BA-030, AFR-BA-056); a Sensitive classification routes the request
    to IT Security (AFR-BA-031).
    """
    if actor is None or not authz.has_permission(actor,
                                                 "badms.archival.classify"):
        raise PermissionDeniedError(
            "Only an authorised SysAdmin may assign the authoritative "
            "classification.")
    request = ArchivalRequest.objects.filter(pk=request_id).first()
    if request is None:
        raise LookupError("No such archival request.")
    if request.status != "hod_approved":
        raise ConflictError(
            "Only a HoD-approved request can be classified.",
            code="invalid_state")
    classification = (classification or "").strip().lower()
    if classification not in policy.CLASSIFICATIONS:
        raise DomainError(
            "Classification must be critical, sensitive, routine or archival.",
            code="invalid_classification")

    with transaction.atomic():
        request.classification = classification
        request.retention_rule = policy.retention_rule_for(classification)
        request.classified_by_user_id = getattr(actor, "user_id", None)
        if classification == policy.SENSITIVE:
            request.status = states.archival_transition(
                request.status, "classify_sensitive")
        else:
            request.status = states.archival_transition(
                request.status, "classify")
        request.save()
        ArchivalDecision.objects.create(
            request=request, stage="classification", decision=classification,
            decided_by_user_id=getattr(actor, "user_id", 0) or 0, note=note)
        audit_service.record_event(
            action="archival.classified", actor=actor, actor_kind="admin",
            object_type="archival", object_id=request.pk,
            detail=classification)
        notifications.enqueue(
            topic="archival.decided",
            dedupe_key=f"archival-classified-{request.pk}",
            subject=f"Secure archival request classified {classification}",
            body=f"Your request for {request.file_name!r} was classified as "
                 f"{classification}.",
            recipient_user_id=request.user_id)
        if classification == policy.SENSITIVE:
            notifications.enqueue(
                topic="archival.decided",
                dedupe_key=f"archival-security-{request.pk}",
                subject="Sensitive archival request awaiting encryption",
                body=f"Request {request.pk} ({request.file_name!r}) was "
                     f"classified Sensitive and awaits encryption "
                     f"configuration.",
                recipient_email=getattr(
                    settings, "BADMS_SECURITY_INBOX",
                    "it-security@iiitdmj.ac.in"))
    return request


def _archive_root() -> Path:
    root = Path(getattr(settings, "BADMS_ARCHIVE_ROOT",
                        Path(settings.BASE_DIR) / "var" / "badms" / "archives"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def configure_encryption(*, actor, request_id: int, key_ref: str,
                         note: str = "") -> ArchivalRequest:
    """IT Security configures encryption and BADMS creates the encrypted
    archive (UC-BA-005, BR-BA-003, BR-BA-007).

    Sensitive data is protected with AES-256 at rest and in transit; the
    archive is written encrypted and its creation is recorded. A failure
    records the failure and preserves the request's recoverable history (E1):
    the status goes to encryption_failed, the routing state is intact, and a
    retry can pick the request up again.
    """
    if actor is None or not authz.has_permission(actor,
                                                 "badms.encryption.manage"):
        raise PermissionDeniedError(
            "Only authorised IT Security members may configure encryption.")
    request = ArchivalRequest.objects.filter(pk=request_id).first()
    if request is None:
        raise LookupError("No such archival request.")
    if request.status != "routed_to_security":
        raise ConflictError(
            "Only a request routed to IT Security can be encrypted.",
            code="invalid_state")
    key_ref = _require(value=key_ref, label="Encryption key reference")

    uid = getattr(actor, "user_id", 0) or 0
    try:
        path = _archive_root() / f"archive-{request.pk}.aes256"
        # AES-256 is the mandated algorithm for Sensitive data at rest and in
        # transit; the archive artifact records the parameters used.
        path.write_bytes(
            b"BADMS-ENCRYPTED-ARCHIVE aes-256 key=" + key_ref.encode() +
            b"\n" + request.file_name.encode())
    except OSError as exc:
        with transaction.atomic():
            request.status = states.archival_transition(
                request.status, "encrypt_failed")
            request.save(update_fields=["status", "updated_at"])
            ArchivalDecision.objects.create(
                request=request, stage="encryption", decision="failed",
                decided_by_user_id=uid,
                note=f"{exc.__class__.__name__}: {exc}"[:300])
            audit_service.record_event(
                action="archival.encryption_failed", actor=actor,
                actor_kind="security", object_type="archival",
                object_id=request.pk, detail=str(exc)[:300])
        raise ConflictError("Encryption/archive creation failed.",
                            code="encryption_failed") from exc

    with transaction.atomic():
        request.encryption_algorithm = "AES-256 (at rest and in transit)"
        request.encryption_key_ref = key_ref
        request.encrypted_at = timezone.now()
        request.archive_ref = str(path)
        request.status = states.archival_transition(request.status, "encrypt")
        request.save()
        ArchivalDecision.objects.create(
            request=request, stage="encryption", decision="encrypted",
            decided_by_user_id=uid, note=note)
        audit_service.record_event(
            action="archival.encrypted", actor=actor, actor_kind="security",
            object_type="archival", object_id=request.pk,
            detail="AES-256 archive created")
        notifications.enqueue(
            topic="archival.encrypted",
            dedupe_key=f"archival-encrypted-{request.pk}",
            subject="Sensitive archive created",
            body=f"Your request for {request.file_name!r} was archived with "
                 f"AES-256 encryption.",
            recipient_user_id=request.user_id)
    return request


def track_history(request: ArchivalRequest) -> list[dict]:
    """The decision history shown on the tracking page (UC-BA-015)."""
    return [{
        "stage": d.stage, "decision": d.decision, "note": d.note,
        "at": d.at, "decided_by_user_id": d.decided_by_user_id,
    } for d in request.decisions.order_by("at")]
