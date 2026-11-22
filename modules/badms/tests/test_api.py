"""The HTTP surface: module grant, permission gates and scope (BR-BA-020,
BR-BA-010, UC-BA-015 E1, plus the privilege-escalation checks)."""

import pytest
from django.utils import timezone

from modules.badms.models import (
    ArchivalRequest,
    AuditEvent,
    Backup,
    NotificationOutbox,
    RestorationRequest,
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
    make_archival,
)

pytestmark = pytest.mark.django_db

STUDENT = 1001
STUDENT2 = 1002
HOD = 20
SYSADMIN = 9
ITSEC = 40
SUPERADMIN = 10
URL = "/api/v1/badms"


def _client(stub_iam, uid, perms, kind="student"):
    return api_client(stub_iam, uid=uid, perms=perms, kind=kind)


# -- The manual backup endpoint (BR-BA-001) ---------------------------------------------
class TestBackupEndpoints:
    def test_sysadmin_triggers_a_manual_backup(self, stub_iam, repo):
        client = _client(stub_iam, SYSADMIN, SYSADMIN_PERMS, kind="staff")
        response = client.post(f"{URL}/backups/manual", {}, format="json")
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    def test_student_cannot_trigger(self, stub_iam, repo):
        client = _client(stub_iam, STUDENT, USER_PERMS)
        response = client.post(f"{URL}/backups/manual", {}, format="json")
        assert response.status_code == 403
        assert Backup.objects.count() == 0

    def test_backup_history_needs_no_trigger_grant(self, stub_iam, repo):
        """AFR-BA-018: a user sees history and status; the artifact path is
        withheld (BR-BA-020)."""
        Backup.objects.create(kind="manual", status="success",
                              repository=repo, started_at=timezone.now(),
                              artifact_ref="vault://x")
        client = _client(stub_iam, STUDENT, USER_PERMS)
        response = client.get(f"{URL}/backups")
        assert response.status_code == 200
        row = response.json()[0]
        assert row["status"] == "success"
        assert "artifact_ref" not in row

    def test_sysadmin_sees_the_artifact_reference(self, stub_iam, repo):
        Backup.objects.create(kind="manual", status="success",
                              repository=repo, started_at=timezone.now(),
                              artifact_ref="vault://x")
        client = _client(stub_iam, SYSADMIN, SYSADMIN_PERMS, kind="staff")
        row = client.get(f"{URL}/backups").json()[0]
        assert row["artifact_ref"] == "vault://x"


