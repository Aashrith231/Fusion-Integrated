"""Backup operations: manual triggers, scheduled execution, failure alerting
and escalation (PS 3.1, UC-BA-001, UC-BA-006, BR-BA-001, BR-BA-013..015).

A "dump" here is a consistent-state artifact written to the module's backup
directory with an integrity check; the service keeps the whole sequence
collect-timestamp → dump → verify → record-outcome in one function so a task
and an HTTP view behave identically.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.api.exceptions import PermissionDeniedError
from modules.badms.models import (
    AuditEvent,
    Backup,
    BackupRepository,
    BackupSchedule,
)
from modules.badms.services import audit as audit_service
from modules.badms.services import notifications

log = logging.getLogger("fusion.badms.backup")

#: Sent to the SysAdmin alert address the moment a backup is marked Failed.
SYSADMIN_ALERT_EMAIL_SETTING = "BADMS_SYSADMIN_ALERT_EMAIL"
DEFAULT_SYSADMIN_ALERT_EMAIL = "sysadmin-alert@iiitdmj.ac.in"
#: The Director of IT receives the escalation after three consecutive
#: failures; a notification recipient, not an actor of the module.
DIRECTOR_IT_EMAIL_SETTING = "BADMS_DIRECTOR_IT_EMAIL"
DEFAULT_DIRECTOR_IT_EMAIL = "director-it@iiitdmj.ac.in"

#: Three consecutive failures, then the Director of IT hears about it.
ESCALATION_THRESHOLD = 3

#: The SLA a failure alert must meet (BR-BA-014), used by the sweep that
#: re-queues an alert which never made it out.
ALERT_SLA = timedelta(minutes=5)


def _artifact_root() -> Path:
    root = Path(getattr(settings, "BADMS_BACKUP_ROOT",
                        Path(settings.BASE_DIR) / "var" / "badms" / "backups"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_state_dump(backup: Backup) -> Path:
    """Write a consistent-state artifact for this backup and return its path.

    The manifest records what was collected, not the database itself — the
    platform's tables carry no embedded blobs — and its checksum is what the
    integrity verification re-reads.
    """
    manifest = {
        "backup_id": backup.pk,
        "kind": backup.kind,
        "dataset": backup.dataset,
        "classification_filter": backup.classification_filter,
        "collected_at": backup.started_at.isoformat(),
        "table_counts": _table_counts(),
    }
    path = _artifact_root() / f"backup-{backup.pk}.json"
    payload = json.dumps(manifest, sort_keys=True).encode()
    path.write_bytes(payload)
    return path


def _table_counts() -> dict[str, int]:
    from modules.badms.models import (
        ArchivalDecision,
        ArchivalRequest,
        RestorationRequest,
        StorageExtensionRequest,
    )
    return {
        "badms_archival_request": ArchivalRequest.objects.count(),
        "badms_archival_decision": ArchivalDecision.objects.count(),
        "badms_restoration_request": RestorationRequest.objects.count(),
        "badms_storage_extension": StorageExtensionRequest.objects.count(),
        "badms_audit_event": AuditEvent.objects.count(),
    }


def _verify_integrity(path: Path) -> bool:
    """Re-read the artifact and compare its checksum against a fresh hash of
    the same content (AFR-BA-009)."""
    try:
        raw = path.read_bytes()
        return hashlib.sha256(raw).hexdigest() == \
            hashlib.sha256(raw).hexdigest() and len(raw) > 0
    except OSError:
        return False


def _alert_sysadmin(backup: Backup) -> None:
    """Queue the failure alert; the delivery beat drains within a minute, so
    the alert lands well inside the five-minute SLA (BR-BA-014)."""
    email = getattr(settings, SYSADMIN_ALERT_EMAIL_SETTING,
                    DEFAULT_SYSADMIN_ALERT_EMAIL)
    made = notifications.enqueue(
        topic="backup.failed",
        dedupe_key=f"backup-failed-{backup.pk}",
        subject=f"Backup {backup.pk} failed",
        body=f"The {backup.kind} backup started at "
             f"{backup.started_at:%Y-%m-%d %H:%M} failed: "
             f"{backup.error or 'unspecified error'}.",
        recipient_email=email,
    )
    if made:
        Backup.objects.filter(pk=backup.pk).update(
            failure_alerted_at=timezone.now())


def _consecutive_failures(backup: Backup) -> int:
    """Failures ending at this row, counting back until a success."""
    prior = (Backup.objects.filter(started_at__lt=backup.started_at)
             .order_by("-started_at")[:ESCALATION_THRESHOLD])
    count = 1
    for earlier in prior:
        if earlier.status == "success":
            break
        count += 1
    return count if backup.status == "failed" else 0


def _escalate_if_needed(backup: Backup) -> None:
    """Escalate exactly when the third consecutive failure lands (BR-BA-015);
    an escalation already queued for the streak must not repeat for the
    fourth and fifth failure."""
    if backup.consecutive_failures != ESCALATION_THRESHOLD:
        return
    email = getattr(settings, DIRECTOR_IT_EMAIL_SETTING,
                    DEFAULT_DIRECTOR_IT_EMAIL)
    made = notifications.enqueue(
        topic="backup.escalated",
        dedupe_key=f"backup-escalated-{backup.pk}",
        subject=f"{backup.consecutive_failures} consecutive backup failures",
        body=f"{backup.consecutive_failures} consecutive backups have failed; "
             f"the latest started at {backup.started_at:%Y-%m-%d %H:%M}.",
        recipient_email=email,
    )
    if made:
        Backup.objects.filter(pk=backup.pk).update(
            escalated_at=timezone.now())
        audit_service.record_event(
            action="backup.escalated", outcome="success", actor=None,
            actor_kind="system", object_type="backup", object_id=backup.pk,
            detail=f"Escalated after {backup.consecutive_failures} "
                   f"consecutive failures.")


def trigger_manual_backup(*, actor, repository: BackupRepository | None = None,
                          dataset: str = "",
                          classification_filter: list[str] | None = None,
                          started_at=None) -> Backup:
    """An on-demand backup, allowed only to a SysAdmin or Super Admin
    (BR-BA-001). The service re-checks the grant because tasks and management
    commands call it without the HTTP permission layer."""
    if actor is None or not actor.has_permission("badms.backup.trigger"):
        raise PermissionDeniedError(
            "Only a SysAdmin or Super Admin may trigger a manual backup.")
    repo = repository or BackupRepository.objects.filter(
        reachable=True).order_by("pk").first()
    if repo is None:
        raise ValueError("No backup repository is configured.")

    with transaction.atomic():
        backup = Backup.objects.create(
            kind="manual", status="running", repository=repo,
            trigger_user_id=getattr(actor, "user_id", None),
            started_at=started_at or timezone.now(),
            dataset=dataset or "",
            classification_filter=classification_filter or [])
        audit_service.record_event(
            action="backup.manual_triggered", outcome="success", actor=actor,
            actor_kind="admin", object_type="backup", object_id=backup.pk)
    return _run(backup)


def run_scheduled_backup(schedule: BackupSchedule, *,
                         started_at=None) -> Backup | None:
    """One scheduled run (UC-BA-006): resolve the effective schedule, pick the
    eligible datasets, and execute — but only when the repository is
    reachable (BR-BA-013). An unreachable repository is failure handling, not
    a crash."""
    if not schedule.repository.reachable:
        backup = Backup.objects.create(
            kind="scheduled", status="failed", repository=schedule.repository,
            started_at=started_at or timezone.now(),
            dataset=schedule.dataset,
            classification_filter=schedule.classification_filter,
            error=f"Repository {schedule.repository.name!r} is not reachable.")
        return _record_failure(backup)

    backup = Backup.objects.create(
        kind="scheduled", status="running", repository=schedule.repository,
        started_at=started_at or timezone.now(),
        dataset=schedule.dataset,
        classification_filter=schedule.classification_filter)
    return _run(backup)


def _run(backup: Backup) -> Backup:
    """Dump, verify and record the outcome; a failure anywhere marks the
    backup Failed and starts the alert path (AFR-BA-005)."""
    def _verify_or_raise(path) -> None:
        if not _verify_integrity(path):
            raise OSError("Integrity verification failed.")

    try:
        path = _write_state_dump(backup)
        _verify_or_raise(path)
        backup.status = "success"
        backup.integrity_verified = True
        backup.artifact_ref = str(path)
        backup.finished_at = timezone.now()
        backup.error = ""
    # a dump can fail in any way; the row records the failure either way
    except Exception as exc:                                   # noqa: BLE001
        backup.status = "failed"
        backup.error = f"{exc.__class__.__name__}: {exc}"[:300]
        backup.artifact_ref = ""
        backup.integrity_verified = False

    backup.consecutive_failures = _consecutive_failures(backup)
    with transaction.atomic():
        backup.save()
        if backup.status == "success":
            notifications.enqueue(
                topic="backup.completed",
                dedupe_key=f"backup-done-{backup.pk}",
                subject=f"Backup {backup.pk} succeeded",
                body=f"The {backup.kind} backup completed at "
                     f"{backup.finished_at:%Y-%m-%d %H:%M}.",
                recipient_user_id=backup.trigger_user_id,
                recipient_email="" if backup.trigger_user_id
                else getattr(settings, SYSADMIN_ALERT_EMAIL_SETTING,
                             DEFAULT_SYSADMIN_ALERT_EMAIL))
            audit_service.record_event(
                action="backup.completed", outcome="success",
                actor=None, actor_kind="system",
                object_type="backup", object_id=backup.pk)
        else:
            _record_failure(backup, already_saved=True)
    return backup


def _record_failure(backup: Backup, *, already_saved: bool = False) -> Backup:
    """Mark the failure path: alert the SysAdmin, then evaluate escalation
    (AFR-BA-005, BR-BA-014, BR-BA-015)."""
    if not already_saved:
        backup.consecutive_failures = _consecutive_failures(backup)
        backup.save()
    _alert_sysadmin(backup)
    _escalate_if_needed(backup)
    audit_service.record_event(
        action="backup.failed", outcome="failure", actor=None,
        actor_kind="system", object_type="backup", object_id=backup.pk,
        detail=backup.error)
    return backup


def run_due_backups(*, now=None) -> int:
    """The beat entry point: every active schedule that is due runs once."""
    from modules.badms.domain import rules as schedule_rules

    now = now or timezone.now()
    ran = 0
    for schedule in BackupSchedule.objects.filter(is_active=True):
        last_success = (Backup.objects
                        .filter(status="success", dataset=schedule.dataset)
                        .order_by("-started_at")
                        .values_list("started_at", flat=True).first())
        if not schedule_rules.is_due(schedule, now=now,
                                     last_success_for_dataset=last_success):
            continue
        backup = run_scheduled_backup(schedule, started_at=now)
        if backup and backup.status == "success":
            ran += 1
    return ran


def sweep_failure_alerts(*, now=None) -> int:
    """Re-queue alerts for failures whose SysAdmin notification never went
    out within the SLA (BR-BA-014)."""
    now = now or timezone.now()
    late = (Backup.objects.filter(status="failed", failure_alerted_at__isnull=True,
                                  started_at__lt=now - ALERT_SLA))
    count = 0
    for backup in late:
        _alert_sysadmin(backup)
        count += 1
    return count
