"""Reports and protected-information reads (PS 3.7, UC-BA-012..015, UC-BA-021,
BR-BA-020).

Every reader gets only the slice its role authorises: the SysAdmin the audit
trail and backup visibility, IT Security the security events, a HoD their own
department's operational picture. A HoD's department-scope check lives in
`authz.in_department`, so a report for a foreign department is refused here,
not just hidden.
"""
from __future__ import annotations

from django.db.models import Count, Q

from core.api.exceptions import PermissionDeniedError
from modules.badms.models import (
    ArchivalRequest,
    AuditEvent,
    Backup,
    RestorationRequest,
    StorageExtensionRequest,
)
from modules.badms.selectors import authz


def department_report(*, actor, department: str) -> dict:
    """UC-BA-021: operational reports for the HoD's own department."""
    if actor is None or not authz.has_permission(
            actor, "badms.report.department"):
        raise PermissionDeniedError(
            "Only a department head may view departmental reports.")
    if not authz.in_department(actor, department):
        raise PermissionDeniedError(
            "You may only view reports for your own department.")

    archival = (ArchivalRequest.objects.filter(department=department)
                .values("status")
                .annotate(n=Count("pk")))
    extensions = (StorageExtensionRequest.objects.filter(department=department)
                  .values("status")
                  .annotate(n=Count("pk")))
    return {
        "department": department,
        "archival_by_status": {row["status"]: row["n"] for row in archival},
        "storage_extensions_by_status": {row["status"]: row["n"]
                                         for row in extensions},
        "archival_total": ArchivalRequest.objects.filter(
            department=department).count(),
        "storage_extension_total": StorageExtensionRequest.objects.filter(
            department=department).count(),
    }


def backup_operations_summary() -> dict:
    """AFR-BA-065: operational visibility into backup operations."""
    return {
        "total": Backup.objects.count(),
        "success": Backup.objects.filter(status="success").count(),
        "failed": Backup.objects.filter(status="failed").count(),
        "running": Backup.objects.filter(status="running").count(),
    }


def security_report() -> dict:
    """UC-BA-013: the security slice of the audit trail."""
    security = AuditEvent.objects.filter(actor_kind="security")
    denied = AuditEvent.objects.filter(outcome="denied")
    return {
        "security_events": security.count(),
        "denied_events": denied.count(),
        "recent_security_events": [
            {"action": e.action, "outcome": e.outcome, "at": e.created_at,
             "actor_user_id": e.actor_user_id, "detail": e.detail}
            for e in security.order_by("-created_at")[:20]],
    }


def unauthorised_access_candidates() -> dict:
    """Denied and failed actions, the trail IT Security audits for
    unauthorised access."""
    rows = AuditEvent.objects.filter(
        Q(outcome="denied") | Q(outcome="failure")).order_by("-created_at")[:50]
    return {"candidates": [
        {"action": r.action, "outcome": r.outcome, "at": r.created_at,
         "actor_user_id": r.actor_user_id, "actor_kind": r.actor_kind,
         "detail": r.detail} for r in rows]}


def restoration_summary() -> dict:
    return {
        "by_status": dict(RestorationRequest.objects.values("status")
                          .annotate(n=Count("pk"))
                          .values_list("status", "n")),
    }
