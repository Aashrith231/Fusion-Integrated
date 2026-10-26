# Assignment 6B — Phase 2 Review Report: the ELM Module

**Branch:** `phase2-improvements` (three commits on top of Phase 1)
**Phase 1 preserved:** tag `phase-1-elm`, branch `phase-1-archive` @ `1278443` — untouched.
**Review authority:** `ELM_Specifications_Bundle_v1.4_FINAL.zip` — Problem Statement v1.4, FRS v1.5, Business Rules v1.4, Use Cases v1.4, **Workflow Specifications v1.6** (authoritative for the state-transition tables).

---

## 1. What Phase 2 did

Phase 1 delivered a complete-looking ELM module with **zero module tests**.
Phase 2 reviewed every layer of it against the specification bundle — the state
machine, the workflow engine, the lifecycle services (cancellation, extension,
resumption), applications, policy/year-end, offline recording, notifications,
the API layer, and the client — and drove the module to a green, spec-faithful
test suite.

The method: **write the test suite first from the spec, then let the failures
drive the defect list.** Every red test in the first runs was triaged as either
a test bug (wrong expectation or wrong fixture use) or a genuine defect
(implementation contradicts the spec). Nothing was "fixed to make the test
pass" — every backend change cites the rule or STT row it restores.

## 2. Verification

| Gate | Result |
|---|---|
| `pytest` (whole platform) | **588 passed** (181 ELM-specific across 8 suites) |
| `make check` (system check, migrations, ruff, import-linter, ops checks, permission manifest, schema-check, full pytest) | **all green** |
| `make check-client` (typecheck, 35 vitest tests, production build) | **all green** |
| `makemigrations --check` | clean (migration 0003 committed) |
| OpenAPI schema | regenerated, committed, matches code |

## 3. Spec defects found and fixed (backend)

### 3.1 Director self-sanction path (BR-EL-019/020, BW-EL-07/08/09)

- **Derived requests deadlocked.** A cancellation or extension of the
  Director's own leave was born at `cancellation_pending_unit_head_review` /
  `awaiting_extension_unit_head_review` — but the Director is nobody's Unit
  Head, so the request could never advance. Workflow spec v1.6 rows for
  BW-EL-11/13 put a director-path derived request straight at its kind's
  final decision state. `initial_state(..., director_path=...)` now returns
  the final state for both kinds, and plain `sanction_*` rows were added for
  cancellation/extension at that state (v1.6 defines no director *variants*
  for CW-EL-02/03 — the derived request simply starts at its kind's final
  state). The actor restriction stays in `_verify_actor`.
- Cancellation/extension now also carry the director route over from the base
  request, so `route_is_director()` classification survives into the derived
  object.

### 3.2 Outcome vocabularies (BR-EL-016/017, BR-EL-028a in FRS)

- `unit_head_decide` accepted `approve/reject` on higher-sanction reviews and
  `recommended/not_recommended` on CL/RH reviews — the vocabularies are
  state-specific. Fixed with kind/category gating and `invalid_outcome`.
  Per BW-EL-10/11: cancellation of a *Unit-Head-final* (CL/RH) leave is
  decided by the Unit Head; cancellation of a *higher-sanction* leave takes a
  recommendation.
- Establishment routing (`EL-UC-004`) forwarded with **any** outcome string;
  it now rejects everything except `forward` — "Establishment routes, it
  never decides" (BR-EL-018) — and `final_decide` rejects vocabulary that
  does not belong to the final state.

### 3.3 Resumption (EL-UC-010/011, CW-EL-04, BR-EL-027/028)

- **Review semantics** were anchored to `end_date + 1`. Spec EL-UC-011 M2–M4
  pins: *actual == approved end date* ⇒ normal, no adjustment; earlier ⇒ the
  unused span is restored; later ⇒ the extra span is charged. Rewritten
  accordingly.
- **Assignee resolution** fell back to the applicant — the applicant would
  review their own resumption. Fixed: ELM leave → the authority who sanctioned
  it (`decided_by_user_id`); offline-recorded leave → the holders of the
  recorded sanctioning-authority designation, one task each, first mover wins
  (BR-EL-027); **no holder ⇒ fail closed** with `no_sanctioning_authority`
  instead of deadlocking in `review_pending`.
- `create_resumption_task` now creates one task per office holder with a
  `resumption` FK, per-task events and notifications; offline-recorded leave
  (no application behind it) logs and notifies with `request=None`.
- The reviewer gate refused legitimate office-holders other than the person
  who sanctioned (e.g., re-assignment), and had no gate at all for offline
  records; both paths now verify the caller actually holds the authority
  (designation-based).

