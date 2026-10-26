"""The pure domain layer: counting, overlap, routing and the state
machine — no database, so the maths and the STTs are pinned hard."""
from datetime import date
from decimal import Decimal as D

import pytest

from modules.elm.domain import routing as routing_domain
from modules.elm.domain import state_machine as machine
from modules.elm.domain.errors import InvalidTransition
from modules.elm.domain.leave_types import (
    APPLICANT_ACTION_REQUIRED,
    APPROVED,
    AWAITING_DIRECTOR_SELF_SANCTION,
    AWAITING_ESTABLISHMENT_ROUTING,
    AWAITING_EXTENSION_SUBSTITUTE,
    AWAITING_EXTENSION_UNIT_HEAD,
    AWAITING_FINAL_SANCTION_DECISION,
    AWAITING_SUBSTITUTE_RESPONSE,
    AWAITING_UNIT_HEAD_REVIEW,
    CANCELLATION_PENDING_ESTABLISHMENT,
    CANCELLATION_PENDING_FINAL,
    CANCELLATION_PENDING_UNIT_HEAD,
    DRAFT,
    EXTENSION_APPLICANT_ACTION_REQUIRED,
    EXTENSION_PENDING_ESTABLISHMENT,
    EXTENSION_PENDING_FINAL,
    KIND_CANCELLATION,
    KIND_EXTENSION,
    KIND_NEW,
    PENDING_STATES,
    REJECTED,
    STATES_BY_KIND,
    TERMINAL_STATES,
    WITHDRAWN,
)
from modules.elm.domain.policy import (
    LeaveInterval,
    available_balance,
    count_days,
    intervals_overlap,
    vl_to_el_conversion,
    year_end_outcome,
)

# 2026: Mar 2 is a Monday; Mar 5 Thu; Mar 7 Sat; Mar 8 Sun; Mar 9 Mon.
CLOSED = frozenset({date(2026, 3, 5)})
RHS = frozenset({date(2026, 3, 9)})


def days(category, start, end, *, start_half="full", end_half="full",
         closed=CLOSED, rhs=RHS):
    return count_days(
        LeaveInterval(category=category, start=start, end=end,
                      start_half=start_half, end_half=end_half),
        closed=closed, restricted_holidays=rhs)


# -- counting (PS §4, BR-EL-010/011) -------------------------------------

class TestCounting:

    def test_continuous_categories_count_every_calendar_day(self):
        # EL Mon→Fri over a closed holiday: all five days count.
        assert days("EL", date(2026, 3, 2), date(2026, 3, 6)) == D("5")
        # COL spans the weekend: Sat and Sun are leave days too.
        assert days("COL", date(2026, 3, 6), date(2026, 3, 9)) == D("4")

    def test_non_continuous_categories_skip_weekends_and_closed_days(self):
        # CL Mon→Fri over a closed Thursday: four days.
        assert days("CL", date(2026, 3, 2), date(2026, 3, 6)) == D("4")
        # SCL Mon→Mon over a weekend: one day.
        assert days("SCL", date(2026, 3, 6), date(2026, 3, 9)) == D("2")

    def test_single_day_counts_one(self):
        assert days("CL", date(2026, 3, 2), date(2026, 3, 2)) == D("1")

    def test_half_days_consume_half_a_cl_day(self):
        assert days("CL", date(2026, 3, 2), date(2026, 3, 2),
                    start_half="first") == D("0.5")
        assert days("CL", date(2026, 3, 2), date(2026, 3, 2),
                    end_half="second") == D("0.5")
        # First + second half of the same day is a full day.
        assert days("CL", date(2026, 3, 2), date(2026, 3, 2),
                    start_half="first", end_half="second") == D("1")

    def test_half_day_on_a_multi_day_request_shaves_half(self):
        assert days("CL", date(2026, 3, 2), date(2026, 3, 6),
                    start_half="first") == D("3.5")

    def test_reversed_interval_counts_nothing(self):
        assert days("CL", date(2026, 3, 6), date(2026, 3, 2)) == D("0")

    def test_closed_day_still_counts_for_el_but_not_cl(self):
        # The closed holiday inside a CL span is skipped…
        assert days("CL", date(2026, 3, 5), date(2026, 3, 5)) == D("0")
        # …and inside an EL span it is a leave day.
        assert days("EL", date(2026, 3, 5), date(2026, 3, 5)) == D("1")

    def test_rh_date_counts_for_a_restricted_holiday_request(self):
        assert days("RH", date(2026, 3, 9), date(2026, 3, 9)) == D("1")
        # …and is not treated as a closed day for a CL that spans it.
        assert days("CL", date(2026, 3, 9), date(2026, 3, 9)) == D("1")


