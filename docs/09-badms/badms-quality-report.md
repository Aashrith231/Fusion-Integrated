# BADMS quality report (builder's claim, verified against the gates)

Branch `module/badms`, module code `badms`, round 1 review fixes applied.

## Gate results (measured 2026-11-22, commit at the time of writing)

| Gate | Result |
|---|---|
| `make check` (ruff, importlinter, ops checks, permission manifest, schema check, full pytest) | PASS |
| `make check-client` (tsc, vitest, build) | PASS |
| coverage `--cov=modules/badms --cov-fail-under=90` (test files excluded, per the repo's coverage config) | PASS — 92.02% |
| coverage `--cov=modules/badms/domain --cov-fail-under=95` | PASS — 97.62% |
| `manage.py check --deploy` (prod env, per §7.7) | PASS |
| AI-attribution greps over log/diff/module files | CLEAN |
| `ops/docs/badms_reference.py && git status --porcelain` | PASS (50 ids resolved) |
| `makemigrations --check` | PASS |

## Test counts (without `tests/spec/`, which Student 2 owns)

- **221 backend tests pass** in `modules/badms` (excl. `tests/spec/`): 22 in
  `test_api.py` + journeys, privilege escalation, scoping isolation,
  concurrency (real threads under `transaction=True`), query budgets
  (flat at two list sizes), schedule tests, the permission-drift test, and
  negative twins for every positive path.
- **22 client tests pass** (`hooks.test.tsx` + page tests for Backups,
  Archival, Schedules, Storage: loading, empty, error, hidden control,
  main action each).

## Round 1 review: findings and their disposition

R1-01 ignore_imports (fixed), R1-02 coverage gates (fixed 92.02/97.62),
R1-03 e2e specs (fixed: `client/e2e/badms/` guards + backups + archival
specs; `make e2e` requires the IAM on 8001 and `make dev` running), R1-04
this report (fixed), R1-05 blueprint (fixed), R1-06 reference script
(fixed), R1-07 journeys (fixed), R1-08 BADMS_* settings (approved — see the
blueprint's approval table), R1-09 select_for_update (fixed), R1-10/11/12
test categories (fixed), R1-13 CSRF test (fixed), R1-14 throttle scopes
(fixed), R1-15 route guards + guard test (fixed), R1-16 page tests (fixed),
R1-17 rebase (fixed: branch is on `upstream/main`), R1-18 noqa reasons
(fixed), R1-19 leftover debug file (removed).

## Browser walkthrough table

To be produced by the builder with the IAM running (`make dev` + IAM on
8001), one row per role × use case, each row carrying the `runserver` log
lines of its requests. Status: **pending** — run after Student 2's
baseline; the HTTP-level journeys in `tests/test_journeys.py` already
exercise every main flow.

## Approvals

See `badms-blueprint.md` §8: blueprint, the `BADMS_*` settings block, the
in-module RBAC tables and both known gaps need Student 2's written approval
recorded there before the PR.
