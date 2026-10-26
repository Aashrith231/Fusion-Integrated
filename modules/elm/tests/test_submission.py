"""Applying for leave: the validation gates and the happy paths
(EL-UC-001). Every gate here is a specification BR."""
from datetime import date
from decimal import Decimal as D

import pytest

from conftest import make_principal
from core.api.exceptions import ConflictError, PermissionDeniedError

from .support import (
    APP,
    CLOSED_HOLIDAY,
    DIRECTOR,
    FACULTY,
    HEAD,
    RESTRICTED_HOLIDAY,
    VACATION,
    applicant,
    director,
    principal,
)

pytestmark = pytest.mark.django_db

MON, TUE, WED, THU, FRI = (date(2026, 3, d) for d in (2, 3, 4, 5, 6))
WEEK_AFTER = (date(2026, 3, 16), date(2026, 3, 20))


def make_draft(principal_, category="CL", start=MON, end=FRI, **fields):
    from modules.elm.services import applications as applications_service

    return applications_service.create_draft(
        principal_, category=category, start_date=start, end_date=end,
        **fields)


def submit(principal_, request, **kw):
    from modules.elm.services import applications as applications_service

    return applications_service.submit(request, principal_, **kw)


def apply(principal_, category="CL", start=MON, end=FRI, **fields):
    return submit(principal_, make_draft(principal_, category, start, end,
                                         **fields))


class TestHappyPaths:
    """A CL/RH request is Unit-Head-final; SCL/EL/COL/VL route higher."""

    def test_staff_cl_week_skipping_a_closed_holiday(self, world):
        request = apply(applicant())
        assert request.status == "awaiting_unit_head_review"
        assert request.days == D("4")          # Mon–Fri minus closed Thu
        assert request.leave_year == world["leave_year"]
        # The route snapshot names the Unit Head as final authority.
        assert request.route == [{"role": "unit_head",
                                  "decision": "final",
                                  "authority": None}]

    def test_higher_sanction_routes_through_establishment_when_configured(
            self, world):
        request = apply(applicant(), "EL", date(2026, 3, 16), date(2026, 3, 20))
        assert request.status == "awaiting_unit_head_review"
        assert request.days == D("5")          # continuous counting
        assert [s["role"] for s in request.route] == [
            "unit_head", "establishment", "sanctioning_authority"]
        assert request.route[-1]["authority"] == "Dean"

    def test_faculty_vl_inside_a_vacation_period(self, world):
        p = principal(FACULTY)
        request = apply(p, "VL", VACATION[0], VACATION[1])
        assert request.status == "awaiting_unit_head_review"
        assert request.days == D("12")

    def test_rh_request_matching_the_published_calendar(self, world):
        request = apply(applicant(), "RH", RESTRICTED_HOLIDAY,
                        RESTRICTED_HOLIDAY)
        assert request.status == "awaiting_unit_head_review"
        assert request.days == D("1")

    def test_scl_single_day(self, world):
        request = apply(applicant(), "SCL", WED, WED)
        assert request.status == "awaiting_unit_head_review"
        assert request.days == D("1")

    def test_half_day_cl(self, world):
        request = apply(applicant(), start_half="first")
        assert request.days == D("3.5")        # 4 working days − ½

    def test_director_self_sanctions_their_own_application(self, world):
        p = director()
        request = apply(p, "CL", MON, WED)
        assert request.status == "awaiting_director_self_sanction"
        assert request.route == [{"role": "director_self_sanction",
                                  "decision": "final",
                                  "authority": None}]

    def test_draft_stays_draft_until_submitted(self, world):
        draft = make_draft(applicant())
        assert draft.status == "draft"
        assert draft.route == []               # resolved only on submit