# -- overlap (BR-EL-012) ---------------------------------------------------

class TestOverlap:

    def test_disjoint_intervals_do_not_overlap(self):
        a = LeaveInterval("CL", date(2026, 3, 2), date(2026, 3, 4))
        b = LeaveInterval("CL", date(2026, 3, 6), date(2026, 3, 9))
        assert not intervals_overlap(a, b)
        assert not intervals_overlap(b, a)

    def test_touching_intervals_do_not_overlap(self):
        a = LeaveInterval("CL", date(2026, 3, 2), date(2026, 3, 6))
        b = LeaveInterval("CL", date(2026, 3, 9), date(2026, 3, 10))
        assert not intervals_overlap(a, b)

    def test_nested_and_partial_overlaps_collide(self):
        week = LeaveInterval("CL", date(2026, 3, 2), date(2026, 3, 6))
        inside = LeaveInterval("CL", date(2026, 3, 4), date(2026, 3, 5))
        assert intervals_overlap(week, inside)

    def test_first_and_second_half_cl_on_the_same_day_do_not_overlap(self):
        first = LeaveInterval("CL", date(2026, 3, 2), date(2026, 3, 2),
                              start_half="first")
        second = LeaveInterval("CL", date(2026, 3, 2), date(2026, 3, 2),
                               end_half="second")
        assert not intervals_overlap(first, second)
        assert not intervals_overlap(second, first)

    def test_same_half_cl_on_the_same_day_overlaps(self):
        a = LeaveInterval("CL", date(2026, 3, 2), date(2026, 3, 2),
                          start_half="first")
        b = LeaveInterval("CL", date(2026, 3, 2), date(2026, 3, 2),
                          start_half="first")
        assert intervals_overlap(a, b)

    def test_half_day_exception_is_cl_only(self):
        first = LeaveInterval("EL", date(2026, 3, 2), date(2026, 3, 2),
                              start_half="first")
        second = LeaveInterval("EL", date(2026, 3, 2), date(2026, 3, 2),
                               end_half="second")
        assert intervals_overlap(first, second)


# -- balance maths (BR-EL-001/005) ------------------------------------------

class TestBalanceMaths:

    def test_available_is_opening_plus_entitled_minus_used_minus_pending(self):
        assert available_balance(D("5"), D("30"), D("10"), D("2")) == D("23")

    def test_pending_reservation_prevents_double_booking(self):
        assert available_balance(D("0"), D("8"), D("0"), D("8")) == D("0")


class TestVlConversion:

    def test_two_vl_days_convert_to_one_el_day(self):
        assert vl_to_el_conversion(D("40")) == D("20.00")

    def test_fractional_part_is_preserved(self):
        assert vl_to_el_conversion(D("61")) == D("30.50")

    def test_odd_remainder_keeps_half(self):
        assert vl_to_el_conversion(D("1")) == D("0.50")

    def test_nothing_converts_from_zero_or_negative(self):
        assert vl_to_el_conversion(D("0")) == D("0")
        assert vl_to_el_conversion(D("-5")) == D("0")


class TestYearEndOutcome:

    def test_cl_rh_scl_lapse(self):
        for category in ("CL", "RH", "SCL"):
            assert year_end_outcome(category, "staff", D("3")) == "lapse"
            assert year_end_outcome(category, "faculty", D("3")) == "lapse"

    def test_faculty_vl_converts(self):
        assert year_end_outcome("VL", "faculty", D("40")) == "convert"

    def test_staff_vl_lapses(self):
        assert year_end_outcome("VL", "staff", D("40")) == "lapse"

    def test_el_and_col_carry_forward(self):
        assert year_end_outcome("EL", "staff", D("10")) == "carry_forward"
        assert year_end_outcome("COL", "faculty", D("10")) == "carry_forward"


# -- leave-year derivation (PS §3) -------------------------------------------

class TestLeaveYear:

    def test_year_runs_to_the_boundary(self):
        from modules.elm.services import policy as policy_service

        # The boundary day itself still belongs to the closing year.
        assert policy_service.leave_year_for(
            date(2026, 3, 31), "03-31") == "2025-26"
        # The day after the boundary opens the new year.
        assert policy_service.leave_year_for(
            date(2026, 4, 1), "03-31") == "2026-27"

    def test_custom_boundary(self):
        from modules.elm.services import policy as policy_service

        # A 12-31 boundary makes the leave year the calendar
        # year, labelled with the year it starts in.
        assert policy_service.leave_year_for(
            date(2026, 1, 10), "12-31") == "2026-27"
        assert policy_service.leave_year_for(
            date(2026, 1, 1), "12-31") == "2026-27"
        # The boundary day itself still closes the year.
        assert policy_service.leave_year_for(
            date(2026, 12, 31), "12-31") == "2026-27"
        assert policy_service.leave_year_for(
            date(2027, 1, 1), "12-31") == "2027-28"

    def test_next_leave_year(self):
        from modules.elm.services import policy as policy_service

        assert policy_service.next_leave_year("2025-26") == "2026-27"

