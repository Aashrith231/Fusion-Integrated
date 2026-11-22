"""Every legal and illegal transition, enumerated from the tables.

The state machines (CW-BA-01, CW-BA-02, CW-BA-03) are declarative tables in
`domain/states.py`; these tests walk them entry by entry, with no database.
Illegal pairs must be inexpressible (raise), not silently pass through.
"""
import datetime as dt

import pytest

from modules.badms.domain import policy, rules, states

# --- archival (CW-BA-01) ---------------------------------------------------

def test_archival_happy_path_is_enumerated():
    assert states.archival_transition("submitted", "approve") == "hod_approved"
    assert states.archival_transition("hod_approved", "classify") == "classified"
    assert states.archival_transition("hod_approved",
                                      "classify_sensitive") == "routed_to_security"
    assert states.archival_transition("routed_to_security",
                                      "encrypt") == "encrypted"
    assert states.archival_transition("routed_to_security",
                                      "encrypt_failed") == "encryption_failed"
    assert states.archival_transition("encryption_failed",
                                      "encrypt") == "encrypted"


def test_archival_rejection_only_from_submitted():
    assert states.archival_transition("submitted", "reject") == "rejected"


@pytest.mark.parametrize("from_state,outcome", [
    ("submitted", "classify"),            # not approved yet
    ("submitted", "encrypt"),             # not routed to security
    ("hod_approved", "approve"),          # already approved
    ("hod_approved", "reject"),           # spec: rejection ends the flow
    ("classified", "encrypt"),            # encryption follows Sensitive only
    ("rejected", "approve"),
    ("encrypted", "classify"),
])
def test_archival_illegal_pairs_raise(from_state, outcome):
    with pytest.raises(ValueError):
        states.archival_transition(from_state, outcome)


# --- storage extension (CW-BA-02) ------------------------------------------

def test_extension_transitions_are_enumerated():
    assert states.extension_transition("submitted", "approve") == "approved"
    assert states.extension_transition("submitted", "reject") == "rejected"


@pytest.mark.parametrize("from_state,outcome", [
    ("submitted", "classify"), ("approved", "approve"),
    ("rejected", "approve"), ("approved", "reject"),
])
def test_extension_illegal_pairs_raise(from_state, outcome):
    with pytest.raises(ValueError):
        states.extension_transition(from_state, outcome)


# --- restoration (CW-BA-03) -------------------------------------------------

def test_restoration_transitions_are_enumerated():
    assert states.restoration_transition(
        "pending_approval", "approve") == "approved_for_restoration"
    assert states.restoration_transition(
        "pending_approval", "reject") == "rejected"
    assert states.restoration_transition(
        "requested", "execute") == "restored"
    assert states.restoration_transition(
        "approved_for_restoration", "execute") == "restored"
    assert states.restoration_transition(
        "requested", "execute_failed") == "failed"
    assert states.restoration_transition(
        "approved_for_restoration", "execute_failed") == "failed"


@pytest.mark.parametrize("from_state,outcome", [
    ("requested", "approve"),           # non-Sensitive never waits for approval
    ("pending_approval", "execute"),    # approval comes first
    ("restored", "execute"),
    ("failed", "approve"),
    ("rejected", "execute"),
])
def test_restoration_illegal_pairs_raise(from_state, outcome):
    with pytest.raises(ValueError):
        states.restoration_transition(from_state, outcome)


# --- classification policy (BR-BA-006, BR-BA-008) ---------------------------

def test_the_initial_classification_defaults_to_routine():
    assert policy.effective_initial_classification(None) == "routine"
    assert policy.effective_initial_classification("") == "routine"
    assert policy.effective_initial_classification("  SENSITIVE ") == "sensitive"


def test_an_unknown_initial_classification_is_refused():
    with pytest.raises(ValueError):
        policy.effective_initial_classification("top-secret")


def test_every_classification_has_a_retention_rule():
    for name in policy.CLASSIFICATIONS:
        assert policy.retention_rule_for(name)
    with pytest.raises(ValueError):
        policy.retention_rule_for("top-secret")


# --- schedule rules (BR-BA-011, BR-BA-012) ----------------------------------

def _sched(**over):
    base = {"dataset": "db1", "scope": "local", "frequency": "daily",
            "run_at": dt.time(2, 0), "weekday": None, "pk": 1,
            "is_active": True}
    base.update(over)
    return type("S", (), base)


