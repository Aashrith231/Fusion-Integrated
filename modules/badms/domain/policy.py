"""Classifications, defaults and retention treatment (BR-BA-006, BR-BA-008).

Institute-defined retention rules are selected by classification. This
version does not carry classification-specific duration values, so each
rule is a treatment statement, not a number.
"""
CLASSIFICATIONS = ("critical", "sensitive", "routine", "archival")
DEFAULT_CLASSIFICATION = "routine"
SENSITIVE = "sensitive"

#: Institute-defined retention treatment per classification (BR-BA-008).
RETENTION_RULES = {
    "critical": "critical: retain under the institute's critical-data "
                "retention rule; deletion requires an authorised review",
    "sensitive": "sensitive: retain under the sensitive-data retention rule; "
                 "AES-256 protection throughout the retention period",
    "routine": "routine: retain under the routine-data retention rule",
    "archival": "archival: retain under the long-term archival retention rule",
}


def effective_initial_classification(provided: str | None) -> str:
    """Use the user's initial classification; default to Routine when it is
    omitted (AFR-BA-029)."""
    value = (provided or "").strip().lower()
    if not value:
        return DEFAULT_CLASSIFICATION
    if value not in CLASSIFICATIONS:
        raise ValueError(f"Unknown initial classification {provided!r}.")
    return value


def retention_rule_for(classification: str) -> str:
    if classification not in RETENTION_RULES:
        raise ValueError(f"Unknown classification {classification!r}.")
    return RETENTION_RULES[classification]
