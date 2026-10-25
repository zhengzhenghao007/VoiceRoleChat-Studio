# C2C-010 Implementation Plan

Spec: matching specs/2026-10-25-c2c-010-segmented-datasets.md. Inline TDD, user
continuous-development authority and independent C2C review retained.

1. RED pure slicing tests; schemas/segmented_dataset.py and workers/dataset_worker.py.
   Stream local decode/resample and deterministic exact PCM windows, quality metrics,
   bounded private candidate protocol; keep audio/Whisper workers unchanged.
2. RED storage/API tests; services/segmented_dataset_service.py, api/datasets.py.
   Review/source snapshots, owned worker deadline/cleanup retention, manifest/labels,
   no-overwrite staging publication, read-only list/details, minimal legacy guards.
3. RED browser dataset action; frontend/datasets.js + correction integration and
   saved-review gate. Use temporary all roots; actual lightweight codec worker,
   never training. Prior37 workflows remain; visual QA desktop/mobile.
4. Dual Python full suites, real temp multi-clip CPU evidence, resource protection;
   README/roadmap/results -> independent review -> required fixes -> GitHub upload.

Preflight: review revision/hash and canonical audio -> dataset snapshot; fixed
clip names/final paths -> labels/manifest; immutable prepared datasets -> future
training C2C011 (legacy training rebuild path is explicitly not used this task).
No reset, deletion of existing resources, installation, download or GPU training.

## Execution ledger

Local implementation and tests complete; independent review pending. Final dual Python suites each166 tests/165pass/1existing permission skip; native browser41checks and real8.064s-source HTTP slicing both environments pass. Final review lock covers freshness check and directory publication. Known job source hash and decoded duration are verified. Cleanup retains owned worker references on failure. Legacy build only received path/annotation guards. Two additional minimal regressions fixed: shared safe-path resolver translates resolution exceptions, and TTS watchdog-fired event prevents early Windows timer abort misclassification. See docs/C2C-010-results.md for actual RED failures and frontend TDD correction. Existing55resources and upstream config unchanged. No training/downloads/installations.
