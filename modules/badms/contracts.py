"""badms's public surface. Plural by signature.

Nothing else in the platform needs BADMS internals today; the contract is the
storage-threshold condition, because any module that writes data a user owns
may want to know whether that user's quota is full without reaching into
badms models.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class StorageStatusDTO:
    user_id: int
    used_bytes: int
    quota_bytes: int
    full: bool


def get_storage_statuses(user_ids: Sequence[int]) -> dict[int, StorageStatusDTO]:
    """Whether each user's storage quota is full (UC-BA-022's condition).

    Plural because callers check a batch, not a person. A user with no
    profile is not full — the quota has simply never been needed.
    """
    from modules.badms.models import StorageProfile

    ids = {int(i) for i in user_ids if i is not None}
    if not ids:
        return {}
    rows = StorageProfile.objects.in_bulk(ids)
    return {
        uid: StorageStatusDTO(uid, p.used_bytes, p.quota_bytes, p.full)
        for uid, p in rows.items()
    }
