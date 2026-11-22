"""Role scope, decided in one place (BR-BA-020).

Every list and detail view starts from a queryset built here. Ownership and
department scope are enforced by narrowing the queryset, never by fetching a
row and checking it — so a row you may not see is a 404, not a 403 that
confirms it exists.

    BR-BA-020  protected information is shown only within an authorised scope
    BR-BA-010  a HoD sees only their department's requests and reports
    UC-BA-015  a request not owned by the user is never disclosed
"""
from __future__ import annotations

from django.db.models import Q, QuerySet

from modules.badms.models import (
    ArchivalRequest,
    Backup,
    RestorationRequest,
    SpecialArchivalRecord,
    StorageExtensionRequest,
)
from modules.badms.selectors import authz

P_BACKUP_TRIGGER = "badms.backup.trigger"
P_DECIDE = "badms.archival.decide"
P_CLASSIFY = "badms.archival.classify"
P_ENCRYPT = "badms.encryption.manage"
P_SPECIAL = "badms.special_archival.perform"
P_RESTORATION_DECIDE = "badms.restoration.approve"
P_RESTORATION_EXECUTE = "badms.restoration.execute"
P_STORAGE_DECIDE = "badms.storage.decide"
P_AUDIT_VIEW = "badms.audit.view"
P_SECURITY_AUDIT = "badms.security.audit"
P_REPORT = "badms.report.department"


def _own_id(actor) -> int | None:
    return getattr(actor, "user_id", None)


def backups_for(actor) -> QuerySet[Backup]:
    """Backup history/status (UC-BA-014). Anyone in the module may see the
    status and history; the artifact reference is an operational detail shown
    only to those who run backups."""
    qs = Backup.objects.all()
    if not authz.has_permission(actor, P_BACKUP_TRIGGER):
        qs = qs.defer("artifact_ref")
    return qs


def archival_requests_for(actor) -> QuerySet[ArchivalRequest]:
    """Who sees a request at all:

    * the requester, always (UC-BA-015);
    * the HoD of the request's department (BR-BA-002/010);
    * the SysAdmin, once it is routed for classification;
    * IT Security, once it is routed for encryption.
    """
    qs = ArchivalRequest.objects.all()
    own = _own_id(actor)
    visible = Q(user_id=own) if own is not None else Q(pk=None)

    if authz.has_permission(actor, P_DECIDE):
        department = authz.department_of(actor)
        if department:
            visible |= Q(department=department)

    if authz.has_permission(actor, P_CLASSIFY):
        visible |= Q(status__in=("hod_approved", "routed_to_security",
                                 "classified", "encrypted",
                                 "encryption_failed"))
    if authz.has_permission(actor, P_ENCRYPT):
        visible |= Q(status__in=("routed_to_security", "encrypted",
                                 "encryption_failed"))
    return qs.filter(visible).distinct()


def special_archival_for(actor) -> QuerySet[SpecialArchivalRecord]:
    """The Super Admin's own operation records (BR-BA-018)."""
    if not authz.has_permission(actor, P_SPECIAL):
        return SpecialArchivalRecord.objects.none()
    return SpecialArchivalRecord.objects.all()


def restorations_for(actor) -> QuerySet[RestorationRequest]:
    """The requester sees their own; the SysAdmin sees the approval queue and
    the execution list (UC-BA-017, UC-BA-018)."""
    qs = RestorationRequest.objects.select_related("archival")
    own = _own_id(actor)
    visible = Q(user_id=own) if own is not None else Q(pk=None)
    if (authz.has_permission(actor, P_RESTORATION_DECIDE)
            or authz.has_permission(actor, P_RESTORATION_EXECUTE)):
        visible |= Q(pk__isnull=False)
    return qs.filter(visible).distinct()


def storage_extensions_for(actor) -> QuerySet[StorageExtensionRequest]:
    """The requester sees their own; the respective HoD sees their
    department's queue (BR-BA-009, BR-BA-010)."""
    qs = StorageExtensionRequest.objects.all()
    own = _own_id(actor)
    visible = Q(user_id=own) if own is not None else Q(pk=None)
    if authz.has_permission(actor, P_STORAGE_DECIDE):
        department = authz.department_of(actor)
        if department:
            visible |= Q(department=department)
    return qs.filter(visible).distinct()
