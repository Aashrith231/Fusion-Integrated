"""Shared BADMS fixtures and builders.

The suite runs against the stubbed IAM, so a "role" here is the permission
set the stub session carries, and a department is a local UserRef row — the
same projection the HoD scoping reads in production.
"""
import datetime as dt

from django.apps import apps
from django.utils import timezone
from rest_framework.test import APIClient

from conftest import make_session
from fusion_auth.principal import Principal
from modules.badms.models import ArchivalRequest

USER_PERMS = (
    "badms.backup.view",
    "badms.archival.submit",
    "badms.restoration.request",
    "badms.storage.request",
)
HOD_PERMS = (*USER_PERMS, "badms.archival.decide", "badms.storage.decide",
             "badms.report.department")
SYSADMIN_PERMS = (
    "badms.backup.view", "badms.backup.trigger", "badms.schedule.manage",
    "badms.archival.classify", "badms.restoration.approve",
    "badms.restoration.execute", "badms.audit.view",
)
ITSEC_PERMS = (
    "badms.backup.view", "badms.encryption.manage", "badms.security.audit",
    "badms.rbac.manage", "badms.security_policy.manage",
)
SUPERADMIN_PERMS = (*SYSADMIN_PERMS, "badms.schedule.manage_global",
                    "badms.special_archival.perform")

DEPT = "CSE"
OTHER_DEPT = "ECE"


def actor(*, uid, perms, kind="student", roles=("student",)) -> Principal:
    """A principal without any IAM wiring — services only read user_id and
    has_permission off it."""
    return Principal.from_session(make_session(
        user_id=uid, kind=kind, roles=roles, modules=("badms",),
        permissions=perms))


def api_client(stub_iam, *, uid, perms, kind="student") -> APIClient:
    stub_iam(make_session(user_id=uid, kind=kind, modules=("badms",),
                          permissions=perms))
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Token abc")
    return client


def give_department(user_id: int, department: str) -> None:
    """A directory row, because department scope reads the projection."""
    user_ref = apps.get_model("directory", "UserRef")
    user_ref.objects.update_or_create(
        user_id=user_id,
        defaults={"username": f"u{user_id}", "display_name": f"User {user_id}",
                  "kind": "staff", "department": department})


def make_archival(*, uid=2001, department=DEPT, classification="routine",
                  status="classified", encrypted=False) -> ArchivalRequest:
    """A request at a chosen state, for restoration and tracking tests."""
    request = ArchivalRequest.objects.create(
        user_id=uid, file_name="records.pdf", file_date=dt.date(2026, 8, 1),
        owners="Owner", file_type="pdf", reason="r", attachment="att://x",
        department=department, classification=classification,
        initial_classification=classification or "routine", status=status)
    if encrypted:
        request.archive_ref = "att://archive"
        request.save(update_fields=["archive_ref"])
    return request


def submit_archival(actor_principal, *, uid=None, department=DEPT,
                    classification="", size=0) -> ArchivalRequest:
    """Submit through the service, with the department pre-resolved."""
    from modules.badms.services import archival

    give_department(uid or actor_principal.user_id, department)
    return archival.submit_request(
        actor=actor_principal, file_name="thesis-final.pdf",
        file_date=dt.date(2026, 8, 1), owners="Dr. Asha Verma",
        file_type="pdf", reason="Long-term record",
        attachment="drive://thesis-final.pdf", attachment_size_bytes=size,
        initial_classification=classification)


def now_minus(minutes: int):
    return timezone.now() - dt.timedelta(minutes=minutes)
