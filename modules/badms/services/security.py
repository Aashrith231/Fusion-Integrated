"""Security administration: RBAC assignments and security policies
(UC-BA-019, UC-BA-020, BR-BA-021).

Module entry stays with the IAM; what IT Security manages here is the
BADMS-scoped slice — who may act on BADMS requests, and the institute
security policies that govern encryption, access and related controls. Both
write an audit record (UC-BA-019 M4, UC-BA-020 M4), and a change that fails
validation leaves the current configuration in force.
"""
from __future__ import annotations

from django.db import transaction

from core.api.exceptions import ConflictError, DomainError, PermissionDeniedError
from modules.badms.models import RbacAssignment, SecurityPolicy
from modules.badms.selectors import authz
from modules.badms.services import audit as audit_service

#: Permission codes an RBAC assignment may carry: only BADMS's own.
ASSIGNABLE_PERMISSIONS = frozenset({
    "badms.backup.trigger",
    "badms.schedule.manage",
    "badms.schedule.manage_global",
    "badms.archival.submit",
    "badms.archival.decide",
    "badms.archival.classify",
    "badms.encryption.manage",
    "badms.special_archival.perform",
    "badms.restoration.request",
    "badms.restoration.approve",
    "badms.restoration.execute",
    "badms.storage.request",
    "badms.storage.decide",
    "badms.audit.view",
    "badms.security.audit",
    "badms.report.department",
})


def _guard(actor, code: str) -> None:
    if actor is None or not authz.has_permission(actor, code):
        raise PermissionDeniedError(
            "Only authorised IT Security members may administer security.")


# -- RBAC assignments (UC-BA-019) ---------------------------------------------------
def grant_permission(*, actor, user_id: int, permission_code: str,
                     note: str = "") -> RbacAssignment:
    _guard(actor, "badms.rbac.manage")
    if permission_code not in ASSIGNABLE_PERMISSIONS:
        raise DomainError(
            f"{permission_code!r} is not a BADMS permission.",
            code="invalid_permission")
    if not user_id:
        raise DomainError("A user is required.", code="invalid_permission")
    with transaction.atomic():
        assignment, created = RbacAssignment.objects.get_or_create(
            user_id=user_id, permission_code=permission_code,
            defaults={"granted_by_user_id": getattr(actor, "user_id", 0) or 0,
                      "is_active": True})
        if not created and not assignment.is_active:
            assignment.is_active = True
            assignment.granted_by_user_id = getattr(actor, "user_id", 0) or 0
            assignment.save(update_fields=["is_active", "granted_by_user_id",
                                           "updated_at"])
        audit_service.record_event(
            action="rbac.granted", actor=actor, actor_kind="security",
            object_type="rbac_assignment", object_id=assignment.pk,
            detail=f"user={user_id} permission={permission_code} {note}")
    return assignment


def revoke_permission(*, actor, user_id: int, permission_code: str) -> None:
    _guard(actor, "badms.rbac.manage")
    assignment = RbacAssignment.objects.filter(
        user_id=user_id, permission_code=permission_code).first()
    if assignment is None or not assignment.is_active:
        raise ConflictError("No active assignment to revoke.",
                            code="invalid_permission")
    with transaction.atomic():
        assignment.is_active = False
        assignment.save(update_fields=["is_active", "updated_at"])
        audit_service.record_event(
            action="rbac.revoked", actor=actor, actor_kind="security",
            object_type="rbac_assignment", object_id=assignment.pk,
            detail=f"user={user_id} permission={permission_code}")


def assignments_for_user(user_id: int):
    return RbacAssignment.objects.filter(user_id=user_id, is_active=True)


# -- Security policies (UC-BA-020) ---------------------------------------------------
def define_policy(*, actor, name: str, statement: str,
                  applies_to: str = "") -> SecurityPolicy:
    _guard(actor, "badms.security_policy.manage")
    name = (name or "").strip()
    statement = (statement or "").strip()
    if not name or not statement:
        raise DomainError("A policy needs a name and a statement.",
                              code="invalid_policy")
    if SecurityPolicy.objects.filter(name=name).exists():
        raise ConflictError("A policy with this name already exists.",
                            code="invalid_policy")
    with transaction.atomic():
        policy = SecurityPolicy.objects.create(
            name=name, statement=statement, applies_to=applies_to or "",
            defined_by_user_id=getattr(actor, "user_id", 0) or 0)
        audit_service.record_event(
            action="security_policy.defined", actor=actor,
            actor_kind="security", object_type="security_policy",
            object_id=policy.pk)
    return policy


def update_policy(*, actor, policy_id: int, statement: str | None = None,
                  is_active: bool | None = None) -> SecurityPolicy:
    _guard(actor, "badms.security_policy.manage")
    policy = SecurityPolicy.objects.filter(pk=policy_id).first()
    if policy is None:
        raise LookupError("No such security policy.")
    with transaction.atomic():
        if statement is not None:
            statement = statement.strip()
            if not statement:
                raise DomainError("A policy statement cannot be empty.",
                                      code="invalid_policy")
            policy.statement = statement
        if is_active is not None:
            policy.is_active = is_active
        policy.save(update_fields=["statement", "is_active", "updated_at"])
        audit_service.record_event(
            action="security_policy.updated", actor=actor,
            actor_kind="security", object_type="security_policy",
            object_id=policy.pk)
    return policy
