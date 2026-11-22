"""Audit recording and reading (PS 3.7, UC-BA-023).

`record_event` is the one door every service writes through: a timestamped
row with the actor (or event-source label for system events), the action and
the outcome. Recording never raises — an audit write failing must not fail
the business event it describes, but a failed write must not be reported as
stored either, so the outcome is returned to the caller for logging.
"""
from __future__ import annotations

import logging

from django.db import transaction

from modules.badms.models import AuditEvent

log = logging.getLogger("fusion.badms.audit")


def record_event(*, action: str, outcome: str = "success",
                 actor=None, actor_kind: str = "user",
                 actor_label: str = "", object_type: str = "",
                 object_id: str | int = "", detail: str = "") -> bool:
    """Store one audit event. True when it was stored, False when it was not
    (UC-BA-023 E1: never report a fabricated record as successfully stored)."""
    actor_user_id = getattr(actor, "user_id", None) if actor is not None else None

    try:
        with transaction.atomic():
            AuditEvent.objects.create(
                actor_user_id=actor_user_id, actor_kind=actor_kind,
                actor_label=actor_label or ("system" if actor is None else ""),
                action=action, outcome=outcome, object_type=object_type,
                object_id=str(object_id or ""), detail=detail[:300])
    except Exception as exc:                                   # noqa: BLE001
        log.error("badms.audit.write_failed action=%s err=%s", action, exc)
        return False
    return True


def recent_events(now=None):
    """The last audit rows, newest first, for the authorised viewers."""
    return AuditEvent.objects.all().order_by("-created_at")


def failed_writes_since(unreadable=None):
    """Failures this process noticed but could not store are logged, not
    stored — the log line above is the record a reviewer greps for."""
    return