# -- routing resolution (PS §7, BR-EL-016…020) --------------------------------

def ctx(designation="Assistant Professor", kind="staff",
        unit_code="cse", user_id=1):
    return routing_domain.ApplicantContext(
        user_id=user_id, employee_kind=kind,
        designation_name=designation, unit_code=unit_code)


class TestRouteResolution:

    def test_cl_rh_ends_at_the_unit_head(self):
        route = routing_domain.resolve_route(ctx(), "CL", _hierarchy())
        assert [(s.role, s.decision) for s in route.steps] == [
            ("unit_head", "final")]
        assert not route.director_path

    def test_higher_sanction_recommends_then_final_authority(self):
        route = routing_domain.resolve_route(ctx(), "EL", _hierarchy())
        assert [(s.role, s.decision) for s in route.steps] == [
            ("unit_head", "recommendation"),
            ("sanctioning_authority", "final")]

    def test_establishment_step_only_where_configured(self):
        hierarchy = _hierarchy(establishment_required=True)
        route = routing_domain.resolve_route(ctx(), "EL", hierarchy)
        assert [s.role for s in route.steps] == [
            "unit_head", "establishment", "sanctioning_authority"]

    def test_director_self_sanction_replaces_the_whole_route(self):
        route = routing_domain.resolve_route(ctx(designation="Director"),
                                             "CL", _hierarchy())
        assert route.director_path
        assert [(s.role, s.decision) for s in route.steps] == [
            ("director_self_sanction", "final")]

    def test_unknown_category_takes_the_safe_higher_sanction_path(self):
        route = routing_domain.resolve_route(ctx(), "XX", _hierarchy())
        assert [s.role for s in route.steps] == [
            "unit_head", "sanctioning_authority"]

    def test_task_classes_follow_the_route(self):
        route = routing_domain.resolve_route(ctx(), "EL", _hierarchy())
        assert routing_domain.route_task_classes(route) == (
            "unit_head_review", "final_sanction")


def _hierarchy(establishment_required=False):
    return routing_domain.HierarchyProfile(
        establishment_required=establishment_required,
        establishment_designations=("Deputy Registrar (Estt.)",),
        sanctioning_authority="Dean",
    )


# -- the state machine (WF v1.6 STTs) ---------------------------------------

def tx(kind, frm, actor, guard):
    return machine.transition(kind, frm, actor, guard)


