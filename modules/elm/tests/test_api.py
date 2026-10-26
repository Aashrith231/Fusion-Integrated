"""The HTTP layer: authentication, authorization and the
scope gates — the two platform gates plus the office-holder
checks (the *right* reviewer, not merely a permission
holder), and the 401/403/404/409/400 semantics.

The IAM is stubbed at the root ``conftest``; every principal
here resolves through a token → session map so one test can
call the API as several people.
"""
import pytest
from rest_framework.test import APIClient

from .support import (
    APP,
    COLLEAGUE,
    DEAN,
    EST,
    HEAD,
    applicant,
)
from .test_lifecycle import apply, approve

pytestmark = pytest.mark.django_db

EMPLOYEE_PERMS = (
    "elm.leave.apply", "elm.leave.view_self", "elm.leave.withdraw",
    "elm.leave.nominate", "elm.substitute.respond", "elm.leave.cancel",
    "elm.leave.extend", "elm.leave.resume",
)


def err_code(response):
    return response.data["error"]["code"]


@pytest.fixture
def api(stub_iam):
    """A factory: ``api(user_id, permissions=..., kind=...)``
    returns an APIClient authenticated as that principal."""
    from conftest import make_session

    fake = stub_iam()
    fake.sessions = {}

    def resolve_session(*, auth_token=None, cookies=None):
        return fake.sessions.get(auth_token)

    fake.resolve_session = resolve_session

    def _client(user_id, permissions=EMPLOYEE_PERMS, kind="staff",
                modules=("elm",)):
        token = f"tok-{user_id}"
        fake.sessions[token] = make_session(
            user_id=user_id, permissions=tuple(permissions),
            modules=tuple(modules), kind=kind)
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f"Token {token}")
        return client

    return _client


class TestAuthenticationAndAuthorization:

    def test_anonymous_is_unauthorized(self, world):
        client = APIClient()
        assert client.get("/api/v1/elm/me").status_code == 401

    def test_the_module_grant_is_required(self, api, world):
        client = api(APP, permissions=EMPLOYEE_PERMS, modules=())
        assert client.get("/api/v1/elm/me").status_code == 403

    def test_the_permission_is_required(self, api, world):
        client = api(APP, permissions=("elm.leave.view_self",))
        assert client.post(
            "/api/v1/elm/requests",
            {"category": "CL",
             "start_date": "2026-03-16",
             "end_date": "2026-03-20"},
            format="json").status_code == 403


class TestScoping:

    def test_someone_elses_request_is_a_404(self, api, world):
        base = approve(apply(applicant()))
        stranger = api(999, permissions=("elm.leave.view_self",))
        assert stranger.get(
            f"/api/v1/elm/requests/{base.id}").status_code == 404

    def test_a_participant_sees_the_request(self, api, world):
        request = apply(applicant())
        client = api(HEAD, permissions=(
            "elm.review.unit_head", "elm.leave.view_self"))
        response = client.get(f"/api/v1/elm/requests/{request.id}")
        assert response.status_code == 200
        assert response.data["status"] == "awaiting_unit_head_review"

    def test_the_records_list_scopes_to_self(self, api, world):
        approve(apply(applicant()))
        own = api(APP).get("/api/v1/elm/records")
        assert own.status_code == 200
        assert {row["user_id"] for row in own.data} == {APP}

    def test_the_records_view_bypass_sees_everything(self, api, world):
        approve(apply(applicant()))
        admin_client = api(601, permissions=("elm.records.view",))
        response = admin_client.get("/api/v1/elm/records")
        assert response.status_code == 200
        assert {row["user_id"] for row in response.data} == {APP}


