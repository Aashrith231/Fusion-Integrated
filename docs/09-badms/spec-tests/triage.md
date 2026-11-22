# Spec tests: badms

Student 1 (git author name): Aashrith
Student 2 (git author name): Aashrith
Design commit (hash and subject): d5f9dc6 badms spec tests: frozen designs from the specification (FR, UC, BR, WF)
Baseline commit (hash and subject): (this commit — see "Tests commit" below)
Student 1's 10/10 commit the baseline ran on (hash): the review loop ran
Round 1 (19 findings, verdict "not yet"); all 19 were fixed and the
gates were re-verified (commit ef79804, rebased onto upstream/main
5595be6). Later rounds were not run before the hand-in deadline; the
baseline ran on e6adc5e.

## Results

| Run | Strategy | Cases | Passed | Failed | Skipped | Line % | Branch % |
|-----|----------|-------|--------|--------|---------|--------|----------|
| baseline | fr | 32 | 32 | 0 | 0 | 70.2 | 73.8 |
| baseline | uc | 33 | 33 | 0 | 0 | 48.6 | 69.0 |
| baseline | br | 32 | 32 | 0 | 0 | 45.6 | 75.3 |
| baseline | wf | 14 | 14 | 0 | 0 | 31.5 | 84.0 |

(Case counts are the executed tests; the four frozen designs hold 149
obligations, some sharing one closely-related test per the design rules.)

## Failures and skips

| Test id | Source id | Strategies | Category | Evidence | Outcome |
|---------|-----------|------------|----------|----------|---------|
| — | — | — | — | — | — |

No failing or skipped tests in the baseline.

## Observations (recorded for Student 1, not open rows)

1. `services/storage.py` `decide_extension` raises the raw state-machine
   `ValueError` for an illegal transition instead of converting it to
   `ConflictError` the way the archival service does — over HTTP this would
   be a 500, not the 409 the API conventions name. The workflow test
   wf_007 asserts "refused and nothing changed" so it passes either way.
   Candidate defect for Student 1.
2. A manual backup against an unreachable repository still succeeds
   (the dump is written locally), so BR-BA-013's reachability gate is only
   exercised on the scheduled path (br_024/br_025). Accepted reading: the
   spec ties reachability to scheduled execution (AFR-BA-011).

## Rebase note

After a rebase, update every hash in this file.
