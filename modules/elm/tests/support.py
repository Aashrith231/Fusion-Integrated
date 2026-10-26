"""Shared ELM test world.

Builds the organizational cast, the published calendar, the vacation
window and the leave accounts once per test, plus principals for every
seat. Dates are anchored on March 2026 and time is frozen so the
workflow's ``timezone.now()`` calls are deterministic:

* frozen "today" is 2026-03-02 (a Monday);
* 2026-03-05 (Thu) is a closed holiday;
* 2026-03-09 (Mon) is a Restricted Holiday (office open);
* 2026-05-18 → 2026-05-29 is a vacation period (for VL).
"""
from __future__ import annotations

from datetime import date

import pytest
from django.utils import timezone
from freezegun import freeze_time

from conftest import make_principal
from fusion_auth.client import UserRef
from modules.elm.models import (
    EmployeeProfile,
    HierarchyConfig,
    Holiday,
    HolidayCalendar,
    LeaveAccount,
    OrgUnit,
    VacationPeriod,
)
from modules.elm.services import policy as policy_service

# -- the cast ----------------------------------------------------------------
APP = 101          # the applicant: staff, cse department
COLLEAGUE = 102    # second cse employee — the substitute nominee
FACULTY = 103      # faculty member — VL applicant
HEAD = 202         # Unit Head of cse
EST = 301          # Deputy Registrar (Estt.) — Establishment processing
EST2 = 302         # a second Establishment holder — multi-holder office
DEAN = 401         # Dean — the final sanctioning authority
DIRECTOR = 501     # Director — self-sanctions their own leave
ADMIN = 601        # Leave Administrator

EMPLOYEE_PERMS = (
    "elm.leave.apply", "elm.leave.view_self", "elm.leave.withdraw",
    "elm.leave.nominate", "elm.substitute.respond", "elm.leave.cancel",
    "elm.leave.extend", "elm.leave.resume",
)

TODAY = date(2026, 3, 2)

USERS = {
    APP: UserRef(user_id=APP, username="emp101", display_name="Applicant One",
                 kind="staff"),
    COLLEAGUE: UserRef(user_id=COLLEAGUE, username="emp102",
                       display_name="Colleague Two", kind="staff"),
    FACULTY: UserRef(user_id=FACULTY, username="fac103",
                     display_name="Faculty Three", kind="faculty"),
    HEAD: UserRef(user_id=HEAD, username="emp202", display_name="Head of cse",
                  kind="staff"),
    EST: UserRef(user_id=EST, username="emp301", display_name="Deputy Registrar",
                 kind="staff"),
    EST2: UserRef(user_id=EST2, username="emp302", display_name="Second Deputy",
                  kind="staff"),
    DEAN: UserRef(user_id=DEAN, username="emp401", display_name="The Dean",
                  kind="faculty"),
    DIRECTOR: UserRef(user_id=DIRECTOR, username="emp501",
                      display_name="The Director", kind="faculty"),
    ADMIN: UserRef(user_id=ADMIN, username="emp601",
                   display_name="Leave Administrator", kind="staff"),
}


def principal(user_id, permissions=EMPLOYEE_PERMS, kind="staff", **kw):
    return make_principal(user_id=user_id, kind=kind,
                          permissions=permissions, modules=("elm",), **kw)


def applicant(**kw):
    return principal(APP, **kw)


def head(**kw):
    return principal(HEAD, permissions=("elm.review.unit_head",
                                        "elm.records.view"), **kw)


def establishment(**kw):
    return principal(EST, permissions=("elm.review.establishment",), **kw)


def dean(**kw):
    return principal(DEAN, permissions=("elm.sanction.final",
                                        "elm.resume.review"), **kw)


def director(**kw):
    return principal(DIRECTOR, permissions=("elm.sanction.final",
                                            *EMPLOYEE_PERMS),
                     kind="faculty", **kw)


def admin(**kw):
    return principal(ADMIN, permissions=(
        "elm.records.view", "elm.records.offline", "elm.records.maintain",
        "elm.config.policy", "elm.config.hierarchy", "elm.config.calendar",
        "elm.config.units", "elm.config.vacation", "elm.config.sla",
        "elm.yearend.run"), **kw)


# -- the world ----------------------------------------------------------------

CLOSED_HOLIDAY = date(2026, 3, 5)          # Thursday, institute closed
RESTRICTED_HOLIDAY = date(2026, 3, 9)      # Monday, RH — office open
VACATION = (date(2026, 5, 18), date(2026, 5, 29))


@pytest.fixture
def world(db, _frozen_clock):
    """The organizational cast, a published calendar with one closed
    holiday and one RH, the vacation window, and this year's leave
    accounts for the two employees."""
    unit = OrgUnit.objects.create(code="cse", name="Computer Science",
                                  unit_type="department", head_user_id=HEAD)
    office = OrgUnit.objects.create(code="registrar-office",
                                    name="Registrar's Office",
                                    unit_type="office", head_user_id=None)
    for user_id, kind, designation, u in [
        (APP, "staff", "Assistant Professor", unit),
        (COLLEAGUE, "staff", "Assistant Professor", unit),
        (FACULTY, "faculty", "Professor", unit),
        (HEAD, "staff", "Associate Professor", unit),
        (EST, "staff", "Deputy Registrar (Estt.)", None),
        (EST2, "staff", "Deputy Registrar (Estt.)", None),
        (DEAN, "faculty", "Dean", None),
        (DIRECTOR, "faculty", "Director", None),
        (ADMIN, "staff", "Leave Administrator", None),
    ]:
        EmployeeProfile.objects.create(
            user_id=user_id, employee_kind=kind,
            designation_name=designation, unit_code=u, is_active=True)

    for group, est_required in [("cl_rh", False),
                                ("higher_sanction", True)]:
        HierarchyConfig.objects.create(
            category_group=group, unit_type="department",
            establishment_required=est_required,
            sanctioning_authority="Dean")

    calendar = HolidayCalendar.objects.create(name="Test Calendar", year=2026)
    Holiday.objects.create(calendar=calendar, date=CLOSED_HOLIDAY,
                           label="Closed holiday", kind="holiday", closed=True)
    Holiday.objects.create(calendar=calendar, date=RESTRICTED_HOLIDAY,
                           label="Restricted holiday",
                           kind="restricted_holiday", closed=False)
    calendar.published_at = timezone.now()
    calendar.save(update_fields=["published_at"])

    leave_year = policy_service.leave_year_for(TODAY)

    VacationPeriod.objects.create(label="Winter Vacation",
                                  start_date=VACATION[0],
                                  end_date=VACATION[1],
                                  academic_year="2025-26")

    for user_id, kind in [(APP, "staff"), (COLLEAGUE, "staff"),
                          (FACULTY, "faculty")]:
        for category in ("CL", "RH", "SCL", "EL", "COL", "VL"):
            LeaveAccount.objects.create(
                user_id=user_id, leave_year=leave_year, category=category,
                entitled_days=policy_service.entitlement_for(
                    category, kind))

    return {"unit": unit, "office": office, "leave_year": leave_year}


@pytest.fixture(autouse=True)
def _frozen_clock():
    """Pin the clock for every ELM test: 'today' is 2026-03-02."""
    with freeze_time("2026-03-02 10:00:00"):
        yield