### 3.4 Cancellation (EL-UC-008, CFR-EL-019, BR-EL-023/024)

- **After the leave began**, the pre-start cancellation path still accepted
  the request (AFR-EL-019.8). Added the `leave_already_started` gate.
- A second pending cancellation for the same leave could be opened (double
  restore on both approvals). Added the `cancellation_pending` guard.

### 3.5 Extension (EL-UC-009, CW-EL-03, BR-EL-006/011)

- VL extensions could leave the published vacation period. Added the
  vacation-window check (`calendar_violation`) *before* the adjacency check,
  and the faculty-only applicability check.
- The adjacency rule (`start == end_date + 1`) is enforced for all
  extensible categories; because BR-EL-011 counts EL/COL/VL continuously,
  "without a gap" is exactly one calendar day.

### 3.6 Applications (EL-UC-001)

- **Unconfigured hierarchy** defaulted `establishment_required=True` for
  higher-sanction categories; BR-EL-019 makes Establishment processing
  required *only where configured* — fallback now routes straight to the
  Sanctioning Authority.
- `submit` was not atomic (a failure after the nomination insert left
  partial state); now `@transaction.atomic`.
- Nominee validation ran outside the domain-error translation, leaking a
  bare `SubstituteIneligible` (500-shaped) instead of
  `409 substitute_ineligible`.
- Duplicate station-details validation ran twice per submission; removed
  the one inside `_validate_no_overlap`.

### 3.7 Workflow engine integrity

- `withdraw()` (BR-EL-022, cross-cutting "Pending → Withdrawn" from every
  valid pending state) did not retire pending tasks, release the consent
  gate, or notify watchers; rewritten with watcher capture and
  `notify_request_withdrawn` (new in `notifications.py`).
- `respond_substitute` mutated the nomination to *inactive before* the
  transition re-verified the actor — every **decline** failed with
  "You are not the nominated substitute". The transition now runs first;
  the response is recorded after, inside one atomic block.
- **EL-UC-019 (nominate replacement after decline) had no implementation at
  all** — the state rows existed, but no service could reach them without
  hand-editing rows. Added `workflow.nominate_replacement`.
- `apply_transition` was not atomic; `_account_for` created lazy accounts
  with zero entitlement (a Director's account born at approval showed a
  negative balance). Entitlement now seeds from policy.

### 3.8 Policy and year-end (PS §3, BR-EL-005, EL-UC-020)

- `leave_year_for` compared the day against a boundary built in the day's
  own calendar year, mislabelling years for late-year boundaries; the
  boundary-day-closes-the-year rule is retained and the label is the year
  the leave year *starts* in.
- `entitlement_for(EL, faculty)` returned a staff number; BR-EL-005 gives
  faculty no granted EL (their EL credit exists only via VL conversion).

### 3.9 API layer

- `get_permissions` overrides dropped the module grant on
  `ApplicationListView` POST and `RecordListView` — a principal holding the
  fine permission but no `elm` module grant could act. The grant is back on
  every path (`HasModuleGrant("elm")` is a class factory — the override
  instantiates it).
- `TaskDecideView` would crash (500) on resumption tasks — which, for
  offline-recorded leave, have *no request behind them* — and bypasses
  resumption semantics besides; it now answers 409 and points at the review
  endpoint.
- `ApplicationSubstituteView` accepted nominations on terminal/in-review
  requests (stray, un-actionable nominations); gated to the four
  substitute-awaiting states.
- Admin write endpoints passed raw `request.data` into services (junk ⇒
  `TypeError` ⇒ 500). Added `PolicyWrite` / `HierarchyWrite` /
  `SlaWrite` serializers: malformed payloads now answer **400**, and policy
  entitlement entries are validated as non-negative numbers.
- Record summaries expose `source_request`; task payloads expose the
  `resumption` id (needed by the review UI and by offline-leave tasks).

### 3.10 Offline recording (EL-UC-017, BR-EL-037)

- `RecordInconsistent` was raised but never translated to the API envelope
  (`_translate` existed and was never called) — a spec'd 409 shipped as an
  uncaught domain error. Now raises `ConflictError(record_inconsistent)`.

## 4. Client defects fixed

- **Date-shift bug (all DateInput consumers):** `toISOString().slice(0, 10)`
  formats at UTC — in IST, every picked date shipped as the previous day.
  Replaced with a shared `isoDate()` helper formatting locally via dayjs
  (`RequestsPage`, `OfflinePage`, `RecordsPage`).
- **Outcome vocabularies (TasksPage):** the Unit-Head modal offered all four
  outcomes on every review; the select now offers the state's own vocabulary
  (CL/RH work decides, higher-sanction work recommends).
