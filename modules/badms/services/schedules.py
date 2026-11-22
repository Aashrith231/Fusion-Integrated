"""Backup schedule management (PS 3.1 Schedule Configuration, UC-BA-009/011).

Local (dataset) schedules are SysAdmin work; the institution-wide global
schedule and default policy are Super Admin work (BR-BA-019). Every save is
validated first — an invalid or conflicting configuration is never applied
(BR-BA-012) — and every applied change is logged (AFR-BA-016).
"""
from __future__ import annotations

import datetime as dt
import logging

from django.db import transaction

from core.api.exceptions import ConflictError, DomainError, PermissionDeniedError
from modules.badms.domain import rules as schedule_rules
from modules.badms.models import (
    BackupRepository,
    BackupSchedule,
    ScheduleChangeLog,
)
from modules.badms.services import audit as audit_service

log = logging.getLogger("fusion.badms.schedules")


def _actor_guard(actor, code: str) -> None:
    if actor is None or not actor.has_permission(code):
        raise PermissionDeniedError(
            "You are not authorised to manage backup schedules.")


def _validated_fields(*, scope: str, dataset: str, frequency: str,
                      run_at, weekday: int | None,
                      classification_filter, repository_id: int,
                      exclude_pk: int | None = None) -> dict:
    """Run every rule and resolve the repository. Raises on any violation;
    the caller only ever sees a valid configuration."""
    try:
        schedule_rules.validate_parameters(
            frequency=frequency, run_at=run_at,
            classification_filter=classification_filter, weekday=weekday)
        dataset = schedule_rules.validate_dataset(dataset, scope=scope)
    except schedule_rules.ScheduleInvalid as exc:
        raise DomainError(str(exc), code="invalid_schedule") from exc

    repo = BackupRepository.objects.filter(pk=repository_id).first()
    if repo is None:
        raise DomainError("Unknown backup repository.",
                              code="invalid_schedule")

    existing = BackupSchedule.objects.filter(is_active=True)
    reason = schedule_rules.conflicts(
        existing, scope=scope, dataset=dataset, frequency=frequency,
        run_at=run_at, weekday=weekday, exclude_pk=exclude_pk)
    if reason:
        raise ConflictError(reason, code="schedule_conflict")

    return {
        "dataset": dataset, "frequency": frequency, "run_at": run_at,
        "weekday": weekday,
        "classification_filter": list(classification_filter or []),
        "repository": repo,
    }


def create_local_schedule(*, actor, dataset: str, frequency: str, run_at: dt.time,
                          weekday: int | None = None,
                          classification_filter: list[str] | None = None,
                          repository_id: int | None = None) -> BackupSchedule:
    """Create a dataset schedule (UC-BA-009 A1). Only an authorised SysAdmin
    (or Super Admin, who holds the grant) may call this."""
    _actor_guard(actor, "badms.schedule.manage")
    fields = _validated_fields(
        scope="local", dataset=dataset, frequency=frequency, run_at=run_at,
        weekday=weekday, classification_filter=classification_filter,
        repository_id=repository_id or 0)
    with transaction.atomic():
        schedule = BackupSchedule.objects.create(
            scope="local", is_active=True,
            created_by_user_id=getattr(actor, "user_id", 0) or 0, **fields)
        ScheduleChangeLog.objects.create(
            schedule=schedule, action="create",
            changed_by_user_id=getattr(actor, "user_id", 0) or 0,
            summary=f"Created {frequency} schedule at {run_at:%H:%M} for "
                    f"{dataset}.")
        audit_service.record_event(
            action="schedule.created", actor=actor, actor_kind="admin",
            object_type="backup_schedule", object_id=schedule.pk)
    return schedule


