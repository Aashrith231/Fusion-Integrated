"""Year-end leave processing (EL-UC-020): lapse, conversion,
carry-forward, the ledger, and the exceptions report."""
from decimal import Decimal as D

import pytest

from core.api.exceptions import ConflictError

from .support import (
    APP,
    COLLEAGUE,
    FACULTY,
    admin,
    principal,
)

pytestmark = pytest.mark.django_db

# The world fixture pre-creates the *current* leave year's
# accounts ("2025-26", derived from the frozen clock), so the
# year-end tests seed the previous year and let the run open
# "2025-26" — which the service get_or_creates harmlessly.
YEAR = "2024-25"
NEXT = "2025-26"


def seed_account(user_id, category, *, opening=D("0"), entitled, used=D("0")):
    from modules.elm.models import LeaveAccount

    return LeaveAccount.objects.create(
        user_id=user_id, leave_year=YEAR, category=category,
        opening_days=opening, entitled_days=entitled, used_days=used)


def run(principal_=None, leave_year=YEAR):
    from modules.elm.services import year_end as year_end_service

    return year_end_service.run_year_end(
        principal_ or admin(), leave_year=leave_year)


class TestYearEndRun:

    def test_cl_rh_scl_lapse(self, world):
        seed_account(APP, "CL", entitled=D("8"), used=D("3"))
        seed_account(APP, "RH", entitled=D("2"))
        seed_account(APP, "SCL", entitled=D("15"), used=D("1"))
        run()
        from modules.elm.models import LeaveTransaction

        lapsed = LeaveTransaction.objects.filter(
            kind="year_end_lapse", account__user_id=APP)
        assert {t.account.category for t in lapsed} == {"CL", "RH", "SCL"}
        cl = next(t for t in lapsed
                  if t.account.category == "CL")
        assert cl.delta == D("-5")              # 8 entitled - 3 used

        # The closing accounts read zero, the new year starts fresh.
        from modules.elm.models import LeaveAccount

        assert LeaveAccount.objects.get(
            user_id=APP, category="CL", leave_year=NEXT).entitled_days \
            == D("8")
        assert LeaveAccount.objects.get(
            user_id=APP, category="CL", leave_year=YEAR).used_days == D("3")

    def test_faculty_vl_converts_to_el_two_to_one(self, world):
        seed_account(FACULTY, "VL", entitled=D("60"), used=D("21"))
        seed_account(FACULTY, "EL", entitled=D("0"))
        run()
        from modules.elm.models import LeaveAccount, LeaveTransaction

        # 39 unused VL → 19.5 EL, fractional part preserved.
        el = LeaveAccount.objects.get(
            user_id=FACULTY, category="EL", leave_year=NEXT)
        assert el.opening_days == D("19.50")
        credit = LeaveTransaction.objects.get(
            kind="vl_conversion", account=el)
        assert credit.delta == D("19.50")
        # VL itself does not carry forward.
        vl = LeaveAccount.objects.get(
            user_id=FACULTY, category="VL", leave_year=NEXT)
        assert vl.opening_days == D("0") and vl.entitled_days == D("60")

    def test_el_and_col_carry_forward(self, world):
        seed_account(APP, "EL", entitled=D("30"), used=D("10"))
        seed_account(APP, "COL", entitled=D("20"), used=D("18"))
        run()
        from modules.elm.models import LeaveAccount, LeaveTransaction

        el = LeaveAccount.objects.get(
            user_id=APP, category="EL", leave_year=NEXT)
        assert el.opening_days == D("20")
        assert el.entitled_days == D("30")      # fresh entitlement on top
        carried = LeaveTransaction.objects.filter(
            kind="year_end_carry_forward", account=el)
        assert [t.delta for t in carried] == [D("20")]
        col = LeaveAccount.objects.get(
            user_id=APP, category="COL", leave_year=NEXT)
        assert col.opening_days == D("2")

    def test_every_movement_is_on_the_ledger(self, world):
        seed_account(APP, "CL", entitled=D("8"))
        seed_account(APP, "EL", entitled=D("30"), used=D("5"))
        seed_account(FACULTY, "VL", entitled=D("60"))
        run()
        from modules.elm.models import LeaveTransaction

        kinds = set(LeaveTransaction.objects.values_list("kind",
                                                         flat=True))
        assert {"year_end_lapse", "year_end_carry_forward",
                "vl_conversion"} <= kinds

    def test_run_records_stats_and_is_once_per_year(self, world):
        from modules.elm.models import YearEndRun

        seed_account(APP, "CL", entitled=D("8"), used=D("2"))
        report = run()
        assert report.stats["lapsed"] == 1
        assert report.stats["accounts"] == 1
        assert report.leave_year == YEAR
        assert YearEndRun.objects.filter(leave_year=YEAR).exists()
        with pytest.raises(ConflictError) as err:
            run()
        assert err.value.code == "already_processed"

    def test_permission_is_required(self, world):
        from core.api.exceptions import PermissionDeniedError

        with pytest.raises(PermissionDeniedError):
            run(principal(999, permissions=("elm.leave.view_self",)))

    def test_a_broken_account_is_reported_not_fatal(self, world):
        """AFR-EL-028.5: processing exceptions are reported; one bad
        account must not abort the batch."""
        seed_account(APP, "CL", entitled=D("8"), used=D("10"))   # negative!
        seed_account(COLLEAGUE, "CL", entitled=D("8"))
        report = run()
        assert len(report.exceptions) == 1
        assert report.exceptions[0]["user_id"] == APP
        assert report.exceptions[0]["category"] == "CL"
        # The healthy account was still processed.
        from modules.elm.models import LeaveTransaction

        assert LeaveTransaction.objects.filter(
            kind="year_end_lapse",
            account__user_id=COLLEAGUE).exists()
