"""Re-queue backup-failure alerts that missed the five-minute SLA.

The same guard the `badms.sweep_backup_alerts` beat entry runs (BR-BA-014).
"""
from django.core.management.base import BaseCommand

from modules.badms.services import backups


class Command(BaseCommand):
    help = "Re-queue failure alerts that never made it out."

    def handle(self, *args, **opts) -> None:
        n = backups.sweep_failure_alerts()
        self.stdout.write(f"re-queued {n} alert(s)")
