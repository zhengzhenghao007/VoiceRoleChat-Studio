# C2C-011A Implementation Plan

Goal: Remove destructive legacy preparation and consume verified prepared datasets.
Architecture: existing training entry points retained; focused training_dataset service validates prepared sources and legacy adapter uses safe exclusive build. User opts out of routine design questions; inline TDD/current checkout retained under existing authorization.

1. RED tests/test_training_safety.py covering existing dataset/log/model output preservation; implement exclusive directory creation/path guards in worker. No training command executed.
2. RED prepared dataset validation and TrainingRequest grammar/API tests. Add services/training_dataset.py; schema optional dataset_name/legacy alternatives, validate before job and worker. Hash/read only, fail closed on mismatches.
3. Dual Python regression; docs/README/roadmap and execution evidence, independent review; required fixes then publish.011B queue, cancellation, per-job input snapshot and lifecycle separately.

Execution ledger: approved plan refinements adopted; output directory exclusive mkdir, no rmtree in training worker, legacy builder root injection instead of duplicate implementation, strict schema2 full integrity validator, exclusive log file and early global-weight collision guard.12targeted tests and179full tests in each Python (178pass/1existing skip). All upstream commands intercepted; no GPU/Whisper/install/download.55resources/YAML unchanged. API real validation but Thread stubbed. Output conflict scenarios use distinct first8 job ID prefixes to avoid masking later conflict paths. External edit/shared global output races and daemon lifecycle remain explicitly011B.

Final review2 full suites: Python3.12 180tests/179pass/1skip31.550s; Python3.10 same43.859s. Ordinary builder cleanup default retained; training cleanup disabled explicitly.13targeted tests pass.
