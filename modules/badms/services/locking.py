"""Row locks for state changes.

Every decision service re-reads its row under `select_for_update` inside the
transaction that applies the transition, so two concurrent decisions of the
same request cannot both pass the state check.
"""


def locked(model_qs, pk):
    """Re-read the row under a lock inside an open transaction, or None."""
    return model_qs.select_for_update().filter(pk=pk).first()
