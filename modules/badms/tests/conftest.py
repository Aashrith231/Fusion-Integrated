"""BADMS test fixtures."""
import pytest

from modules.badms.models import BackupRepository

from .helpers import ITSEC_PERMS, SYSADMIN_PERMS  # noqa: F401 — re-exported for test files


@pytest.fixture
def repo():
    return BackupRepository.objects.create(name="primary", kind="primary",
                                           location="vault", reachable=True)


@pytest.fixture
def dead_repo():
    return BackupRepository.objects.create(name="offsite", kind="offsite",
                                           location="remote", reachable=False)


@pytest.fixture
def profile_factory():
    from modules.badms.models import StorageProfile

    def _make(uid, *, used=0, quota=1024) -> StorageProfile:
        profile, _ = StorageProfile.objects.get_or_create(user_id=uid)
        profile.used_bytes = used
        profile.quota_bytes = quota
        profile.full = used >= quota
        profile.save(update_fields=["used_bytes", "quota_bytes", "full"])
        return profile
    return _make
