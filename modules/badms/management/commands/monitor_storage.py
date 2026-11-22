"""Re-evaluate every user's storage threshold status by hand.

The same work the `badms.monitor_storage` beat entry runs (UC-BA-022).
"""
from django.core.management.base import BaseCommand

from modules.badms.services import storage


class Command(BaseCommand):
    help = "Refresh every storage profile's full-quota status."

    def handle(self, *args, **opts) -> None:
        n = storage.monitor_all()
        self.stdout.write(f"monitored {n} profile(s)")
