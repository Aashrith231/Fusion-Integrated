"""Schedule rules: parameter validation, conflict detection and the
local-over-global precedence (BR-BA-011, BR-BA-012).

Pure functions: they take plain values and return verdicts or raise
`ScheduleInvalid`, which services translate into a domain error.
"""
from __future__ import annotations

import datetime as dt

FREQUENCIES = ("daily", "weekly", "monthly")


class ScheduleInvalid(ValueError):
    """A schedule configuration fails parameter or conflict validation."""


def validate_parameters(*, frequency: str, run_at: dt.time,
                        classification_filter: list[str] | None,
                        weekday: int | None = None) -> None:
    """A schedule must carry a known frequency, a time of day, and — for
    weekly schedules — a weekday. Filters may only name real classifications."""
    if frequency not in FREQUENCIES:
        raise ScheduleInvalid(f"Unknown backup frequency {frequency!r}.")
    if not isinstance(run_at, dt.time):
        raise ScheduleInvalid("A schedule needs a time of day.")
    if frequency == "weekly" and weekday is None:
        raise ScheduleInvalid("A weekly schedule needs a weekday (0=Monday).")
    if frequency != "weekly" and weekday is not None:
        raise ScheduleInvalid("Only weekly schedules take a weekday.")
    for name in classification_filter or []:
        if name not in ("critical", "sensitive", "routine", "archival"):
            raise ScheduleInvalid(f"Unknown classification filter {name!r}.")


def validate_dataset(dataset: str, *, scope: str) -> str:
    dataset = (dataset or "").strip()
    if scope == "global":
        return ""
    if not dataset:
        raise ScheduleInvalid("A local schedule names the dataset it backs up.")
    if len(dataset) > 80:
        raise ScheduleInvalid("Dataset names are at most 80 characters.")
    return dataset


def conflicts(existing_schedules, *, scope: str, dataset: str,
              frequency: str, run_at: dt.time, weekday: int | None,
              exclude_pk: int | None = None) -> str | None:
    """Return the reason a candidate schedule conflicts, or None.

    Two active schedules for the same target are a conflict when they are
    due near each other: identical timing is redundant, and different
    timings inside an hour of each other run the second against a repository
    the first still holds. Weekly/monthly schedules landing on a different
    day are not conflicts.
    """
    for other in existing_schedules:
        if exclude_pk is not None and other.pk == exclude_pk:
            continue
        if other.dataset != dataset:
            continue
        if other.frequency != frequency or other.run_at != run_at \
                or other.weekday != weekday:
            # Different timing: still a conflict when the runs would land
            # within an hour of each other on the same day pattern.
            if not _same_day_pattern(frequency, other.frequency, weekday,
                                     other.weekday):
                continue
            gap = abs(_minutes(other.run_at) - _minutes(run_at))
            if gap <= 60:
                return (f"Conflicts with an active {other.frequency} schedule "
                        f"at {other.run_at:%H:%M} for dataset "
                        f"{dataset or 'institution-wide'!r}.")
            continue
        return (f"An active {other.frequency} schedule at "
                f"{other.run_at:%H:%M} already covers "
                f"{dataset or 'institution-wide'!r}.")
    return None


def _same_day_pattern(a: str, b: str, weekday_a: int | None,
                      weekday_b: int | None) -> bool:
    if a == "daily" or b == "daily":
        return True
    if a == "weekly" and b == "weekly":
        return weekday_a == weekday_b
    return a == "monthly" or b == "monthly"


def _minutes(t: dt.time) -> int:
    return t.hour * 60 + t.minute


def is_due(schedule, *, now: dt.datetime,
           last_success_for_dataset: dt.datetime | None) -> bool:
    """Whether a schedule is due for execution at `now`.

    Daily: past run_at today and no success since the last midnight.
    Weekly: the weekday matches, past run_at, no success this week.
    Monthly: the 1st of the month, past run_at, no success this month.
    """
    if not schedule.is_active:
        return False
    if now.time() < schedule.run_at:
        return False
    if schedule.frequency == "daily":
        boundary = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif schedule.frequency == "weekly":
        if weekday_of(now) != schedule.weekday:
            return False
        boundary = (now - dt.timedelta(days=weekday_of(now))).replace(
            hour=0, minute=0, second=0, microsecond=0)
    else:                                   # monthly
        if now.day != 1:
            return False
        boundary = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return (last_success_for_dataset is None
            or last_success_for_dataset < boundary)


def weekday_of(now: dt.datetime) -> int:
    """0=Monday .. 6=Sunday."""
    return now.weekday()