# -- Archival: department scope over HTTP (BR-BA-002/010) ----------------------------------
def _submit(stub_iam, uid=STUDENT, **kw):
    give_department(uid, kw.pop("department", DEPT))
    client = _client(stub_iam, uid, USER_PERMS)
    payload = {
        "file_name": "thesis.pdf", "file_date": "2026-08-01",
        "owners": "Owner", "file_type": "pdf", "reason": "Record",
        "attachment": "att://x", "attachment_size_bytes": 0,
        **kw}
    response = client.post(f"{URL}/archival/submit", payload, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


class TestArchivalEndpoints:
    def test_student_submits_and_sees_own_request(self, stub_iam):
        row = _submit(stub_iam)
        client = _client(stub_iam, STUDENT, USER_PERMS)
        assert client.get(f"{URL}/archival/mine").json()[0]["id"] == row["id"]
        detail = client.get(f"{URL}/archival/{row['id']}")
        assert detail.status_code == 200

    def test_hod_sees_department_queue_not_foreign(self, stub_iam):
        """BR-BA-010: the HoD's queue carries their department only."""
        own = _submit(stub_iam, STUDENT)
        _submit(stub_iam, STUDENT2, department=OTHER_DEPT)
        give_department(HOD, DEPT)
        client = _client(stub_iam, HOD, HOD_PERMS, kind="staff")
        rows = client.get(f"{URL}/archival").json()
        ids = {r["id"] for r in rows}
        assert own["id"] in ids
        foreign = ArchivalRequest.objects.get(
            user_id=STUDENT2, department=OTHER_DEPT)
        assert foreign.pk not in ids

    def test_hod_of_other_department_cannot_decide(self, stub_iam):
        row = _submit(stub_iam, STUDENT)
        give_department(HOD, OTHER_DEPT)
        client = _client(stub_iam, HOD, HOD_PERMS, kind="staff")
        response = client.post(f"{URL}/archival/{row['id']}/decide",
                               {"decision": "approve"}, format="json")
        assert response.status_code == 403
        assert ArchivalRequest.objects.get(pk=row["id"]).status == "submitted"

    def test_respective_hod_decides_over_http(self, stub_iam):
        row = _submit(stub_iam, STUDENT)
        give_department(HOD, DEPT)
        client = _client(stub_iam, HOD, HOD_PERMS, kind="staff")
        response = client.post(f"{URL}/archival/{row['id']}/decide",
                               {"decision": "approve"}, format="json")
        assert response.status_code == 200
        assert response.json()["status"] == "hod_approved"

    def test_student_cannot_decide(self, stub_iam):
        row = _submit(stub_iam, STUDENT)
        client = _client(stub_iam, STUDENT, USER_PERMS)
        response = client.post(f"{URL}/archival/{row['id']}/decide",
                               {"decision": "approve"}, format="json")
        assert response.status_code == 403

    def test_sysadmin_classifies_over_http(self, stub_iam):
        row = _submit(stub_iam, STUDENT)
        give_department(HOD, DEPT)
        hod = _client(stub_iam, HOD, HOD_PERMS, kind="staff")
        hod.post(f"{URL}/archival/{row['id']}/decide", {"decision": "approve"},
                 format="json")
        client = _client(stub_iam, SYSADMIN, SYSADMIN_PERMS, kind="staff")
        response = client.post(f"{URL}/archival/{row['id']}/classify",
                               {"classification": "sensitive"}, format="json")
        assert response.status_code == 200
        assert response.json()["status"] == "routed_to_security"

    def test_it_security_encrypts_over_http(self, stub_iam, tmp_path,
                                            settings):
        settings.BADMS_ARCHIVE_ROOT = str(tmp_path / "archives")
        row = _submit(stub_iam, STUDENT)
        give_department(HOD, DEPT)
        hod = _client(stub_iam, HOD, HOD_PERMS, kind="staff")
        hod.post(f"{URL}/archival/{row['id']}/decide", {"decision": "approve"},
                 format="json")
        sysadmin = _client(stub_iam, SYSADMIN, SYSADMIN_PERMS, kind="staff")
        sysadmin.post(f"{URL}/archival/{row['id']}/classify",
                      {"classification": "sensitive"}, format="json")
        client = _client(stub_iam, ITSEC, ITSEC_PERMS, kind="staff")
        response = client.post(f"{URL}/archival/{row['id']}/encryption",
                               {"key_ref": "kms://k1"}, format="json")
        assert response.status_code == 200
        assert response.json()["status"] == "encrypted"

    def test_request_not_owned_not_disclosed(self, stub_iam):
        """UC-BA-015 E1: a foreign request is a 404, not a 403."""
        row = _submit(stub_iam, STUDENT2, department=OTHER_DEPT)
        client = _client(stub_iam, STUDENT, USER_PERMS)
        response = client.get(f"{URL}/archival/{row['id']}")
        assert response.status_code == 404

    def test_my_requests_tracks_all_types(self, stub_iam, profile_factory):
        _submit(stub_iam, STUDENT)
        profile_factory(STUDENT, used=1024, quota=1024)
        client = _client(stub_iam, STUDENT, USER_PERMS)
        client.post(f"{URL}/storage/extensions/submit",
                    {"requested_bytes": 1024, "justification": "Need"},
                    format="json")
        rows = client.get(f"{URL}/me/requests").json()
        kinds = {r["kind"] for r in rows}
        assert {"archival", "storage_extension"} <= kinds


# -- Restoration endpoints -----------------------------------------------------------------
class TestRestorationEndpoints:
    def test_sensitive_flow_over_http(self, stub_iam, tmp_path, settings):
        settings.BADMS_RESTORE_ROOT = str(tmp_path / "restored")
        archived = make_archival(uid=STUDENT, classification="sensitive",
                                 status="encrypted", encrypted=True)
        artifact = tmp_path / "a.aes256"
        artifact.write_bytes(b"payload")
        archived.archive_ref = str(artifact)
        archived.save(update_fields=["archive_ref"])

        student = _client(stub_iam, STUDENT, USER_PERMS)
        response = student.post(
            f"{URL}/restorations/request", {"archival": archived.pk},
            format="json")
        assert response.status_code == 201
        assert response.json()["status"] == "pending_approval"

        # Blocked before approval — and the student cannot execute anyway.
        request_id = response.json()["id"]
        blocked = student.post(f"{URL}/restorations/{request_id}/execute",
                               {}, format="json")
        assert blocked.status_code == 403
        sysadmin = _client(stub_iam, SYSADMIN, SYSADMIN_PERMS, kind="staff")
        blocked = sysadmin.post(f"{URL}/restorations/{request_id}/execute",
                                {}, format="json")
        assert blocked.status_code == 409

        sysadmin = _client(stub_iam, SYSADMIN, SYSADMIN_PERMS, kind="staff")
        decided = sysadmin.post(
            f"{URL}/restorations/{response.json()['id']}/decide",
            {"decision": "approve"}, format="json")
        assert decided.status_code == 200
        executed = sysadmin.post(
            f"{URL}/restorations/{response.json()['id']}/execute", {},
            format="json")
        assert executed.status_code == 200
        assert executed.json()["status"] == "restored"

    def test_hod_cannot_approve_sensitive_restoration(self, stub_iam):
        """BR-BA-005: no HoD route for restoration in this version."""
        archived = make_archival(uid=STUDENT, classification="sensitive",
                                 status="encrypted", encrypted=True)
        request = RestorationRequest.objects.create(
            user_id=STUDENT, archival=archived, classification="sensitive",
            status="pending_approval")
        give_department(HOD, DEPT)
        client = _client(stub_iam, HOD, HOD_PERMS, kind="staff")
        response = client.post(f"{URL}/restorations/{request.pk}/decide",
                               {"decision": "approve"}, format="json")
        assert response.status_code == 403


# -- Storage endpoints -------------------------------------------------------------------------
class TestStorageEndpoints:
    def _client_full(self, stub_iam, profile_factory):
        profile_factory(STUDENT, used=1024, quota=1024)
        give_department(STUDENT, DEPT)
        return _client(stub_iam, STUDENT, USER_PERMS)

    def test_extension_flow_over_http(self, stub_iam, profile_factory):
        student = self._client_full(stub_iam, profile_factory)
        response = student.post(
            f"{URL}/storage/extensions/submit",
            {"requested_bytes": 1024, "justification": "Need"},
            format="json")
        assert response.status_code == 201
        extension_id = response.json()["id"]

        give_department(HOD, DEPT)
        hod = _client(stub_iam, HOD, HOD_PERMS, kind="staff")
        queue = hod.get(f"{URL}/storage/extensions").json()
        assert extension_id in {r["id"] for r in queue}
        decided = hod.post(f"{URL}/storage/extensions/{extension_id}/decide",
                           {"decision": "approve"}, format="json")
        assert decided.status_code == 200
        assert decided.json()["status"] == "approved"
        assert NotificationOutbox.objects.filter(
            topic="storage.decided", recipient_user_id=STUDENT).exists()

    def test_not_full_quota_rejected_over_http(self, stub_iam,
                                               profile_factory):
        profile_factory(STUDENT, used=10, quota=1024)
        client = _client(stub_iam, STUDENT, USER_PERMS)
        response = client.post(
            f"{URL}/storage/extensions/submit",
            {"requested_bytes": 1024, "justification": "Need"},
            format="json")
        assert response.status_code == 422

    def test_my_storage_shows_threshold_status(self, stub_iam,
                                               profile_factory):
        profile_factory(STUDENT, used=1024, quota=1024)
        client = _client(stub_iam, STUDENT, USER_PERMS)
        body = client.get(f"{URL}/storage/me").json()
        assert body["full"] is True


# -- Audit, security and reports over HTTP ---------------------------------------------------
class TestProtectedInformationEndpoints:
    def test_audit_log_for_sysadmin_only(self, stub_iam):
        """UC-BA-012 / BR-BA-020: only the authorised role reads the audit
        trail."""
        AuditEvent.objects.create(action="backup.completed", outcome="success",
                                  actor_kind="system")
        client = _client(stub_iam, SYSADMIN, SYSADMIN_PERMS, kind="staff")
        assert client.get(f"{URL}/audit").status_code == 200
        student = _client(stub_iam, STUDENT, USER_PERMS)
        assert student.get(f"{URL}/audit").status_code == 403

    def test_security_audit_for_it_security(self, stub_iam):
        client = _client(stub_iam, ITSEC, ITSEC_PERMS, kind="staff")
        assert client.get(f"{URL}/security/audit").status_code == 200
        client2 = _client(stub_iam, SYSADMIN, SYSADMIN_PERMS, kind="staff")
        assert client2.get(f"{URL}/security/audit").status_code == 403

    def test_policies_crud_by_it_security(self, stub_iam):
        client = _client(stub_iam, ITSEC, ITSEC_PERMS, kind="staff")
        response = client.post(
            f"{URL}/security/policies",
            {"name": "at-rest", "statement": "AES-256 for Sensitive data"},
            format="json")
        assert response.status_code == 201
        policy_id = response.json()["id"]
        patched = client.patch(f"{URL}/security/policies/{policy_id}",
                               {"is_active": False}, format="json")
        assert patched.status_code == 200
        assert patched.json()["is_active"] is False
        sysadmin = _client(stub_iam, SYSADMIN, SYSADMIN_PERMS, kind="staff")
        assert sysadmin.post(
            f"{URL}/security/policies", {"name": "x", "statement": "y"},
            format="json").status_code == 403

    def test_rbac_grant_and_revoke_by_it_security(self, stub_iam):
        client = _client(stub_iam, ITSEC, ITSEC_PERMS, kind="staff")
        granted = client.post(
            f"{URL}/security/rbac",
            {"user_id": STUDENT,
             "permission_code": "badms.archival.decide",
             "action": "grant"}, format="json")
        assert granted.status_code == 201
        # The grant is live: the student can now decide their department.
        give_department(STUDENT, DEPT)
        _submit(stub_iam, STUDENT2, department=DEPT)
        student = _client(stub_iam, STUDENT, USER_PERMS)
        queue = student.get(f"{URL}/archival").json()
        assert any(ArchivalRequest.objects.get(pk=r["id"]).user_id == STUDENT2
                   for r in queue)
        # The stub IAM is global — the student fetch replaced the session, so
        # reinstall the IT Security one before revoking.
        client = _client(stub_iam, ITSEC, ITSEC_PERMS, kind="staff")
        revoked = client.post(
            f"{URL}/security/rbac",
            {"user_id": STUDENT,
             "permission_code": "badms.archival.decide",
             "action": "revoke"}, format="json")
        assert revoked.status_code == 200

    def test_department_report_scope_over_http(self, stub_iam):
        _submit(stub_iam, STUDENT)
        give_department(HOD, DEPT)
        client = _client(stub_iam, HOD, HOD_PERMS, kind="staff")
        ok = client.get(f"{URL}/reports/department",
                        {"department": DEPT})
        assert ok.status_code == 200
        assert ok.json()["archival_total"] == 1
        denied = client.get(f"{URL}/reports/department",
                            {"department": OTHER_DEPT})
        assert denied.status_code == 403


# -- CSRF: a cookie-borne write needs the X-CSRF-Token header ------------------
class TestCsrfForCookieWrites:
    """A cookie is ambient; the header proves the request was meant
    (`core.api.csrf`, and the core test suite for the platform-wide rule)."""

    def _cookie_client(self, stub_iam, uid=STUDENT, perms=USER_PERMS):
        from django.conf import settings
        from rest_framework.test import APIClient

        from conftest import make_session

        stub_iam(make_session(user_id=uid, kind="student", modules=("badms",),
                              permissions=perms))
        client = APIClient(enforce_csrf_checks=False)
        client.credentials()          # no Authorization header: cookie only
        client.cookies[settings.IAM_AUTH_COOKIE_NAME] = "tok-123"
        return client

    def test_a_cookie_write_without_the_header_is_refused(self, stub_iam):
        client = self._cookie_client(stub_iam)
        archived = make_archival(uid=STUDENT, classification="sensitive",
                                 status="encrypted")
        response = client.post(f"{URL}/restorations/request",
                               {"archival": archived.pk}, format="json")
        assert response.status_code == 403

    def test_a_cookie_write_with_the_header_is_accepted(self, stub_iam):
        from core.api import csrf

        client = self._cookie_client(stub_iam)
        archived = make_archival(uid=STUDENT, classification="sensitive",
                                 status="encrypted")
        response = client.post(
            f"{URL}/restorations/request", {"archival": archived.pk},
            format="json", HTTP_X_CSRF_TOKEN=csrf.token_for("tok-123"))
        assert response.status_code == 201
