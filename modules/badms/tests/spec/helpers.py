"""Shared builders for the spec test suites (tests/spec/).

These tests implement frozen designs (docs/09-badms/spec-tests/*_DESIGN.json).
Each test carries its design's test_id and source_id in its docstring. The
expected results come from the designs; the status code for an unnamed
refusal follows docs/01-architecture/api-conventions.md.
"""
import datetime as dt

import pytest

from modules.badms.models import (
    NotificationOutbox,
)
from modules.badms.services import (
    archival as archival_service,
)

from ..helpers import (  # noqa: F401  (re-exported for the spec suites)
    DEPT,
    HOD_PERMS,
    ITSEC_PERMS,
    OTHER_DEPT,
    SUPERADMIN_PERMS,
    SYSADMIN_PERMS,
    USER_PERMS,
    actor,
    give_department,
    make_archival,
)

pytestmark = pytest.mark.django_db

T0 = dt.datetime(2026, 11, 22, 2, 0, tzinfo=dt.UTC)
DAY = dt.date(2026, 8, 1)


def student(uid=9001):
    return actor(uid=uid, perms=USER_PERMS)


def sysadmin(uid=70):
    return actor(uid=uid, perms=SYSADMIN_PERMS, kind="staff",
                 roles=("sysadmin",))


def super_admin(uid=69):
    return actor(uid=uid, perms=SUPERADMIN_PERMS, kind="staff",
                 roles=("super_admin",))


def itsec(uid=72):
    return actor(uid=uid, perms=ITSEC_PERMS, kind="staff",
                 roles=("it_security",))


def hod(dept=DEPT, uid=71):
    give_department(uid, dept)
    return actor(uid=uid, perms=HOD_PERMS, kind="staff", roles=("hod",))


def submit(owner, **over):
    """A valid archival submission."""
    fields = {"file_name": "spec.pdf", "file_date": DAY,
              "owners": "Spec Owner", "file_type": "pdf", "reason": "spec",
              "attachment": "att://spec", "attachment_size_bytes": 10}
    fields.update(over)
    return archival_service.submit_request(actor=owner, **fields)


def hod_approved(owner, hod_principal, **over):
    request = submit(owner, **over)
    return archival_service.decide_request(actor=hod_principal,
                                           request_id=request.pk,
                                           decision="approve")


def classified_sensitive(owner, hod_principal, sysadmin_principal):
    request = hod_approved(owner, hod_principal)
    return archival_service.classify_request(
        actor=sysadmin_principal, request_id=request.pk,
        classification="sensitive")


def queued_for(user_id):
    """The requester's queued notification topics, in order."""
    return list(NotificationOutbox.objects.filter(recipient_user_id=user_id)
                .order_by("pk").values_list("topic", flat=True))
