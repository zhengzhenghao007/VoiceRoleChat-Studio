# C2C-009A Implementation Plan

Inline executing-plans / TDD; autonomous user authorization retained.

1. RED tests for offline constructor/missing model, canonical path/escaped
   symlink, generic inference errors, atomic preservation, invalid timings,
   serialized lazy segments and async upload thread offload.
2. Minimal transcription_service/schema/API changes, keeping old response and
   transcript path compatible; GREEN targeted tests.
3. Dual Python full regressions, real offline CPU API with temporary root,
   original resource metadata/YAML preservation. No download/install/training.
4. Record evidence/docs, independent ChatGPT review, fix required findings,
   commit/push to authorized GitHub. Do not claim full C2C-009 completion.

Codex ruling: user asked continuous execution; no repeat design confirmation.
Review brain plans/reviews; Codex retains scope and execution ownership.

## Evidence ledger

- PLAN APPROVED WITH REFINEMENTS received; contracts applied. Codex retains
  installed Whisper language set for backward compatibility; dataset languages
  unchanged. Wider inference/publication lock chosen to preserve request order.
- Initial 9-test RED: 7 failures/1 error; initial GREEN 9/9. Added metadata RED:
  silent out-of-duration segment incorrectly accepted, fixed and covered.
- Final both environments: 107 tests, 106 pass/1 known skip; actual offline CPU
  HTTP normal/upload 200 and missing local model 503, original WAV unchanged.
- No frontend changes or browser rerun, installs/downloads/training. Await review.
- Iteration 1 independent review required chronological starts across all rows.
  Added failing case then previous_start validation; equal starts accepted.
  Targeted 13 PASS; full 108 (107 pass/1 skip) on both interpreters. Await final
  Iteration 2 review before publication; actual CPU evidence need not repeat.
