"""Drain the BADMS notification outbox.

The Celery beat runs this every minute (BR-BA-014's five-minute SLA); the
command is the operator's way to run the same drain before a broker exists,
or during an incident when the workers are down.
"""
from django.core.management.base import BaseCommand

from modules.badms.models import NotificationOutbox
from modules.badms.services import notifications


class Command(BaseCommand):
    help = "Send pending BADMS notifications."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None,
                            help="Maximum to send in this pass.")
        parser.add_argument("--status", action="store_true",
                            help="Report the queue and exit. Sends nothing.")

    def handle(self, *args, **opts) -> None:
        if opts["status"]:
            counts = {}
            for row in NotificationOutbox.objects.all():
                counts[row.status] = counts.get(row.status, 0) + 1
            for status in ("pending", "sending", "sent", "failed"):
                if counts.get(status):
                    self.stdout.write(f"{status}: {counts[status]}")
            if not counts:
                self.stdout.write("outbox empty")
            return
        report = notifications.deliver_pending(limit=opts["limit"])
        self.stdout.write(str(report))
        if report.failed:
            raise SystemExit(1)
