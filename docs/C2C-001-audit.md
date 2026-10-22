# C2C-001 audit and startup verification

Date: 2026-10-22 (Australia/Sydney). Branch: main. HEAD: aa35363.
Result: PASS for the bounded startup/API audit; model loading, synthesis and GPU training remain unverified.

## Baseline and changes

Initial working tree: modified `backend/app.py`; untracked `backend/api/models.py`,
`backend/schemas/model.py`, `backend/services/model_service.py`.
The existing app and schema were left unchanged. No commits, resets, cleanup,
downloads, dependency installations or training starts were performed.

Production changes this iteration:

- `backend/services/model_service.py`: import `schemas.model`, matching all other
  backend imports. Previously `cd backend; python -c "import app"` failed with
  `ModuleNotFoundError: No module named 'backend'`. With the repository root also
  on sys.path, duplicate schema classes instead caused Pydantic model-list errors.
- `backend/api/models.py`: register `/refresh` before `/{model_id}`. Previously
  GET `/api/models/refresh` returned 404, treating `refresh` as a model ID.
- Added `tests/test_backend_smoke.py`: offline regression and fixture checks.
- Added this report.

## Actual commands and results

Run from repository root unless stated otherwise.

| Command | Result |
| --- | --- |
| `git status --short`; `git rev-parse --short HEAD`; `git diff -- backend/app.py` | Confirmed baseline above; app diff still matches initial diff after execution. |
| `python -c "import app"` (cwd `backend`) before fix | Failed: inconsistent schema import. |
| `python -m unittest discover -s tests -v` before fix, normal user environment | 5 tests: 1 passed, 2 failures, 2 errors. Failures reproduced import, schema identity, refresh dispatch. |
| Same unittest command after fix, Python 3.12.8 | 5/5 passed, 2.262 seconds. |
| `& 'C:\Users\zsh\anaconda3\envs\gpt-sovits\python.exe' -m unittest discover -s tests -v` | 5/5 passed, Python 3.10.20, 9.091 seconds. |
| `python C:\Users\zsh\.codex\visualizations\2026\10\22\01a161c2-4f3c-7a12-a0ac-2e48a0e427b0\c2c_001_runtime.py` | Final run exit 0: real Uvicorn startup, HTTP checks, resource metadata comparison. |
| `git diff --check` | Exit 0. |

The unittest checks import every backend API/service/schema/worker module, import
the application in a subprocess from `backend`, validate root/health/OpenAPI,
validate characters and real model responses against Pydantic schemas, fetch each
model detail, and check unknown IDs return 404. Temporary fixtures cover missing
and empty directories, single-sided weights, stable IDs, explicit IDs, pairing,
epoch/step selection and removal of a selected weight. Fixture API responses are
also validated. No real weight is deleted or loaded.

Real server command (cwd `backend`):

```powershell
python -m uvicorn app:app --host 127.0.0.1 --port 60675
```

The harness chose an available port, started its own server and stopped only that
process afterwards. `/`, `/health`, `/openapi.json`, `/api/characters`,
`/api/models`, `/api/models/refresh`, both model details and `/api/training` all
returned HTTP 200. Counts: 1 character, 2 models, 6 training jobs.
Health body: `{"status":"healthy"}`.

Environment-only failures: sandbox TestClient execution stalled in Windows
`socket._fallback_socketpair` before requests; a 20-second faulthandler run located
the stall. Those runs were stopped and tests rerun outside the sandbox. A temporary
baseline file was unavailable across environments, so the first runtime harness
ended with FileNotFoundError *after* successful HTTP checks. The harness was fixed
to compare source hashes/resource metadata within one run and rerun successfully.
An exploratory fixture probe also hit sandbox temporary-directory permissions and
was rerun successfully outside the sandbox. These failed attempts are not passes.

## Resources and observed models

All config paths resolve on this machine, including the configured Conda Python,
BERT and HuBERT directories, SV checkpoint, v2Pro S2G/S2D and S1 checkpoint.
BERT includes config/tokenizer and a 651,225,145-byte weight; HuBERT includes
config/preprocessor and a 188,811,417-byte weight.

- GPT training weights: 6 files; SoVITS training weights: 4 files.
- Discovered `80a9a003`: `test_character_auto_v3`, GPT e15 + SoVITS e8/s400,
  status `ready`, language null.
- Discovered `2ff64c64`: `test_character_japanese_v1`, GPT e15 + SoVITS e8/s400,
  status `ready`, language ja.
- Four dataset directories (13 files), two transcript files, four uploaded files.
- `models/`: one exported GPT/SoVITS pair plus manifest (5 total files).
- Six training records: 3 completed, 2 failed, 1 queued. These are saved states,
  not evidence of currently running or reproducible training.
- Final runtime check compared all 55 resource files, including directory marker
  files, in characters/datasets/models/training_jobs/transcripts/uploads/voices
  and the two trained-weight directories: names, sizes and nanosecond mtimes
  unchanged across that run; backend source hashes also unchanged across that run.
  This is not a full content-hash audit of all large weights or an end-to-end
  cryptographic comparison from the start of the entire session.

## Remaining issues and next steps

1. `backend/services/model_service.py`, `_extract_name_and_id`/`get_model`:
   explicit 8-hex IDs are not collision-safe. Temporary fixture
   `one_deadbeef-e1.ckpt` + `two_deadbeef-e1.ckpt` produced two models with ID
   `deadbeef`; lookup returned only `one`. No collision occurs in current real
   models. Next: define deterministic collision behavior and add a regression.
2. Same service, constructor/list_models: scans only v2Pro training directories;
   `models/<job_id>/manifest.json` and exported-only models are not discovered.
   Next: define canonical identity and manifest/weight deduplication before adding
   discovery sources. Do not accidentally duplicate the existing exported pair.
3. Same service: `ready` means two filenames were found, not valid checkpoints.
   Empty fixture weights also become ready by design; compatibility, loadability
   and actual synthesis are unverified. `created_at` is the latest selected file
   mtime, not a training creation timestamp. Document/clarify these semantics.
4. `backend/config.py`: configured Python path is machine-specific; requirements
   are unpinned. Backend imports consistently expect `backend` on sys.path:
   use cwd `backend` or Uvicorn `--app-dir backend`; package-mode startup from
   the root is not supported by current imports. Avoid a broad import rewrite now.
5. `backend/requirements.txt`: httpx is installed locally but not declared for
   tests; Python 3.12 reports a Starlette httpx deprecation, while the Conda
   environment reports a multipart deprecation. Next: record a tested development
   dependency set separately, without changing runtime dependencies blindly.
6. `training_jobs/`: two historical failed jobs and one queued record require a
   separate read-only failure/recovery audit before starting training. Existing
   pretrained weights were checked for presence/size only; no GPU test was run.

NEXT_EXPECTED_STEP: C2C-002, define and test collision-safe model identity and
manifest discovery/deduplication, then implement only that bounded change after
independent review. This iteration stops here.