class TestApplicability:
    """BR-EL-001/006/010: category conditions."""

    def test_vl_is_faculty_only(self, world):
        with pytest.raises(ConflictError):
            apply(applicant(), "VL", VACATION[0], VACATION[1])

    def test_vl_only_during_a_published_vacation_period(self, world):
        p = principal(FACULTY, kind="faculty")
        with pytest.raises(ConflictError):
            apply(p, "VL", date(2026, 4, 2), date(2026, 4, 10))

    def test_half_days_are_cl_only(self, world):
        with pytest.raises(ConflictError):
            apply(applicant(), "SCL", MON, MON, start_half="first")

    def test_rh_must_match_the_calendar(self, world):
        with pytest.raises(ConflictError):
            apply(applicant(), "RH", TUE, TUE)   # Tuesday is not an RH

    def test_rh_span_may_not_mix_rh_and_ordinary_days(self, world):
        with pytest.raises(ConflictError):
            apply(applicant(), "RH", RESTRICTED_HOLIDAY, date(2026, 3, 10))

    def test_col_requires_medical_evidence_by_default(self, world):
        with pytest.raises(ConflictError) as err:
            apply(applicant(), "COL", MON, WED)
        assert err.value.code == "medical_evidence_required"

    def test_col_with_evidence_reference(self, world):
        request = apply(applicant(), "COL", MON, WED,
                        evidence={"medical": "MC-2026-0042"})
        assert request.status == "awaiting_unit_head_review"


class TestPeriodAndCalendar:
    """BR-EL-011 and the basic interval sanity."""

    def test_end_before_start(self, world):
        with pytest.raises(ConflictError) as err:
            apply(applicant(), end=MON, start=FRI)
        assert err.value.code == "invalid_period"

    def test_period_with_no_countable_days(self, world):
        # Saturday–Sunday: nothing counts for CL.
        with pytest.raises(ConflictError) as err:
            apply(applicant(), start=date(2026, 3, 7), end=date(2026, 3, 8))
        assert err.value.code == "calendar_violation"

    def test_whole_period_falling_on_a_closed_holiday(self, world):
        with pytest.raises(ConflictError) as err:
            apply(applicant(), start=CLOSED_HOLIDAY, end=CLOSED_HOLIDAY)
        assert err.value.code == "calendar_violation"


class TestBalanceAndOverlap:
    """BR-EL-002…005/008/009 and BR-EL-012/013."""

    def test_insufficient_balance(self, world):
        from modules.elm.models import LeaveAccount
        from modules.elm.services import policy as policy_service

        account = LeaveAccount.objects.get(
            user_id=APP, category="CL", leave_year=world["leave_year"])
        account.used_days = D("7.5")           # 0.5 left of 8
        account.save()
        with pytest.raises(ConflictError) as err:
            apply(applicant())
        assert err.value.code == "insufficient_balance"

    def test_half_day_fits_a_half_day_balance(self, world):
        from modules.elm.models import LeaveAccount

        account = LeaveAccount.objects.get(
            user_id=APP, category="CL", leave_year=world["leave_year"])
        account.used_days = D("7.5")
        account.save()
        request = apply(applicant(), start=MON, end=MON, start_half="first")
        assert request.status == "awaiting_unit_head_review"

    def test_pending_requests_reserve_the_balance(self, world):
        """Two in-flight requests cannot double-book one balance."""
        first = apply(applicant(), start=MON, end=FRI)   # 4 days pending
        with pytest.raises(ConflictError) as err:
            apply(applicant(), start=date(2026, 3, 16),
                  end=date(2026, 3, 20))
        assert err.value.code == "insufficient_balance"
        assert first.status == "awaiting_unit_head_review"

    def test_overlap_with_pending_request(self, world):
        apply(applicant(), start=MON, end=WED)
        with pytest.raises(ConflictError) as err:
            apply(applicant(), start=TUE, end=FRI)
        assert err.value.code == "overlapping_leave"

    def test_first_and_second_half_cl_on_one_day_coexist(self, world):
        first = apply(applicant(), start=MON, end=MON, start_half="first")
        second = apply(applicant(), start=MON, end=MON, end_half="second")
        assert first.days == second.days == D("0.5")
        assert first.status == second.status == "awaiting_unit_head_review"

    def test_overlap_with_approved_leave_record(self, world):
        from modules.elm.models import LeaveRecord

        LeaveRecord.objects.create(
            user_id=APP, leave_year=world["leave_year"], category="CL",
            start_date=date(2026, 3, 16), end_date=date(2026, 3, 20),
            days=D("5"), status="ongoing")
        with pytest.raises(ConflictError) as err:
            apply(applicant(), start=date(2026, 3, 16), end=date(2026, 3, 18))
        assert err.value.code == "overlapping_leave"


