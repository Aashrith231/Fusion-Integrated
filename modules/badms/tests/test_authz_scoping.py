"""Who-is-asking decisions (BR-BA-010, BR-BA-020) and scope narrowing.

These cover the branches the scoping and authz selectors take per role,
including the degraded paths: no user id, no department on record and a
broken directory projection.
"""
import datetime as dt

import pytest

from core.api.exceptions import PermissionDeniedError
from modules.badms.models import (
    ArchivalRequest,
    RbacAssignment,
    RestorationRequest,
    SpecialArchivalRecord,
    StorageExtensionRequest,
)
from modules.badms.selectors import authz, scoping
from modules.badms.services import archival

from .helpers import DEPT, OTHER_DEPT, actor, give_department, make_archival

pytestmark = pytest.mark.django_db


class BarePrincipal:
    """A principal with no permissions object at all (worst case)."""

    user_id = None

    def has_permission(self, code):
        return False


# --- authz.py ----------------------------------------------------------------

def test_department_of_reads_the_projection():
    give_department(3101, DEPT)
    assert authz.department_of(actor(uid=3101, perms=())) == DEPT


def test_department_of_survives_a_missing_user_and_a_broken_projection():
    assert authz.department_of(actor(uid=4711, perms=())) == ""
    assert authz.department_of(BarePrincipal()) == ""
    broken = actor(uid=3102, perms=())
    real = authz.directory.get_users
    authz.directory.get_users = lambda ids: (_ for _ in ()).throw(
        RuntimeError("down"))
    try:
        assert authz.department_of(broken) == ""
        assert authz.departments_for([1, 2]) == {1: "", 2: ""}
    finally:
        authz.directory.get_users = real


def test_departments_for_maps_only_known_users():
    give_department(3103, DEPT)
    assert authz.departments_for([3103, 4711]) == {3103: DEPT}
    assert authz.departments_for([]) == {}


def test_has_permission_falls_back_to_the_badms_rbac_assignment():
    uid = 3201
    p = actor(uid=uid, perms=())
    assert not authz.has_permission(p, "badms.backup.view")
    RbacAssignment.objects.create(
        user_id=uid, permission_code="badms.backup.view", is_active=True,
        granted_by_user_id=1)
    assert authz.has_permission(p, "badms.backup.view")
    # an inactive assignment grants nothing
    RbacAssignment.objects.filter(user_id=uid).update(is_active=False)
    assert not authz.has_permission(p, "badms.backup.view")
    assert not authz.has_permission(None, "badms.backup.view")


def test_in_department_never_matches_an_empty_department():
    give_department(3301, DEPT)
    assert authz.in_department(actor(uid=3301, perms=()), DEPT)
    assert not authz.in_department(actor(uid=3301, perms=()), "")
    assert not authz.in_department(actor(uid=4711, perms=()), DEPT)


def test_is_staff_by_permission_and_by_rbac():
    assert authz.is_staff(actor(uid=1, perms=("badms.backup.trigger",)))
    RbacAssignment.objects.create(
        user_id=3401, permission_code="badms.audit.view", is_active=True,
        granted_by_user_id=1)
    assert authz.is_staff(actor(uid=3401, perms=()))
    assert not authz.is_staff(actor(uid=2, perms=("badms.backup.view",)))
    assert not authz.is_staff(None)


# --- scoping.py ----------------------------------------------------------------

def test_special_archival_is_none_without_the_permission():
    give_department(3501, DEPT)
    SpecialArchivalRecord.objects.create(
        performed_by_user_id=3501, data_reference="legacy-set",
        reason="offline", outcome="completed")
    assert (scoping.special_archival_for(
        actor(uid=3501, perms=("badms.special_archival.perform",))
    ).count() == 1)
    assert scoping.special_archival_for(
        actor(uid=3501, perms=("badms.backup.view",))).count() == 0


def test_restoration_scoping_fallbacks():
    request = make_archival()
    rest = RestorationRequest.objects.create(user_id=3601, archival=request)
    assert scoping.restorations_for(
        actor(uid=3601, perms=("badms.restoration.request",))
    ).filter(pk=rest.pk).exists()
    # the SysAdmin sees the whole queue
    assert scoping.restorations_for(
        actor(uid=1, perms=("badms.restoration.approve",))
    ).filter(pk=rest.pk).exists()
    # an actor with no user id sees nothing
    assert not scoping.restorations_for(
        actor(uid=None, perms=())).filter(pk=rest.pk).exists()


def test_storage_scoping_fallbacks():
    give_department(3701, DEPT)
    StorageExtensionRequest.objects.create(
        user_id=3702, department=DEPT, usage_at_request=1,
        quota_at_request=1, requested_bytes=1, justification="j",
        attachment="a://x")
    StorageExtensionRequest.objects.create(
        user_id=3702, department=OTHER_DEPT, usage_at_request=1,
        quota_at_request=1, requested_bytes=1, justification="j",
        attachment="a://x")
    hod = actor(uid=3701, perms=("badms.storage.decide",))
    assert scoping.storage_extensions_for(hod).count() == 1
    # a HoD with no department on record sees only their own rows
    give_department(3701, "")
    assert scoping.storage_extensions_for(hod).count() == 0
    # a plain user sees only their own
    assert scoping.storage_extensions_for(
        actor(uid=3702, perms=("badms.storage.request",))).count() == 2


def test_archival_scoping_classify_and_encrypt_windows():
    give_department(3801, DEPT)
    request = make_archival(uid=3802, status="hod_approved")
    # the SysAdmin classification window
    seen = scoping.archival_requests_for(
        actor(uid=1, perms=("badms.archival.classify",)))
    assert seen.filter(pk=request.pk).exists()
    # a submitted request is outside both windows
    submitted = ArchivalRequest.objects.create(
        user_id=3802, file_name="f.pdf", file_date=dt.date(2026, 8, 1),
        owners="o", file_type="pdf", reason="r", attachment="a://x",
        department=DEPT, classification="routine", status="submitted")
    assert not seen.filter(pk=submitted.pk).exists()
    # IT Security sees only the encryption window
    sec = scoping.archival_requests_for(
        actor(uid=3, perms=("badms.encryption.manage",)))
    assert not sec.filter(pk=submitted.pk).exists()


def test_archival_hod_sees_only_their_department():
    give_department(3901, DEPT)
    own = make_archival(uid=3902, department=DEPT, status="hod_approved")
    foreign = make_archival(uid=3903, department=OTHER_DEPT,
                            status="hod_approved")
    hod = actor(uid=3901, perms=("badms.archival.decide",))
    seen = scoping.archival_requests_for(hod)
    assert seen.filter(pk=own.pk).exists()
    assert not seen.filter(pk=foreign.pk).exists()
    # the service agrees with the scope: the foreign row is refused
    with pytest.raises(PermissionDeniedError):
        archival.decide_request(actor=hod, request_id=foreign.pk,
                                decision="approve")