def modify_local_schedule(*, actor, schedule_id: int, frequency: str | None = None,
                          run_at: dt.time | None = None, weekday: int | None = None,
                          classification_filter: list[str] | None = None,
                          repository_id: int | None = None) -> BackupSchedule:
    """Modify an existing local schedule (UC-BA-009 A2). The schedule keeps
    its current values for anything not supplied, and an invalid change
    leaves the effective schedule untouched (E1)."""
    _actor_guard(actor, "badms.schedule.manage")
    schedule = BackupSchedule.objects.filter(
        pk=schedule_id, scope="local").first()
    if schedule is None:
        raise LookupError("No such local schedule.")

    fields = _validated_fields(
        scope="local", dataset=schedule.dataset,
        frequency=frequency or schedule.frequency,
        run_at=run_at or schedule.run_at,
        weekday=weekday if weekday is not None else schedule.weekday,
        classification_filter=(classification_filter
                               if classification_filter is not None
                               else schedule.classification_filter),
        repository_id=repository_id or schedule.repository_id,
        exclude_pk=schedule.pk)
    with transaction.atomic():
        for name, value in fields.items():
            setattr(schedule, name, value)
        schedule.updated_by_user_id = getattr(actor, "user_id", None)
        schedule.save()
        ScheduleChangeLog.objects.create(
            schedule=schedule, action="modify",
            changed_by_user_id=getattr(actor, "user_id", 0) or 0,
            summary=f"Modified to {schedule.frequency} at "
                    f"{schedule.run_at:%H:%M}.")
        audit_service.record_event(
            action="schedule.modified", actor=actor, actor_kind="admin",
            object_type="backup_schedule", object_id=schedule.pk)
    return schedule


def set_global_schedule(*, actor, frequency: str, run_at: dt.time,
                        weekday: int | None = None,
                        classification_filter: list[str] | None = None,
                        repository_id: int | None = None) -> BackupSchedule:
    """Define or update the institution-wide schedule and default policy
    (UC-BA-011). Super Admin only (BR-BA-019): the guard names the global
    grant, which no other designation holds."""
    _actor_guard(actor, "badms.schedule.manage_global")
    # The global schedule is replaced, not added — its current row does not
    # conflict with itself.
    existing_global = BackupSchedule.objects.filter(
        scope="global", is_active=True).first()
    fields = _validated_fields(
        scope="global", dataset="", frequency=frequency, run_at=run_at,
        weekday=weekday, classification_filter=classification_filter,
        repository_id=repository_id or 0,
        exclude_pk=existing_global.pk if existing_global else None)
    with transaction.atomic():
        schedule, created = BackupSchedule.objects.get_or_create(
            scope="global", dataset="", is_active=True,
            defaults={"created_by_user_id": getattr(actor, "user_id", 0) or 0,
                      **fields})
        if not created:
            for name, value in fields.items():
                setattr(schedule, name, value)
            schedule.updated_by_user_id = getattr(actor, "user_id", None)
            schedule.save()
        ScheduleChangeLog.objects.create(
            schedule=schedule, action="create" if created else "modify",
            changed_by_user_id=getattr(actor, "user_id", 0) or 0,
            summary=("Defined" if created else "Updated") +
                    f" the global {frequency} schedule at {run_at:%H:%M}.")
        audit_service.record_event(
            action="global_schedule.updated", actor=actor, actor_kind="admin",
            object_type="backup_schedule", object_id=schedule.pk)
    return schedule


def effective_schedule(dataset: str = "") -> BackupSchedule | None:
    """The schedule that governs a dataset right now (BR-BA-011): a valid
    local schedule wins; where none exists, the global schedule applies
    (AFR-BA-054, AFR-BA-055)."""
    local = BackupSchedule.objects.filter(
        scope="local", dataset=dataset, is_active=True).first()
    if local:
        return local
    return BackupSchedule.objects.filter(
        scope="global", is_active=True).first()


def change_log_for(schedule_id: int):
    return ScheduleChangeLog.objects.filter(schedule_id=schedule_id) \
        .order_by("-at")
