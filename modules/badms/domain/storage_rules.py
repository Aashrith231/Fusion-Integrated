"""Storage rules (UC-BA-022, BR-BA-016, AFR-BA-052).

The threshold monitor keeps `StorageProfile.full` current; the extension
service validates a request against the user's usage and the available
infrastructure before anything is routed anywhere.
"""

#: A profile is full when usage reaches the quota.
def is_full(used_bytes: int, quota_bytes: int) -> bool:
    return used_bytes >= quota_bytes


def extension_usage_check(used_bytes: int, quota_bytes: int) -> str | None:
    """The usage condition a request must satisfy (BR-BA-016).

    The trigger is "quota is full"; a user who is not full has no reason to
    request an extension, so the request is refused.
    """
    if not is_full(used_bytes, quota_bytes):
        return (f"Storage quota is not full: {used_bytes} of {quota_bytes} "
                f"bytes in use.")
    return None


def extension_infra_check(requested_bytes: int,
                          available_bytes: int) -> str | None:
    """Detect when a requested extension exceeds available infrastructure
    (AFR-BA-052)."""
    if requested_bytes <= 0:
        return "The requested extension must be a positive amount of storage."
    if requested_bytes > available_bytes:
        return (f"Requested {requested_bytes} bytes exceeds the "
                f"{available_bytes} bytes of available infrastructure.")
    return None
