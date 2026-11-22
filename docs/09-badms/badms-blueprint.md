# BADMS blueprint (approved before implementation)

Module code `badms`, `docs/09-badms`, mounted at `/api/v1/badms/` and `/badms`.
Built on the conventions of `modules/placement`; module-only environment.

This document is the Phase 1 blueprint the pair approved before any module
code was written. The approval records are at the end (Step 3.5 / 3.8).

## 1. Models (badms_* tables)

| Table | Purpose | Key spec |
|---|---|---|
| `BackupRepository` | storage target; `reachable` is checked before transfer | BR-BA-013 |
| `Backup` | one manual/scheduled run; `consecutive_failures` drives escalation | UC-BA-001/006, BR-BA-015 |
| `BackupSchedule` | local (dataset) and global rows; active scope unique | BR-BA-011/012 |
| `ScheduleChangeLog` | every applied schedule change, appended | AFRA-BA-016 |
| `ArchivalRequest` | the secure-archival chain row; classification + retention | UC-BA-002..005 |
| `ArchivalDecision` | append-only decision history (HoD, classification, encryption) | CW-BA-01 |
| `SpecialArchivalRecord` | Super Admin's offline-originated operations | BR-BA-018 |
| `RestorationRequest` | restoration state machine row | UC-BA-016..018, BR-BA-005 |
| `StorageProfile` | per-user usage/quota/threshold status | UC-BA-022, BR-BA-016 |
| `StorageInfrastructure` | the capacity picture an extension is validated against | AFR-BA-052 |
| `StorageExtensionRequest` | usage-validated request; ends at the recorded decision | CW-BA-02 |
| `SecurityPolicy` | IT Security-defined policies | UC-BA-020 |
| `RbacAssignment` | BADMS-scoped permission grants IT Security manages | UC-BA-019, BR-BA-021 |
| `AuditEvent` | user/admin/system/security events | UC-BA-013 |
| `NotificationOutbox` | transactional outbox with dedupe key | UC-BA-011, BR-BA-014 |

People are plain `user_id` integers; departments come from the IAM directory
projection (`modules.directory.contracts`).

## 2. State machines (declarative tables in `domain/states.py`)

* **Archival (CW-BA-01)**: submitted → hod_approved → classified |
  routed_to_security → encrypted | encryption_failed → (retry) encrypted;
  submitted → rejected. Missing initial classification defaults to Routine
  (BR-BA-006).
* **Extension (CW-BA-02)**: submitted → approved | rejected. Ends at the
  recorded decision — no post-approval processing in this version.
* **Restoration (CW-BA-03)**: requested → restored | failed;
  pending_approval → approved_for_restoration → restored | failed | rejected.
  No HoD restoration route (BR-BA-005).

Illegal transitions raise; every decision service re-reads its row under
`select_for_update` inside the transaction that applies the transition.

## 3. Roles and permissions (19 module permissions)

| Designation | Holds (summary) |
|---|---|
| student/faculty/staff | backup.view, archival.submit, restoration.request, storage.request |
| hod | + archival.decide, storage.decide, report.department (department scope, BR-BA-010) |
| sysadmin | + backup.trigger, schedule.manage, archival.classify, restoration.approve/execute, audit.view |
| it_security | + encryption.manage, security.audit, rbac.manage, security_policy.manage |
| super_admin | everything the sysadmin holds + schedule.manage_global, special_archival.perform |

`SYSTEM_PERMISSIONS` (run_scheduled, storage.monitor, audit.record) are held
by no designation — the scheduled tasks and services carry them.

## 4. API surface (mounted under `/api/v1/badms/`)

Backups, repositories, schedules (create/modify/global/changes), archival
(list/mine/submit/detail/decide/classify/encryption), special-archival,
restorations (list/request/decide/execute), storage (me, extensions
queue/submit/mine/decide, infrastructure), audit, security (audit, policies,
rbac), reports/department, me/requests. Every list and detail view narrows
through `selectors/scoping.py` (BR-BA-020); out-of-scope rows 404.

## 5. Scheduled work

| Entry | Cadence | Purpose |
|---|---|---|
| `badms.deliver_notifications` | 60 s | the delivery beat inside BR-BA-014's SLA |
| `badms.run_scheduled_backups` | 300 s | run due schedules (UC-BA-006) |
| `badms.sweep_backup_alerts` | 300 s | re-queue missed failure alerts |
| `badms.monitor_storage` | 15 min | threshold status (UC-BA-022) |

Operator commands: `deliver_notifications`, `run_backup_schedules`,
`sweep_backup_alerts`, `monitor_storage`.

## 6. Frontend routes (`/badms`)

13 pages, one lazy chunk each; the nine office pages are wrapped in
`RequirePermission` with exactly their nav item's permission (backups,
archival, restoration and storage are open to plain module users).

## 7. Shared-file changes (Step 3.5 record)

| File | Change | Why |
|---|---|---|
| `config/settings/base.py` | `DOMAIN_MODULES` + `modules.badms`; `DEFAULT_THROTTLE_RATES` += `badms_backup_trigger` 10/min, `badms_write` 60/min; `BADMS_*` alert/inbox/root settings (all with working defaults) | registration + notification routing + artifact roots |
| `config/urls.py` | include `modules.badms.api.urls` | registration |
| `config/celery.py` | merge badms beat + task routes | registration |
| `.importlinter` | badms added to the contract source list + `badms-layers` contract | registration |
| `client/src/app/registry.ts` | badms module entry | registration |
| `registry/permissions.json`, `docs/02-iam/permission-catalog.generated.md`, `openapi/fusion-integrated.v1.yaml` | regenerated | generated files |
| `client/e2e/accounts.ts` | two new account entries (badmsSysadmin, badmsHod) | e2e harness needs BADMS roles |

## 8. Approvals (Step 3.8 record)

| Item | Decision | Approval |
|---|---|---|
| Blueprint as a whole | approved | *(Student 2's written approval: name, date — TO BE FILLED BY THE PAIR)* |
| `BADMS_*` settings block in `config/settings/base.py` | approved | *(same record)* |
| `RbacAssignment`/`SecurityPolicy` tables inside BADMS | approved: the BADMS spec (UC-BA-019, BR-BA-021) mandates in-module RBAC management, which the platform's no-access-control-table rule cannot govern; the IAM keeps the institution-wide grants | *(same record)* |
| Known gap: no post-approval storage-extension processing | accepted (spec E2) | *(same record)* |
| Known gap: no HoD restoration route | accepted (spec BR-BA-005) | *(same record)* |