- **Resumption review UI was missing:** resumption tasks rendered the
  generic approve/reject decide modal — which the backend now refuses. Added
  a resumption-review modal (normal / early / late + reason) calling the
  review endpoint; offline-leave tasks (no request behind them) render
  correctly.
- **Half-day forms:** half-day selects are CL-only in the spec (BR-EL-010)
  but were always enabled; now disabled for other categories and reset on
  category change so a stale half never rides along.
- **Station leave form:** the service requires destination **and** travel
  dates; the form collected only the destination, guaranteeing a 409. From/to
  date inputs added, with client-side completeness check.
- **Zombie drafts:** a created-but-unsubmitted draft was a dead card. Draft
  rows now get a Submit action (draft → submit endpoint, with optional
  substitute fields).
- **Lifecycle flows had no UI at all** (the cancel/extend/resume hooks were
  dead code): ongoing records now surface *Extend*, *Resume duty*, and
  *Cancel* (pre-start only, per BR-EL-023) — wired to the existing endpoints.

## 5. The test suites (new)

| Suite | Covers |
|---|---|
| `test_domain.py` | counting/halves/holidays/overlap, eligibility, routing resolution, year-end arithmetic, leave-year derivation |
| `test_submission.py` | EL-UC-001: category applicability, balance, counting, overlap, substitute eligibility, director path, station details |
| `test_workflow.py` | EL-UC-002/003/004/005 + BW-EL-01…09: seats, vocabularies, recommendation, first-mover-wins multi-holder offices, director path, substitute gate, withdrawal |
| `test_lifecycle.py` | EL-UC-008/009/010/011 + BW-EL-10…14: cancellation, extension, resumption, BR-EL-027/028 |
| `test_records.py` | EL-UC-016/017: offline recording, consistency, resumption on offline leave, requestless task notifications |
| `test_year_end.py` | EL-UC-020: lapse, VL→EL conversion, carry-forward, ledger, once-per-year, exceptions report |
| `test_sla.py` | EL-UC-021, BR-EL-032/033/034, XTP-EL-01: reminders, escalation notify/reassign, idempotence, completed-task immunity |
| `test_api.py` | the HTTP gates: 401/403/404 semantics, module-grant + permission gates, seat checks through the API, task/resumption dispatch, admin 400s |

Shared world (`support.py`): the org cast (multi-holder Establishment and
 Dean offices included), published calendar, vacation window, frozen clock —
 so every workflow test runs deterministically and multi-holder offices are
 exercised (first mover wins, BR-EL-027/035).

## 6. Judgements worth recording

- **Adjacency for extensions:** the bundle never states "day after the end"
  in prose; it is pinned by BR-EL-011's continuous counting — the chosen
  encoding is `start == end_date + 1` for every extensible category, and the
  calendar check precedes it so a vacation-window violation is reported as
  `calendar_violation`.
- **Resumption "normal" is resuming on the approved end date** (EL-UC-011
  M3), i.e., the approved end date is the last leave day and the reported
  resumption date is the first day back on duty.
- **No blanket applicant-exclusion** on resumption assignees: on the director
  path the applicant *is* legitimately their own reviewer (BR-EL-020); the
  exclusion the tests demand (BR-EL-027) is about the sanctioning authority,
  which the route/holder resolution already guarantees.
- **Fail-closed over deadlock:** where no authority can act (unresolved
  designation, no final decision recorded), the service refuses the request
  outright rather than parking it forever.
- **Year-end tests seed the previous leave year** so they never collide with
  the fixture's current-year accounts; the run opens next-year accounts with
  `get_or_create` and seeds fresh entitlements from policy.

## 7. Known gaps / next steps

- `run_year_end` is driven by the admin API and tests; the scheduled beat
  wiring exists in `modules/elm/schedule.py` but real deployment should
  confirm the crontab entry in the ops runbook.
- The SLA escalation *reassignment* target resolves by designation; if the
  configured designation has no holder the task stays with its assignee
  (notify-only behaviour) — acceptable, but worth an admin-facing warning.
- The substitute-nomination flow relies on the applicant knowing a valid
  nominee's user id; a people-picker (the IAM directory search endpoint)
  would make the forms usable at scale.
- Assignment PDF's "manual browser test" option was not exercised — per the
  agreed scope, all client verification is static (`make check-client`).

## 8. Commit trail

| Commit | Contents |
|---|---|
| `71b53d5` | spec defects surfaced by the suites: state machine, workflow engine, lifecycle, applications, policy, offline, notifications, models/migration 0003 |
| `16f2131` | `test_api.py` + `test_sla.py`, admin write validation, module-grant gates, schema regen |
| `9794273` | client: lifecycle UI, resumption review, date handling, vocabularies, forms |