class TestEmployeeSurface:

    def test_create_and_submit_in_one_call(self, api, world):
        client = api(APP)
        response = client.post(
            "/api/v1/elm/requests",
            {"category": "CL",
             "start_date": "2026-03-16",
             "end_date": "2026-03-20"},
            format="json")
        assert response.status_code == 201
        assert response.data["status"] == "awaiting_unit_head_review"

    def test_a_decision_by_request_id(self, api, world):
        client = api(APP)
        request_id = client.post(
            "/api/v1/elm/requests",
            {"category": "CL",
             "start_date": "2026-03-16",
             "end_date": "2026-03-20"},
            format="json").data["id"]
        head_client = api(HEAD, permissions=("elm.review.unit_head",))
        response = head_client.post(
            f"/api/v1/elm/requests/{request_id}/decide",
            {"outcome": "approve"}, format="json")
        assert response.status_code == 200
        assert response.data["status"] == "approved"

    def test_a_non_participant_cannot_even_probe_the_decision_endpoint(
            self, api, world):
        """Scope before authority: a principal with the right
        permission but no seat on the request learns nothing —
        not even that the request exists."""
        request_id = api(APP).post(
            "/api/v1/elm/requests",
            {"category": "CL",
             "start_date": "2026-03-16",
             "end_date": "2026-03-20"},
            format="json").data["id"]
        # 402 holds the permission but has no seat on the request.
        other = api(402, permissions=("elm.review.unit_head",))
        response = other.post(
            f"/api/v1/elm/requests/{request_id}/decide",
            {"outcome": "approve"}, format="json")
        assert response.status_code == 404

    def test_withdrawal(self, api, world):
        client = api(APP)
        request_id = client.post(
            "/api/v1/elm/requests",
            {"category": "CL",
             "start_date": "2026-03-16",
             "end_date": "2026-03-20"},
            format="json").data["id"]
        response = client.post(
            f"/api/v1/elm/requests/{request_id}/withdraw",
            {"reason": "Changed plans"}, format="json")
        assert response.status_code == 200
        assert response.data["status"] == "withdrawn"

    def test_withdrawing_after_a_decision_is_refused(self, api, world):
        base = approve(apply(applicant()))
        client = api(APP)
        response = client.post(
            f"/api/v1/elm/requests/{base.id}/withdraw",
            {"reason": "Too late"}, format="json")
        assert response.status_code == 409


class TestDecisionSeats:

    def _higher_sanction(self, api):
        """An EL request recommended by the Unit Head — now
        awaiting Establishment routing."""
        from modules.elm.services import workflow

        request_id = api(APP).post(
            "/api/v1/elm/requests",
            {"category": "EL",
             "start_date": "2026-03-16",
             "end_date": "2026-03-20"},
            format="json").data["id"]
        head_client = api(HEAD, permissions=(
            "elm.review.unit_head",))
        head_client.post(
            f"/api/v1/elm/requests/{request_id}/decide",
            {"outcome": "recommended"}, format="json")
        return workflow, request_id

    def test_the_establishment_routes_but_never_decides(self, api, world):
        from modules.elm.models import LeaveTask

        _, request_id = self._higher_sanction(api)
        task = LeaveTask.objects.get(
            request_id=request_id, task_class="establishment_routing",
            assignee_user_id=EST, status="pending")
        est_client = api(EST, permissions=(
            "elm.review.establishment",))

        wrong = est_client.post(
            f"/api/v1/elm/tasks/{task.id}/decide",
            {"outcome": "approve"}, format="json")
        assert wrong.status_code == 409
        assert err_code(wrong) == "invalid_outcome"

        right = est_client.post(
            f"/api/v1/elm/tasks/{task.id}/decide",
            {"outcome": "forward"}, format="json")
        assert right.status_code == 200
        assert right.data["status"] == "awaiting_final_sanction_decision"

    def test_the_dean_sanctions_through_the_task_endpoint(self, api, world):
        from modules.elm.models import LeaveTask

        _, request_id = self._higher_sanction(api)
        est_client = api(EST, permissions=(
            "elm.review.establishment",))
        est_task = LeaveTask.objects.get(
            request_id=request_id, task_class="establishment_routing",
            assignee_user_id=EST, status="pending")
        est_client.post(
            f"/api/v1/elm/tasks/{est_task.id}/decide",
            {"outcome": "forward"}, format="json")

        dean_client = api(DEAN, permissions=("elm.sanction.final",))
        task = LeaveTask.objects.get(
            request_id=request_id, task_class="final_sanction",
            assignee_user_id=DEAN, status="pending")
        response = dean_client.post(
            f"/api/v1/elm/tasks/{task.id}/decide",
            {"outcome": "approve"}, format="json")
        assert response.status_code == 200
        assert response.data["status"] == "approved"

    def test_someone_elses_task_is_a_404(self, api, world):
        from modules.elm.models import LeaveTask

        request_id = api(APP).post(
            "/api/v1/elm/requests",
            {"category": "CL",
             "start_date": "2026-03-16",
             "end_date": "2026-03-20"},
            format="json").data["id"]
        task = LeaveTask.objects.get(
            request_id=request_id, assignee_user_id=HEAD)
        est_client = api(EST, permissions=(
            "elm.review.establishment", "elm.leave.view_self"))
        assert est_client.get(
            f"/api/v1/elm/tasks/{task.id}").status_code == 404

    def test_a_resumption_task_is_not_a_decision_seat(self, api, world):
        """The resumption review has its own endpoint; deciding a
        resumption task through the decision dispatch would also
        crash on the requestless offline case."""
        from modules.elm.models import LeaveTask
        from modules.elm.services import lifecycle

        from .test_lifecycle import EL_END, EL_START

        base = approve(apply(applicant(), "EL", EL_START, EL_END))
        lifecycle.submit_resumption(
            applicant(), record_id=base.leave_record_id,
            actual_resumption_date=EL_END)
        task = LeaveTask.objects.get(
            task_class="resumption_review", status="pending")
        dean_client = api(DEAN, permissions=(
            "elm.sanction.final", "elm.resume.review"))
        response = dean_client.post(
            f"/api/v1/elm/tasks/{task.id}/decide",
            {"outcome": "approve"}, format="json")
        assert response.status_code == 409