def test_parameter_validation_rejects_each_bad_parameter():
    with pytest.raises(rules.ScheduleInvalid):
        rules.validate_parameters(frequency="hourly", run_at=dt.time(2, 0),
                                  classification_filter=None)
    with pytest.raises(rules.ScheduleInvalid):
        rules.validate_parameters(frequency="daily", run_at="02:00",
                                  classification_filter=None)
    with pytest.raises(rules.ScheduleInvalid):       # weekly needs a weekday
        rules.validate_parameters(frequency="weekly", run_at=dt.time(2, 0),
                                  classification_filter=None)
    with pytest.raises(rules.ScheduleInvalid):       # daily takes no weekday
        rules.validate_parameters(frequency="daily", run_at=dt.time(2, 0),
                                  classification_filter=None, weekday=0)
    with pytest.raises(rules.ScheduleInvalid):
        rules.validate_parameters(frequency="daily", run_at=dt.time(2, 0),
                                  classification_filter=["top-secret"])


def test_parameter_validation_accepts_a_real_schedule():
    rules.validate_parameters(frequency="weekly", run_at=dt.time(2, 0),
                              classification_filter=["routine"], weekday=0)


def test_dataset_rules():
    assert rules.validate_dataset("", scope="global") == ""
    assert rules.validate_dataset(" db1 ", scope="local") == "db1"
    with pytest.raises(rules.ScheduleInvalid):
        rules.validate_dataset("", scope="local")
    with pytest.raises(rules.ScheduleInvalid):
        rules.validate_dataset("d" * 81, scope="local")


def test_identical_timing_conflicts():
    other = _sched()
    reason = rules.conflicts([other], scope="local", dataset="db1",
                             frequency="daily", run_at=dt.time(2, 0),
                             weekday=None)
    assert reason and "already covers" in reason


def test_a_near_timing_conflict_inside_the_hour():
    other = _sched(run_at=dt.time(2, 30))
    reason = rules.conflicts([other], scope="local", dataset="db1",
                             frequency="daily", run_at=dt.time(2, 0),
                             weekday=None)
    assert reason and "Conflicts with" in reason


def test_different_datasets_and_far_timings_do_not_conflict():
    assert rules.conflicts([_sched(dataset="other")], scope="local",
                           dataset="db1", frequency="daily",
                           run_at=dt.time(2, 0), weekday=None) is None
    assert rules.conflicts([_sched(run_at=dt.time(4, 0))], scope="local",
                           dataset="db1", frequency="daily",
                           run_at=dt.time(2, 0), weekday=None) is None


def test_weekly_schedules_on_different_days_do_not_conflict():
    assert rules.conflicts([_sched(frequency="weekly", weekday=0)],
                           scope="local", dataset="db1", frequency="weekly",
                           run_at=dt.time(2, 0), weekday=2) is None
    assert rules.conflicts([_sched(frequency="weekly", weekday=0)],
                           scope="local", dataset="db1", frequency="weekly",
                           run_at=dt.time(2, 30), weekday=0) is not None


def test_exclude_pk_skips_the_schedule_being_modified():
    other = _sched(pk=7)
    assert rules.conflicts([other], scope="local", dataset="db1",
                           frequency="daily", run_at=dt.time(2, 0),
                           weekday=None, exclude_pk=7) is None


def test_is_due_for_each_frequency(monkeypatch):
    now = dt.datetime(2026, 11, 23, 3, 0)          # a Monday
    daily = _sched(frequency="daily", run_at=dt.time(2, 0))
    assert rules.is_due(daily, now=now, last_success_for_dataset=None)
    # a success after last midnight pushes it out
    assert not rules.is_due(
        daily, now=now,
        last_success_for_dataset=now.replace(hour=2, minute=30))
    # a success before the boundary does not
    assert rules.is_due(
        daily, now=now,
        last_success_for_dataset=dt.datetime(2026, 11, 22, 23, 0))

    weekly = _sched(frequency="weekly", weekday=0)
    assert rules.is_due(weekly, now=now, last_success_for_dataset=None)
    assert not rules.is_due(_sched(frequency="weekly", weekday=1),
                            now=now, last_success_for_dataset=None)

    monthly = _sched(frequency="monthly")
    assert not rules.is_due(monthly, now=now, last_success_for_dataset=None)
    first = now.replace(day=1)
    assert rules.is_due(monthly, now=first, last_success_for_dataset=None)

    assert not rules.is_due(_sched(is_active=False), now=now,
                            last_success_for_dataset=None)
    assert not rules.is_due(_sched(run_at=dt.time(23, 0)), now=now,
                            last_success_for_dataset=None)
