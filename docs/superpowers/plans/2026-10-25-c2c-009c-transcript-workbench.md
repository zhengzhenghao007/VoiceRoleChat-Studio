# C2C-009C Implementation Plan

Spec: matching docs/superpowers/specs/2026-10-25-c2c-009c-transcript-workbench.md.
Inline execution/TDD; ChatGPT independent planning/review; user delegated choices.

1. RED records/store tests. Add schemas/transcript_review.py and
   services/transcript_review_service.py: readonly legacy/job envelopes, list,
   strict correction validation, exact source snapshot, atomic revisioned copies.
2. RED API/dataset regression. Extend api/transcriptions.py with record/review
   dependencies and typed routes; preserve existing job and sync paths.
3. RED browser missing tab. Add frontend/transcriptions.js/index/style/app wiring
   and Audio action. Isolate browser jobs/record stores before any test navigation.
   Validate drafts, conflict, delayed responses, pending-save edits, recording and
   existing workbench flows. Visually open desktop/mobile captures.
4. Dual Python and actual browser, resource preservation, README/roadmap/results.
   Execution evidence -> independent whole-task review -> required bounded fixes
   -> authorized GitHub commit/push. C2C009 overall complete only after this passes.

Preflight interfaces: schema3 copies coexist with immutable schema2 JobRecord;
record basename remains dataset-compatible; frontend module owns draft/epoch/token
while app owns shared busy/recording and tabs. No changes to worker ownership.

## Execution ledger

PLAN approved with refinements; raw source stays immutable; schema3 independent
copy and exact source snapshot, locked revision/hash publication. First module/API
RED then10 GREEN; added concurrent instances and orphan snapshot failure tests.
Browser RED missing tab, then fixed select accessible names. Prior26 preserved;
extended36 GREEN, then added failed-load retry RED -> restore displayed identity.
Final full147 tests (146PASS/1knownskip) on both Python; browser37 before final
notice-recovery refinement. Resource55 metadata/YAML unchanged.
Ruling: source snapshot may survive a failed review publication; retain it instead
of deleting provenance. No cross-file crash-transaction claim. New copy keeps
worker/queue recovery independent; extra disk per review is accepted.
Ruling: old dataset consumer compatibility is verified without claiming segmented
C2C010 completion. Same checkout/C2C review loop and existing Windows settings.
Await independent whole-task review before publication.