class TestSubstituteAndResumptionSurface:

    def test_the_nominee_responds_through_the_task_endpoint(
            self, api, world):
        client = api(APP)
        # A substitute-gated request is submitted in two steps:
        # the draft, then the submission that names the nominee.
        request_id = client.post(
            "/api/v1/elm/requests",
            {"category": "CL",
             "start_date": "2026-03-16",
             "end_date": "2026-03-20",
             "submit": False},
            format="json").data["id"]
        client.post(
            f"/api/v1/elm/requests/{request_id}/submit",
            {"substitute_required": True,
             "substitute_user_id": COLLEAGUE},
            format="json")

        colleague = api(COLLEAGUE)
        tasks = colleague.get("/api/v1/elm/substitute-tasks")
        assert tasks.status_code == 200
        assert len(tasks.data) == 1
        task_id = tasks.data[0]["id"]

        response = colleague.post(
            f"/api/v1/elm/substitute-tasks/{task_id}/respond",
            {"accept": True}, format="json")
        assert response.status_code == 200
        assert response.data["status"] == "awaiting_unit_head_review"

    def test_substituting_on_a_terminal_request_is_refused(
            self, api, world):
        base = approve(apply(applicant()))
        client = api(APP)
        response = client.post(
            f"/api/v1/elm/requests/{base.id}/substitute",
            {"nominee_user_id": COLLEAGUE}, format="json")
        assert response.status_code == 409
        assert err_code(response) == "invalid_transition"

    def test_the_resumption_review_endpoint(self, api, world):
        from modules.elm.services import lifecycle

        from .test_lifecycle import EL_END, EL_START

        base = approve(apply(applicant(), "EL", EL_START, EL_END))
        resumption = lifecycle.submit_resumption(
            applicant(), record_id=base.leave_record_id,
            actual_resumption_date=EL_END)

        stranger = api(999, permissions=("elm.resume.review",))
        assert stranger.post(
            f"/api/v1/elm/resumptions/{resumption.id}/review",
            {"outcome": "normal"}, format="json").status_code == 403

        dean_client = api(DEAN, permissions=("elm.resume.review",))
        response = dean_client.post(
            f"/api/v1/elm/resumptions/{resumption.id}/review",
            {"outcome": "normal"}, format="json")
        assert response.status_code == 200
        assert response.data["status"] == "reviewed_normal"


class TestAdminSurface:

    def test_policy_junk_is_a_400_not_a_500(self, api, world):
        client = api(601, permissions=("elm.config.policy",))
        response = client.put(
            "/api/v1/elm/admin/policy",
            {"year_end_month_day": "not-a-date",
             "entitlements": "junk"},
            format="json")
        assert response.status_code == 400

    def test_policy_update_round_trip(self, api, world):
        client = api(601, permissions=("elm.config.policy",))
        response = client.put(
            "/api/v1/elm/admin/policy",
            {"year_end_month_day": "03-31",
             "station_leave_enabled": True},
            format="json")
        assert response.status_code == 200
        assert response.data["year_end_month_day"] == "03-31"

    def test_sla_junk_is_a_400(self, api, world):
        client = api(601, permissions=("elm.config.sla",))
        response = client.post(
            "/api/v1/elm/admin/sla",
            {"task_class": "not-a-task",
             "reminder_hours": 0,
             "escalation_hours": -5},
            format="json")
        assert response.status_code == 400

    def test_sla_threshold_order_is_enforced(self, api, world):
        client = api(601, permissions=("elm.config.sla",))
        response = client.post(
            "/api/v1/elm/admin/sla",
            {"task_class": "unit_head_review",
             "reminder_hours": 10,
             "escalation_hours": 5},
            format="json")
        assert response.status_code == 409
        assert err_code(response) == "sla_threshold_order"

    def test_the_admin_seats_require_their_permissions(self, api, world):
        client = api(APP)                      # no config permissions
        assert client.put(
            "/api/v1/elm/admin/policy", {},
            format="json").status_code == 403
        assert client.post(
            "/api/v1/elm/admin/sla",
            {"task_class": "unit_head_review",
             "reminder_hours": 1, "escalation_hours": 2},
            format="json").status_code == 403
