"""Query budgets: the widest lists stay O(1) in queries as they grow
(Step 5.7). The same list at two sizes must issue the same number of queries.
"""
import datetime as dt

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from modules.badms.models import (
    AuditEvent,
    Backup,
    BackupRepository,
    StorageExtensionRequest,
)
from modules.badms.selectors import scoping

from .helpers import actor

pytestmark = pytest.mark.django_db

VIEWER = actor(uid=501, perms=("badms.backup.view",))


def _repos(n: int) -> list[BackupRepository]:
    return [BackupRepository.objects.create(
                name=f"repo-{i}", location=f"srv://r{i}")
            for i in range(n)]


def _measure(qs, limit: int) -> int:
    """The query count of materialising `limit` rows from `qs`."""
    with CaptureQueriesContext(connection) as ctx:
        list(qs[:limit])
    return len(ctx)


def test_backup_list_budget_is_flat_in_row_count():
    _repos(25)
    rows = [Backup.objects.create(repository=BackupRepository.objects.get(
                name=f"repo-{i % 25}"), dataset=f"db-{i}", status="success",
                kind="manual",
                started_at=dt.datetime(2026, 11, 22, 2, i % 60,
                                       tzinfo=dt.UTC))
           for i in range(25)]
    assert len(rows) == 25
    small = _measure(scoping.backups_for(VIEWER), 5)
    big = _measure(scoping.backups_for(VIEWER), 25)
    assert small == big, "the backup list must not query per row"


def test_the_audit_list_budget_is_flat_in_row_count():
    for i in range(30):
        AuditEvent.objects.create(
            action=f"a.{i}", actor_user_id=501, actor_kind="admin",
            object_type="backup", object_id=str(i))
    small = _measure(AuditEvent.objects.all(), 5)
    big = _measure(AuditEvent.objects.all(), 30)
    assert small == big, "the audit list must not query per row"


def test_the_storage_extension_queue_budget_is_flat_in_row_count():
    rows = [StorageExtensionRequest.objects.create(
        user_id=600 + i, department=f"D{i}", requested_bytes=1,
        justification="j", attachment="a://x", usage_at_request=1,
        quota_at_request=1) for i in range(20)]
    assert len(rows) == 20
    hod = actor(uid=502, perms=("badms.storage.decide",))
    small = _measure(scoping.storage_extensions_for(hod), 5)
    big = _measure(scoping.storage_extensions_for(hod), 20)
    assert small == big, "the extension queue must not query per row"

