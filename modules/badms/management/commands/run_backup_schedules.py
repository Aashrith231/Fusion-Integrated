"""Run every due backup schedule once, by hand.

The same work the `badms.run_scheduled_backups` beat entry does (UC-BA-006) —
for a cron-only deployment or an operator catching up after downtime.
"""
from django.core.management.base import BaseCommand

from modules.badms.services import backups


class Command(BaseCommand):
    help = "Execute every backup schedule that is due."

    def handle(self, *args, **opts) -> None:
        ran = backups.run_due_backups()
        self.stdout.write(f"ran {ran} schedule(s)")