class TestStationLeave:
    """BR-EL-013: station details ride in the same application."""

    def test_station_leave_requires_details(self, world):
        with pytest.raises(ConflictError) as err:
            apply(applicant(), station_leave=True)
        assert err.value.code == "station_details_required"

    def test_station_leave_with_details(self, world):
        request = apply(applicant(), station_leave=True,
                        station_details={"destination": "Bhopal",
                                         "from": str(MON),
                                         "to": str(WED)})
        assert request.station_leave
        assert request.status == "awaiting_unit_head_review"


class TestSubmissionAccess:
    """Ownership, state and permission gates."""

    def test_other_people_cannot_submit_your_draft(self, world):
        other = principal(202, permissions=("elm.leave.apply",))
        draft = make_draft(applicant())
        with pytest.raises(PermissionDeniedError):
            submit(other, draft)

    def test_only_a_draft_can_be_submitted(self, world):
        submitted = apply(applicant())
        with pytest.raises(ConflictError):
            submit(applicant(), submitted)

    def test_apply_permission_is_required(self, world):
        stranger = make_principal(user_id=999, kind="staff",
                                  permissions=("elm.leave.view_self",),
                                  modules=("elm",))
        with pytest.raises(PermissionDeniedError):
            make_draft(stranger)


class TestEntitlements:
    """BR-EL-005/006: non-faculty carry the EL credit; faculty earn EL
    only through VL conversion."""

    def test_non_faculty_el_entitlement(self, world):
        from modules.elm.services import policy as policy_service

        assert policy_service.entitlement_for("EL", "staff") == D("30")

    def test_faculty_el_comes_only_from_vl_conversion(self, world):
        from modules.elm.models import LeaveAccount

        from modules.elm.services import policy as policy_service

        account = LeaveAccount.objects.get(
            user_id=FACULTY, category="EL", leave_year=world["leave_year"])
        assert account.entitled_days == D("0")
        assert policy_service.entitlement_for("EL", "faculty") == D("0")

    def test_faculty_cannot_apply_for_el_without_converted_credit(self, world):
        with pytest.raises(ConflictError) as err:
            apply(principal(FACULTY, kind="faculty"), "EL",
                  date(2026, 3, 16), date(2026, 3, 20))
        assert err.value.code == "insufficient_balance"

    def test_staff_vl_entitlement_is_zero(self, world):
        from modules.elm.services import policy as policy_service

        assert policy_service.entitlement_for("VL", "staff") == D("0")


class TestEstablishmentOnlyWhereConfigured:
    """BR-EL-019: the Establishment step occurs only where configured —
    a unit type with no hierarchy row routes straight to the authority."""

    def test_no_hierarchy_row_means_no_establishment_step(self, world):
        from modules.elm.models import EmployeeProfile

        profile = EmployeeProfile.objects.get(user_id=APP)
        profile.unit_code = world["office"]    # office unit: no config rows
        profile.save()
        office = world["office"]
        office.head_user_id = HEAD             # the office still has a head
        office.save()

        request = apply(applicant(), "EL", date(2026, 3, 16),
                        date(2026, 3, 20))
        assert [s["role"] for s in request.route] == [
            "unit_head", "sanctioning_authority"]
