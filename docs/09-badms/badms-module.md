# BADMS — Backup and Database Archive Management System

Module code `badms`, mounted at `/api/v1/badms/` and `/badms` in the console.

## What it does

BADMS supports institutional backup, secure archival, restoration,
storage-extension, scheduling, retention, notification, logging, reporting and
security-administration activities, per the synchronised BADMS v1.2
specification bundle (Problem Statement, Requirement Registry, Use Cases,
Business Rules, Workflows).

## Roles and role boundaries (PS 3.8)

| Designation | Scope in BADMS |
|---|---|
| `student`, `faculty`, `staff` | Submit archival, restoration and storage-extension requests; track their own requests; view backup status |
| `hod` | Decide archival and storage-extension requests **for the HoD's own department**; departmental reports |
| `sysadmin` | Manual backups; local (dataset) schedules; authoritative classification; restoration approval and technical execution; audit-log review |
| `it_security` | Encryption for Sensitive data; RBAC assignments; security policies; security audit |
| `super_admin` | Institution-wide global backup schedules and default policy; special archival operations; everything the sysadmin holds |

Department scope comes from the IAM directory projection
(`modules.directory`); a HoD acts only where their department matches the
request's department (BR-BA-010). Director of IT is a notification recipient
only (BR-BA-015).

## Domain tables (`badms_*`)

`BackupRepository`, `Backup`, `BackupSchedule` (local + global), `ScheduleChangeLog`,
`ArchivalRequest`, `ArchivalDecision`, `SpecialArchivalRecord`,
`RestorationRequest`, `StorageProfile`, `StorageInfrastructure`,
`StorageExtensionRequest`, `SecurityPolicy`, `RbacAssignment`, `AuditEvent`,
`NotificationOutbox`.

## Workflows (state machines in `domain/states.py`)

* **Secure archival (CW-BA-01)**: submitted → hod_approved → classified
  (non-Sensitive) | routed_to_security → encrypted | encryption_failed;
  submitted → rejected. Missing initial classification defaults to Routine
  (BR-BA-006). Sensitive data is encrypted with AES-256 at rest and in
  transit (BR-BA-007); retention treatment follows the authoritative
  classification (BR-BA-008).
* **Storage extension (CW-BA-02)**: submitted → approved | rejected.
  Submission requires a full quota (BR-BA-016) and is validated against the
  available infrastructure (AFR-BA-052). Processing ends with the recorded
  decision — no post-approval processing in this version.
* **Restoration (CW-BA-03)**: non-Sensitive → requested → restored | failed;
  Sensitive → pending_approval → approved_for_restoration → restored | failed
  or rejected. No HoD restoration route exists in this version (BR-BA-005).
* **Special archival** is not a workflow: the request originates offline, and
  only the Super Admin performs the operation (BR-BA-018).

## Schedules and precedence

A valid local schedule for a dataset overrides the institution-wide global
schedule; where no local schedule exists the global one applies (BR-BA-011).
Saves are parameter- and conflict-validated first; an invalid configuration
is never applied (BR-BA-012), and every applied change is logged
(AFRA-BA-016 → `ScheduleChangeLog`).

## Scheduled work (`schedule.py`)

| Task | Cadence | Why |
|---|---|---|
| `badms.deliver_notifications` | 60 s | delivery beat; puts the backup-failure alert inside the 5-minute SLA (BR-BA-014) |
| `badms.run_scheduled_backups` | 300 s | executes every schedule that is due (UC-BA-006) |
| `badms.sweep_backup_alerts` | 300 s | re-queues a failure alert that never made it out (BR-BA-014 guard) |
| `badms.monitor_storage` | 15 min | keeps each user's full-quota status current (UC-BA-022) |

Three consecutive backup failures escalate to the Director of IT
(BR-BA-015); the escalation fires exactly once per streak.

## Notifications

Written to `badms_notification_outbox` in the same transaction as the event
that caused them: backup completion/failure/escalation, archival
submission/decision/encryption, storage submission/decision, restoration
decision/completion. Alert recipients come from settings:
`BADMS_SYSADMIN_ALERT_EMAIL`, `BADMS_DIRECTOR_IT_EMAIL`,
`BADMS_SECURITY_INBOX`, `BADMS_DEPARTMENT_INBOX_TEMPLATE`.

## API surface

Backups: `GET /backups`, `POST /backups/manual`, `GET /repositories`.
Schedules: `GET|POST /schedules`, `GET|PUT /schedules/global`,
`PATCH /schedules/<id>/modify`, `GET /schedules/<id>/changes`.
Archival: `GET|POST /archival(/submit|/mine)`, `GET /archival/<id>`,
`POST /archival/<id>/(decide|classify|encryption)`.
Special archival: `GET /special-archival`, `POST /special-archival/perform`.
Restoration: `GET /restorations`, `POST /restorations/request`,
`POST /restorations/<id>/(decide|execute)`.
Storage: `GET /storage/me`, `GET|POST /storage/extensions(/submit|/mine)`,
`POST /storage/extensions/<id>/decide`, `GET /storage/infrastructure`.
Audit/security: `GET /audit`, `GET /security/audit`,
`GET|POST /security/policies`, `PATCH /security/policies/<id>`,
`GET|POST /security/rbac`.
Reports/tracking: `GET /reports/department`, `GET /me/requests`.

Scope is enforced by narrowing querysets (`selectors/scoping.py`): a row
outside the caller's scope is absent (404), never a 403 confirming it exists.
Refusals follow `docs/01-architecture/api-conventions.md`: 422 for business
rule refusals, 409 for illegal state transitions, 403 for role denial.

## RBAC in BADMS

Module entry stays with the IAM. What IT Security manages here is the
BADMS-scoped slice (`RbacAssignment`), and `selectors/authz.has_permission`
honours an active assignment — so an RBAC grant made in BADMS is a live
permission inside the module, and every change is audited (UC-BA-019).

## Exclusions carried from the spec

No Research Supervisor actor; no separate HoD restoration-authorization
route; no post-approval storage-extension processing; no automated
infrastructure-shortfall remediation; no classification-specific retention
duration values.