class TestStateTable:

    def test_every_pending_state_can_withdraw(self):
        """BR-EL-022: withdrawal is cross-cutting — every pending
        pre-final state of every kind has a withdrawal row."""
        for kind, states in STATES_BY_KIND.items():
            for state in states:
                if state in TERMINAL_STATES:
                    continue
                row = machine.transition(kind, state, "employee",
                                         "withdraw_before_final")
                assert row.to == WITHDRAWN

    def test_pending_states_agree_with_the_table(self):
        for state in PENDING_STATES:
            assert state not in TERMINAL_STATES

    def test_cl_rh_unit_head_rows_are_final(self):
        for kind, frm in [(KIND_NEW, AWAITING_UNIT_HEAD_REVIEW),
                          (KIND_CANCELLATION,
                           CANCELLATION_PENDING_UNIT_HEAD)]:
            assert tx(kind, frm, "unit_head", "cl_rh_final_approve").to \
                == APPROVED
            assert tx(kind, frm, "unit_head", "cl_rh_final_reject").to \
                == REJECTED

    def test_higher_sanction_has_rows_with_and_without_establishment(self):
        for kind, frm in [
            (KIND_NEW, AWAITING_UNIT_HEAD_REVIEW),
            (KIND_CANCELLATION, CANCELLATION_PENDING_UNIT_HEAD),
            (KIND_EXTENSION, AWAITING_EXTENSION_UNIT_HEAD),
        ]:
            assert tx(kind, frm, "unit_head",
                      "higher_recommend_establishment").to in (
                AWAITING_ESTABLISHMENT_ROUTING,
                CANCELLATION_PENDING_ESTABLISHMENT,
                EXTENSION_PENDING_ESTABLISHMENT)
            assert tx(kind, frm, "unit_head",
                      "higher_recommend_no_establishment").to in (
                AWAITING_FINAL_SANCTION_DECISION,
                CANCELLATION_PENDING_FINAL,
                EXTENSION_PENDING_FINAL)

    def test_final_rows_exist_for_every_final_state(self):
        for kind, frm in [
            (KIND_NEW, AWAITING_FINAL_SANCTION_DECISION),
            (KIND_NEW, AWAITING_DIRECTOR_SELF_SANCTION),
            (KIND_CANCELLATION, CANCELLATION_PENDING_FINAL),
            (KIND_EXTENSION, EXTENSION_PENDING_FINAL),
        ]:
            assert tx(kind, frm, "sanctioning_authority",
                      "sanction_approve").to == APPROVED
            assert tx(kind, frm, "sanctioning_authority",
                      "sanction_reject").to == REJECTED

    def test_director_rows_are_new_application_only(self):
        # The director guards belong to the Director's own *application*.
        assert tx(KIND_NEW, AWAITING_DIRECTOR_SELF_SANCTION,
                  "sanctioning_authority",
                  "director_self_sanction_approve").to == APPROVED
        # A derived request on the director route never carries them —
        # it goes through the plain sanction rows at its final state.
        with pytest.raises(InvalidTransition):
            machine.transition(KIND_CANCELLATION,
                               CANCELLATION_PENDING_FINAL,
                               "sanctioning_authority",
                               "director_self_sanction_approve")

    def test_establishment_routes_and_never_decides(self):
        for kind, frm in [
            (KIND_NEW, AWAITING_ESTABLISHMENT_ROUTING),
            (KIND_CANCELLATION, CANCELLATION_PENDING_ESTABLISHMENT),
            (KIND_EXTENSION, EXTENSION_PENDING_ESTABLISHMENT),
        ]:
            row = tx(kind, frm, "establishment",
                     "establishment_routing_valid")
            assert row.to in (AWAITING_FINAL_SANCTION_DECISION,
                              CANCELLATION_PENDING_FINAL,
                              EXTENSION_PENDING_FINAL)

    def test_substitute_gate_rows(self):
        assert tx(KIND_NEW, AWAITING_SUBSTITUTE_RESPONSE, "substitute",
                  "substitute_accepted_not_director").to \
            == AWAITING_UNIT_HEAD_REVIEW
        assert tx(KIND_NEW, AWAITING_SUBSTITUTE_RESPONSE, "substitute",
                  "substitute_accepted_director").to \
            == AWAITING_DIRECTOR_SELF_SANCTION
        assert tx(KIND_NEW, AWAITING_SUBSTITUTE_RESPONSE, "substitute",
                  "substitute_declined").to == APPLICANT_ACTION_REQUIRED
        assert tx(KIND_EXTENSION, AWAITING_EXTENSION_SUBSTITUTE,
                  "substitute", "substitute_accepted").to \
            == AWAITING_EXTENSION_UNIT_HEAD

    def test_recovery_after_decline(self):
        assert tx(KIND_NEW, APPLICANT_ACTION_REQUIRED, "employee",
                  "replacement_nominated").to == AWAITING_SUBSTITUTE_RESPONSE
        assert tx(KIND_EXTENSION, EXTENSION_APPLICANT_ACTION_REQUIRED,
                  "employee", "replacement_nominated").to \
            == AWAITING_EXTENSION_SUBSTITUTE

    def test_an_unknown_move_raises(self):
        with pytest.raises(InvalidTransition):
            machine.transition(KIND_NEW, APPROVED, "employee",
                               "withdraw_before_final")
        with pytest.raises(InvalidTransition):
            machine.transition(KIND_NEW, DRAFT, "unit_head",
                               "cl_rh_final_approve")

    def test_initial_states(self):
        assert machine.initial_state(KIND_NEW) == DRAFT
        assert machine.initial_state(KIND_CANCELLATION) \
            == CANCELLATION_PENDING_UNIT_HEAD
        assert machine.initial_state(
            KIND_EXTENSION, substitute_required=True) \
            == AWAITING_EXTENSION_SUBSTITUTE
        assert machine.initial_state(KIND_EXTENSION) \
            == AWAITING_EXTENSION_UNIT_HEAD

    def test_director_path_derived_requests_start_at_their_final_state(self):
        """A Director's cancellation/extension self-sanctions too: it is
        born at the final state of its kind, with no Unit Head stop."""
        assert machine.initial_state(KIND_CANCELLATION, director_path=True) \
            == CANCELLATION_PENDING_FINAL
        assert machine.initial_state(KIND_EXTENSION, director_path=True) \
            == EXTENSION_PENDING_FINAL
