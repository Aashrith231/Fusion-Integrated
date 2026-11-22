"""Who is asking, and what are they allowed to see and touch.

BADMS role boundaries (PS 3.8, BR-BA-010, BR-BA-020, BR-BA-021):

  * a HoD acts only inside their department — the department comes from the
    IAM directory and must match the request's department on every read;
  * technical execution, classification, global policy and security
    administration each stay with the role the permission names;
  * a department match alone is never enough — the caller must hold the
    permission too.

Department scope is enforced by narrowing querysets (selectors/scoping), so a
row outside scope is absent, never a 403 confirming it exists.
"""
from __future__ import annotations

from modules.badms.models import RbacAssignment
from modules.directory import contracts as directory


def department_of(actor) -> str:
    """The actor's department, read from the IAM directory projection."""
    uid = getattr(actor, "user_id", None)
    if uid is None:
        return ""
    try:
        people = directory.get_users([uid])
    except Exception:  # noqa: BLE001 — a broken projection must not break a permission check
        return ""
    ref = people.get(uid)
    return (ref.department or "").strip() if ref else ""


def departments_for(user_ids) -> dict[int, str]:
    ids = {int(i) for i in user_ids if i is not None}
    if not ids:
        return {}
    try:
        people = directory.get_users(sorted(ids))
    except Exception:  # noqa: BLE001 — a broken projection must not break a permission check
        return dict.fromkeys(ids, "")
    return {i: (people[i].department or "").strip()
            for i in ids if i in people}


def has_permission(actor, code: str) -> bool:
    """The IAM grant, widened by the BADMS RBAC assignments IT Security made
    (UC-BA-019). An inactive assignment grants nothing."""
    if actor is None:
        return False
    check = getattr(actor, "has_permission", None)
    if check and check(code):
        return True
    uid = getattr(actor, "user_id", None)
    if uid is None:
        return False
    return RbacAssignment.objects.filter(
        user_id=uid, permission_code=code, is_active=True).exists()


def in_department(actor, department: str) -> bool:
    """True only when the actor holds a department-scoped role AND their own
    department equals the row's (BR-BA-010). An empty department never
    matches, so a person with no department on record can act on nothing."""
    if not department:
        return False
    return department_of(actor) == department


def is_staff(actor) -> bool:
    """Anyone carrying an administrative grant in this module."""
    if actor is None:
        return False
    return any(has_permission(actor, code) for code in STAFF_PERMISSIONS)


STAFF_PERMISSIONS = (
    "badms.backup.trigger",
    "badms.schedule.manage",
    "badms.schedule.manage_global",
    "badms.archival.classify",
    "badms.encryption.manage",
    "badms.special_archival.perform",
    "badms.restoration.approve",
    "badms.restoration.execute",
    "badms.audit.view",
    "badms.security.audit",
    "badms.rbac.manage",
    "badms.security_policy.manage",
)
