"""SLA reminder and escalation sweep (EL-UC-021, BR-EL-032/033/034).

The sweep runs on the beat; these tests drive it directly
through :func:`sla.sweep` with explicit ``now`` values so the
thresholds are exercised deterministically.
"""
from datetime import date, timedelta

import pytest
from django.utils import timezone

from .support import applicant, head
from .test_lifecycle import apply, approve

pytestmark = pytest.mark.django_db


def task_for(request, task_class):
    from modules.elm.models import LeaveTask

    return LeaveTask.objects.get(
        request=request, task_class=task_class,
        status="pending")


def configure_sla(task_class, *, reminder_hours=1,
                  escalation_hours=2, action="notify",
                  target_role=""):
    from modules.elm.models import SlaConfig

    return SlaConfig.objects.create(
        task_class=task_class, reminder_hours=reminder_hours,
        escalation_hours=escalation_hours,
        escalation_action=action,
        escalation_target_role=target_role)


def notifications_for(user_id, topic):
    from modules.elm.models import Notification

    return list(Notification.objects.filter(
        recipient_user_id=user_id, topic=topic))


class TestSlaSweep:

    def test_no_thresholds_configured_is_a_noop(self, world):
        from modules.elm.services import sla

        apply(applicant())                     # a pending review exists
        result = sla.sweep()
        assert result == {"reminded": 0, "escalated": 0}

    def test_reminder_fires_at_the_threshold_once(self, world):
        from modules.elm.models import RequestEvent, SlaEventLog
        from modules.elm.services import sla

        configure_sla("unit_head_review", reminder_hours=1,
                      escalation_hours=100)
        request = apply(applicant())
        task = task_for(request, "unit_head_review")
        now = timezone.now()

        before = sla.sweep(now=now)
        assert before == {"reminded": 0, "escalated": 0}

        after = sla.sweep(now=now + timedelta(hours=2))
        assert after["reminded"] == 1
        task.refresh_from_db()
        assert task.reminded_at is not None
        assert notifications_for(task.assignee_user_id,
                                 "sla_reminder")
        assert SlaEventLog.objects.filter(
            task=task, kind="reminder").exists()
        assert RequestEvent.objects.filter(
            request=request, event="reminder").exists()

        # Idempotent: the second sweep does not remind again.
        again = sla.sweep(now=now + timedelta(hours=3))
        assert again["reminded"] == 0

    def test_escalation_notifies_the_configured_authority(self, world):
        from modules.elm.models import SlaEventLog
        from modules.elm.services import sla

        from .support import DEAN, HEAD

        configure_sla("unit_head_review", reminder_hours=1,
                      escalation_hours=2, action="notify",
                      target_role="Dean")
        request = apply(applicant())
        task = task_for(request, "unit_head_review")
        now = timezone.now()

        result = sla.sweep(now=now + timedelta(hours=3))
        assert result["escalated"] == 1
        task.refresh_from_db()
        assert task.escalated_at is not None
        assert task.assignee_user_id == HEAD   # notify does not move it
        assert notifications_for(DEAN, "sla_escalation")
        assert SlaEventLog.objects.filter(
            task=task, kind="escalation").exists()

    def test_escalation_reassigns_where_configured(self, world):
        """XTP-EL-01: escalation changes responsibility only
        where it is configured to."""
        from modules.elm.services import sla

        from .support import EST, EST2

        configure_sla("establishment_routing",
                      reminder_hours=1, escalation_hours=2,
                      action="reassign",
                      target_role="Deputy Registrar (Estt.)")
        request = apply(applicant(), "EL",
                        start=date(2026, 3, 16), end=date(2026, 3, 20))
        from modules.elm.services import workflow

        workflow.unit_head_decide(request, head(),
                                  outcome="recommended")
        from modules.elm.models import LeaveTask

        tasks = LeaveTask.objects.filter(
            request=request, task_class="establishment_routing",
            status="pending")
        assert {t.assignee_user_id for t in tasks} == {EST, EST2}
        first = min(t.id for t in tasks)
        now = timezone.now()

        sla.sweep(now=now + timedelta(hours=3))
        task = LeaveTask.objects.get(id=first)
        task.refresh_from_db()
        # Sorted holders: 301 < 302 — the first holder inherits.
        assert task.assignee_user_id == EST
        assert task.escalation_detail["reassigned_from"] == EST
        # The bumped-off holder is told; the receiver is told.
        assert notifications_for(EST2, "sla_escalation")

    def test_completed_tasks_are_never_touched(self, world):
        """BR-EL-034: SLA clocks stop when the work stops."""
        from modules.elm.services import sla

        configure_sla("unit_head_review", reminder_hours=0,
                      escalation_hours=0)
        approve(apply(applicant()))            # decided, not pending
        now = timezone.now() + timedelta(hours=10)
        result = sla.sweep(now=now)
        assert result == {"reminded": 0, "escalated": 0}
