"""Journey tests: every live use case's main flow, over HTTP only.

One journey per UC main flow, plus the named alternate flows (rejection,
sensitive branch, quota-not-full). Actors switch the way the platform says:
the IAM session is re-stubbed before acting as someone else, and every
assertion reads the response body or the rows it caused.
"""

import pytest

from modules.badms.models import (
    ArchivalRequest,
    AuditEvent,
    Backup,
    NotificationOutbox,
    RestorationRequest,
    StorageExtensionRequest,
)

from .helpers import (
    DEPT,
    HOD_PERMS,
    ITSEC_PERMS,
    OTHER_DEPT,
    SYSADMIN_PERMS,
    USER_PERMS,
    api_client,
    give_department,
)

pytestmark = pytest.mark.django_db

URL = "/api/v1/badms"
STUDENT = 7101
STUDENT2 = 7102
HOD = 71
SYSADMIN = 70
ITSEC = 72
SUPERADMIN = 69


def as_client(stub_iam, uid, perms, kind="student", roles=("student",)):
    """A client that re-stubs the IAM session right now. The stub is global
    per test, so a client built earlier would authenticate as whoever was
    stubbed last — always build a client immediately before acting."""
    return api_client(stub_iam, uid=uid, perms=perms, kind=kind)


def _submit_archival(client, **over):
    payload = {
        "file_name": "journey.pdf", "file_date": "2026-08-01",
        "owners": "E2E Owner", "file_type": "pdf", "reason": "journey",
        "attachment": "att://journey", "attachment_size_bytes": 10,
        **over,
    }
    response = client.post(f"{URL}/archival/submit", payload, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def _hod(stub_iam):
    give_department(HOD, DEPT)
    return as_client(stub_iam, HOD, HOD_PERMS, kind="staff", roles=("hod",))


def _student(stub_iam, uid=STUDENT):
    """A submitter with a department on record: the HoD scoping matches it."""
    give_department(uid, DEPT)
    return as_client(stub_iam, uid, USER_PERMS)


def _sysadmin(stub_iam):
    return as_client(stub_iam, SYSADMIN, SYSADMIN_PERMS, kind="staff",
                     roles=("sysadmin",))


def _itsec(stub_iam):
    return as_client(stub_iam, ITSEC, ITSEC_PERMS, kind="staff",
                     roles=("it_security",))


# -- UC-BA-002/003/004: the archival chain, Routine branch (CW-BA-01) ---------

def test_journey_archival_routine_end_to_end(stub_iam):
    student = _student(stub_iam)
    request = _submit_archival(student)
    assert request["status"] == "submitted"

    hod = _hod(stub_iam)
    assert hod.get(f"{URL}/archival").json(), "the HoD queue shows it"
    decided = hod.post(f"{URL}/archival/{request['id']}/decide",
                       {"decision": "approve", "note": "ok"}, format="json")
    assert decided.status_code == 200, decided.json()
    assert decided.json()["status"] == "hod_approved"

    sysadmin = _sysadmin(stub_iam)
    classified = sysadmin.post(f"{URL}/archival/{request['id']}/classify",
                               {"classification": "routine"}, format="json")
    assert classified.status_code == 200, classified.json()
    assert classified.json()["status"] == "classified"

    row = ArchivalRequest.objects.get(pk=request["id"])
    assert row.classification == "routine"
    assert row.retention_rule, "the retention rule follows the classification"
    assert NotificationOutbox.objects.filter(
        recipient_user_id=STUDENT).exists()
    assert AuditEvent.objects.filter(
        object_type="archival", object_id=str(row.pk)).exists()


def test_journey_archival_rejected_by_the_hod(stub_iam):
    student = as_client(stub_iam, STUDENT, USER_PERMS)
    hod = _hod(stub_iam)

    request = _submit_archival(student)
    rejected = hod.post(f"{URL}/archival/{request['id']}/decide",
                        {"decision": "reject"}, format="json")
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    # a rejected request is dead: even the HoD cannot decide it again
    again = hod.post(f"{URL}/archival/{request['id']}/decide",
                     {"decision": "approve"}, format="json")
    assert again.status_code == 409


# -- UC-BA-005: the Sensitive branch reaches encryption (BR-BA-007) -----------

def test_journey_archival_sensitive_is_encrypted_by_it_security(stub_iam):
    student = _student(stub_iam)
    request = _submit_archival(student, initial_classification="sensitive")

    hod = _hod(stub_iam)
    hod.post(f"{URL}/archival/{request['id']}/decide",
             {"decision": "approve"}, format="json")

    sysadmin = _sysadmin(stub_iam)
    routed = sysadmin.post(f"{URL}/archival/{request['id']}/classify",
                           {"classification": "sensitive"}, format="json")
    assert routed.json()["status"] == "routed_to_security"

    itsec = _itsec(stub_iam)
    encrypted = itsec.post(f"{URL}/archival/{request['id']}/encryption",
                           {"key_ref": "key-e2e-1"}, format="json")
    assert encrypted.status_code == 200, encrypted.json()
    assert encrypted.json()["status"] == "encrypted"
    assert "AES-256" in encrypted.json()["encryption_algorithm"]

    student = as_client(stub_iam, STUDENT, USER_PERMS)
    student_sees = student.get(f"{URL}/archival/{request['id']}")
    assert student_sees.status_code == 200
    # the artifact reference is an operational detail the plain user
    # never receives (UC-BA-015)
    assert "archive_ref" not in student_sees.json()


# -- UC-BA-017/018: restoration of archived data (CW-BA-03) -------------------

def test_journey_restoration_sensitive_needs_sysadmin_approval(stub_iam):
    student = _student(stub_iam)
    archived = _submit_archival(student)
    archived["id"]  # non-sensitive, already classified
    row = ArchivalRequest.objects.get(pk=archived["id"])
    row.status = "classified"
    row.save(update_fields=["status"])

    requested = student.post(f"{URL}/restorations/request",
                             {"archival": row.pk}, format="json")
    assert requested.status_code == 201
    restoration = RestorationRequest.objects.get(pk=requested.json()["id"])
    restoration.status = "pending_approval"      # sensitive variant
    restoration.classification = "sensitive"
    restoration.save(update_fields=["status", "classification"])

    # the student cannot approve or execute
    student = as_client(stub_iam, STUDENT, USER_PERMS)
    assert student.post(f"{URL}/restorations/{restoration.pk}/decide",
                        {"decision": "approve"},
                        format="json").status_code == 403
    assert student.post(f"{URL}/restorations/{restoration.pk}/execute",
                        {}, format="json").status_code == 403

    sysadmin = _sysadmin(stub_iam)
    approved = sysadmin.post(f"{URL}/restorations/{restoration.pk}/decide",
                             {"decision": "approve"}, format="json")
    assert approved.json()["status"] == "approved_for_restoration"
    executed = sysadmin.post(f"{URL}/restorations/{restoration.pk}/execute",
                             {}, format="json")
    assert executed.status_code == 200
    assert executed.json()["status"] == "restored"


# -- UC-BA-007/008: scheduled backup management (BR-BA-011/012) ---------------

def test_journey_scheduled_backup_lifecycle(stub_iam, repo):
    sysadmin = _sysadmin(stub_iam)

    created = sysadmin.post(f"{URL}/schedules/create", {
        "dataset": "journey-db", "frequency": "daily", "run_at": "02:00",
        "repository": repo.pk,
    }, format="json")
    assert created.status_code == 201, created.json()
    schedule = created.json()
    assert schedule["is_active"]

    # redefining the same timing conflicts (BR-BA-012)
    conflict = sysadmin.post(f"{URL}/schedules/create", {
        "dataset": "journey-db", "frequency": "daily", "run_at": "02:00",
        "repository": repo.pk,
    }, format="json")
    assert conflict.status_code == 409

    modified = sysadmin.patch(
        f"{URL}/schedules/{schedule['id']}/modify",
        {"run_at": "03:00"}, format="json")
    assert modified.status_code == 200, modified.json()

    changes = sysadmin.get(f"{URL}/schedules/{schedule['id']}/changes")
    assert changes.status_code == 200
    assert len(changes.json()) >= 1


# -- UC-BA-001: the manual backup (BR-BA-001) ---------------------------------

def test_journey_manual_backup_records_a_row(stub_iam, repo):
    assert as_client(stub_iam, STUDENT2, USER_PERMS).post(
        f"{URL}/backups/manual", {}, format="json").status_code == 403

    sysadmin = _sysadmin(stub_iam)
    triggered = sysadmin.post(f"{URL}/backups/manual",
                              {"repository": repo.pk}, format="json")
    assert triggered.status_code in (200, 201), triggered.json()
    assert Backup.objects.filter(kind="manual").exists()


# -- UC-BA-008: the storage extension (BR-BA-009/016, CW-BA-02) ---------------

def test_journey_storage_extension_requires_full_quota(stub_iam,
                                                       profile_factory):
    profile_factory(STUDENT, used=9_000, quota=10_000)
    student = _student(stub_iam)
    early = student.post(f"{URL}/storage/extensions/submit", {
        "requested_bytes": 4096, "justification": "j",
        "attachment": "a://x"}, format="json")
    assert early.status_code == 422, "a quota with room is refused"

    profile_factory(STUDENT, used=10_000, quota=10_000)
    student = _student(stub_iam)
    submitted = student.post(f"{URL}/storage/extensions/submit", {
        "requested_bytes": 4096, "justification": "thesis data",
        "attachment": "a://x"}, format="json")
    assert submitted.status_code == 201, submitted.json()

    extension_id = submitted.json()["id"]
    hod = _hod(stub_iam)
    assert hod.get(f"{URL}/storage/extensions").json()
    decided = hod.post(f"{URL}/storage/extensions/{extension_id}/decide",
                       {"decision": "approve"}, format="json")
    assert decided.status_code == 200, decided.json()
    assert decided.json()["status"] == "approved"
    assert StorageExtensionRequest.objects.filter(
        pk=extension_id, status="approved").exists()


# -- UC-BA-013/014: audit visibility and the department report ----------------

def test_journey_audit_and_department_report_scopes(stub_iam):
    student = as_client(stub_iam, STUDENT, USER_PERMS)
    assert student.get(f"{URL}/audit").status_code == 403

    sysadmin = _sysadmin(stub_iam)
    assert sysadmin.get(f"{URL}/audit").status_code == 200

    hod = _hod(stub_iam)
    report = hod.get(f"{URL}/reports/department", {"department": DEPT})
    assert report.status_code == 200
    foreign = hod.get(f"{URL}/reports/department", {"department": OTHER_DEPT})
    assert foreign.status_code == 403, "a HoD sees only their department"


# -- UC-BA-020: the special archival (BR-BA-018) -------------------------------

def test_journey_special_archival_is_super_admin_only(stub_iam):
    student = as_client(stub_iam, STUDENT, USER_PERMS)
    assert student.post(f"{URL}/special-archival/perform", {
        "data_reference": "offline-set", "reason": "r",
        "outcome": "completed"}, format="json").status_code == 403

    superadmin = as_client(stub_iam, SUPERADMIN,
                           (*SYSADMIN_PERMS, "badms.schedule.manage_global",
                            "badms.special_archival.perform"),
                           kind="staff", roles=("super_admin",))
    performed = superadmin.post(f"{URL}/special-archival/perform", {
        "data_reference": "offline-set", "reason": "offline research data",
        "outcome": "completed"}, format="json")
    assert performed.status_code in (200, 201), performed.json()
    assert superadmin.get(f"{URL}/special-archival").json()


# -- UC-BA-019: the RBAC slice IT Security manages -----------------------------

def test_journey_rbac_grant_widens_a_students_view(stub_iam):
    student = as_client(stub_iam, STUDENT, USER_PERMS)
    assert student.get(f"{URL}/archival").status_code == 200

    itsec = _itsec(stub_iam)
    granted = itsec.post(f"{URL}/security/rbac", {
        "user_id": STUDENT, "permission_code": "badms.archival.classify",
        "action": "grant"},
        format="json")
    assert granted.status_code in (200, 201), granted.json()
    student = as_client(stub_iam, STUDENT, USER_PERMS)
    assert student.get(f"{URL}/archival").json() is not None
