"""State machines for the three request workflows (CW-BA-01..03).

Transitions are keyed by `(from_state, outcome)`. Services call `transition`
before they mutate anything, so an illegal edge raises instead of silently
corrupting a request's history.
"""

# -- Secure archival (CW-BA-01) ---------------------------------------------------
ARCHIVAL_TRANSITIONS = {
    # (from_state, outcome) -> resulting state
    ("submitted", "reject"): "rejected",
    ("submitted", "approve"): "hod_approved",
    ("hod_approved", "classify"): "classified",          # non-Sensitive
    ("hod_approved", "classify_sensitive"): "routed_to_security",
    ("routed_to_security", "encrypt"): "encrypted",
    ("routed_to_security", "encrypt_failed"): "encryption_failed",
    # E1: a failed encryption stays recoverable; IT Security can retry.
    ("encryption_failed", "encrypt"): "encrypted",
}


def archival_transition(from_state: str, outcome: str) -> str:
    try:
        return ARCHIVAL_TRANSITIONS[(from_state, outcome)]
    except KeyError:
        raise ValueError(
            f"An archival request in state {from_state!r} cannot take the "
            f"outcome {outcome!r}.") from None


# -- Storage extension (CW-BA-02) --------------------------------------------------
EXTENSION_TRANSITIONS = {
    ("submitted", "reject"): "rejected",
    ("submitted", "approve"): "approved",
}


def extension_transition(from_state: str, outcome: str) -> str:
    try:
        return EXTENSION_TRANSITIONS[(from_state, outcome)]
    except KeyError:
        raise ValueError(
            f"A storage-extension request in state {from_state!r} cannot take "
            f"the outcome {outcome!r}.") from None


# -- Restoration (CW-BA-03) ---------------------------------------------------------
RESTORATION_TRANSITIONS = {
    ("requested", "execute"): "restored",
    ("requested", "execute_failed"): "failed",
    ("pending_approval", "reject"): "rejected",
    ("pending_approval", "approve"): "approved_for_restoration",
    ("approved_for_restoration", "execute"): "restored",
    ("approved_for_restoration", "execute_failed"): "failed",
}


def restoration_transition(from_state: str, outcome: str) -> str:
    try:
        return RESTORATION_TRANSITIONS[(from_state, outcome)]
    except KeyError:
        raise ValueError(
            f"A restoration request in state {from_state!r} cannot take the "
            f"outcome {outcome!r}.") from None
