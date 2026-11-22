#!/usr/bin/env python
"""Generate docs/09-badms/badms-reference.md from the real code.

Every live spec id (requirement, business rule, use case, workflow) links to
the file and line that enforces or exercises it — found by searching the code
at run time, so a stale link cannot survive the gate. Exits non-zero if any
link does not resolve; run it and then `git status --porcelain` must print
nothing, or the committed reference is stale.

    .venv/bin/python ops/docs/badms_reference.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "09-badms" / "badms-reference.md"

#: id -> [(file, needle)]; the first file:line holding the needle is the link.
#: Files are relative to the repository root. Choose needles that name the
#: rule's vocabulary, not a generic token.
LINKS: dict[str, list[tuple[str, str]]] = {
    # --- business rules -----------------------------------------------------
    "BR-BA-001": [("modules/badms/api/views.py", "ManualBackupView"),
                  ("modules/badms/registry.py", "badms.backup.trigger")],
    "BR-BA-002": [("modules/badms/services/archival.py", "UC-BA-003")],
    "BR-BA-003": [("modules/badms/services/archival.py", "AES-256")],
    "BR-BA-004": [("modules/badms/services/archival.py", "UC-BA-004")],
    "BR-BA-005": [("modules/badms/services/restoration.py", "BR-BA-005")],
    "BR-BA-006": [("modules/badms/domain/policy.py", "DEFAULT_CLASSIFICATION")],
    "BR-BA-007": [("modules/badms/services/archival.py", "at rest and in transit")],
    "BR-BA-008": [("modules/badms/domain/policy.py", "RETENTION_RULES")],
    "BR-BA-009": [("modules/badms/services/storage.py", "UC-BA-008")],
    "BR-BA-010": [("modules/badms/selectors/authz.py", "in_department")],
    "BR-BA-011": [("modules/badms/domain/rules.py", "local-over-global")],
    "BR-BA-012": [("modules/badms/domain/rules.py", "conflict detection")],
    "BR-BA-013": [("modules/badms/services/backups.py", "reachable")],
    "BR-BA-014": [("modules/badms/services/backups.py", "ESCALATION")],
    "BR-BA-015": [("modules/badms/services/backups.py", "ESCALATION_THRESHOLD")],
    "BR-BA-016": [("modules/badms/domain/storage_rules.py", "is_full")],
    "BR-BA-017": [("modules/badms/services/storage.py", "BR-BA-017")],
    "BR-BA-018": [("modules/badms/services/special.py", "BR-BA-018")],
    "BR-BA-020": [("modules/badms/selectors/scoping.py", "BR-BA-020")],
    "BR-BA-021": [("modules/badms/services/security.py", "ASSIGNABLE")],
    # --- use cases ------------------------------------------------------------
    "BA-UC-001": [("modules/badms/services/backups.py", "trigger_manual_backup")],
    "BA-UC-002": [("modules/badms/services/archival.py", "submit_request")],
    "BA-UC-003": [("modules/badms/services/archival.py", "decide_request")],
    "BA-UC-004": [("modules/badms/services/archival.py", "classify_request")],
    "BA-UC-005": [("modules/badms/services/archival.py", "configure_encryption")],
    "BA-UC-006": [("modules/badms/services/backups.py", "run_due_backups")],
    "BA-UC-007": [("modules/badms/services/schedules.py", "create_local_schedule")],
    "BA-UC-008": [("modules/badms/services/storage.py", "submit_extension")],
    "BA-UC-009": [("modules/badms/services/storage.py", "decide_extension")],
    "BA-UC-011": [("modules/badms/services/notifications.py", "deliver_pending")],
    "BA-UC-013": [("modules/badms/services/audit.py", "record_event")],
    "BA-UC-014": [("modules/badms/selectors/scoping.py", "backups_for")],
    "BA-UC-015": [("modules/badms/selectors/scoping.py", "UC-BA-015")],
    "BA-UC-016": [("modules/badms/services/restoration.py", "request_restoration")],
    "BA-UC-017": [("modules/badms/services/restoration.py", "decide_request")],
    "BA-UC-018": [("modules/badms/services/restoration.py", "execute_restoration")],
    "BA-UC-019": [("modules/badms/services/security.py", "grant_permission")],
    "BA-UC-020": [("modules/badms/services/special.py", "perform_special_archival")],
    "BA-UC-022": [("modules/badms/services/storage.py", "monitor_all")],
    "BA-UC-023": [("modules/badms/services/reports.py", "department_report")],
    # --- workflows ------------------------------------------------------------
    "CW-BA-01": [("modules/badms/domain/states.py", "ARCHIVAL_TRANSITIONS")],
    "CW-BA-02": [("modules/badms/domain/states.py", "EXTENSION_TRANSITIONS")],
    "CW-BA-03": [("modules/badms/domain/states.py", "RESTORATION_TRANSITIONS")],
    "BW-BA-01": [("modules/badms/services/archival.py", "submit_request")],
    "BW-BA-02": [("modules/badms/services/archival.py", "decide_request")],
    "BW-BA-03": [("modules/badms/services/backups.py", "_alert_sysadmin")],
    "BW-BA-04": [("modules/badms/services/backups.py", "run_due_backups")],
    "BW-BA-05": [("modules/badms/services/restoration.py", "execute_restoration")],
    "BW-BA-06": [("modules/badms/services/storage.py", "submit_extension")],
    "BW-BA-07": [("modules/badms/services/storage.py", "decide_extension")],
}


def locate(root: Path, file: str, needle: str) -> int | None:
    path = root / file
    if not path.exists():
        return None
    for number, line in enumerate(
            path.read_text(errors="replace").splitlines(), start=1):
        if needle in line:
            return number
    return None


def main() -> int:
    rows: list[str] = []
    missing: list[str] = []
    for spec_id, targets in sorted(LINKS.items()):
        anchors = []
        for file, needle in targets:
            line = locate(ROOT, file, needle)
            if line is None:
                missing.append(f"{spec_id}: {file} does not contain "
                               f"{needle!r}")
                continue
            anchors.append(f"[{file}:{line}](../../{file}#L{line})")
        if anchors:
            rows.append(f"| `{spec_id}` | {' · '.join(anchors)} |")
    if missing:
        print("badms_reference: unresolved links:", file=sys.stderr)
        for item in missing:
            print(f"  {item}", file=sys.stderr)
        return 1

    table = "\n".join(rows)
    OUT.write_text(f"""# BADMS spec-to-code reference

One `file:line` link from every live requirement, business rule, use case and
workflow id to the code that enforces it. Generated by
`ops/docs/badms_reference.py`; regenerate rather than hand-edit.

| Spec id | Enforcement / exercise points |
|---|---|
{table}
""")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(rows)} ids)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
