# C2C-002 execution report

Date: 2026-10-22 (Australia/Sydney). User approved the bounded registry design.
Status: PASS. The initial ChatGPT submission encountered a page error. On resume,
the same conversation recovered; the unsent report was submitted without rerunning
implementation. ChatGPT independently inspected current code, tests, reports and
four execution outputs and returned DONE / REVIEW PASS on 2026-10-22. This review
inspected recorded execution evidence; it did not independently rerun the suite.

## Changes

- `backend/services/model_service.py`: retain unique legacy IDs; assign stable
  SHA-256-based expanded IDs to collisions; reject ambiguous legacy lookup.
  Discover direct `models/<job>/manifest.json` exports with a 1 MiB size limit,
  JSON/identity/type/path checks and diagnostic logging. Detect missing weights
  without claiming inference readiness. Deduplicate only when both recorded
  source weights match the same existing normalized training experiment.
- `backend/api/models.py`: translate ambiguous lookup into HTTP 409; unknown IDs
  remain 404 and expanded IDs remain queryable.
- `tests/test_model_registry.py`: disposable-fixture tests for collisions,
  compatibility, export-only discovery, incomplete exports, source-based merging,
  malformed/oversized manifests, relative paths, Windows relocation, escape
  prevention, repeated refresh and distinct same-name models.
- `docs/PROJECT-ROADMAP.md`: mark implementation pending independent review.
- This report. Existing app, schemas, smoke tests and all model data retained.

## Identity and discovery policy

Unique current IDs `80a9a003` and `2ff64c64` remain unchanged. When multiple
identities share a short ID, every affected record gets `<short>-<digest>`;
the legacy short lookup returns 409 rather than silently selecting a record.
The digest input is the normalized training key or exported job directory ID,
not absolute location, mtime or scan order. Collision suffixes start at 8 hex
digits and expand when needed. Adding/removing a conflicting identity can
change whether a model needs an expanded ID; permanent persisted aliases are
outside this task.

Only actual export files within the corresponding job directory are returned.
Existing Windows absolute export paths can be relocated by matching the exact
`models/<job>/<file>` suffix; this remaps to a local export file and never reads
the old external location. Source paths are identity references only; the
registry never opens arbitrary manifest source paths. Relative source paths or
relocated Windows paths must match known project-local training files. Exports
without confirmed matching sources remain separate, even when names coincide.
Existing training records retain their original chosen paths and metadata.

Invalid manifests are skipped with warnings; at least one valid existing weight
is required to return an exported record. A missing companion gives incomplete.
`ready` still means paired files, not successfully loaded or synthesized models.

## Actual verification

Commands from repository root:

```powershell
python -m unittest discover -s tests -p test_model_registry.py -v
python -m unittest discover -s tests -v
& 'C:\Users\zsh\anaconda3\envs\gpt-sovits\python.exe' -m unittest discover -s tests -v
python 'C:\Users\zsh\.codex\visualizations\2026\10\22\01a161c2-4f3c-7a12-a0ac-2e48a0e427b0\c2c_002_runtime.py'
git diff --check
```

- Before implementation: 12 test methods, failures=11 (including subtests),
  errors=2, skipped=1; failures reproduced missing registry behavior.
- Final Python 3.12: 19 tests, 18 passed, 1 skipped, exit 0.
- Final Conda Python 3.10: 19 tests, 18 passed, 1 skipped, exit 0.
- Real symlink creation requires an unavailable Windows privilege, so that OS
  test is skipped. A separate injected resolved-path escape test passes; it
  exercises containment logic but does not replace OS-level symlink validation.
- Real Uvicorn process on ephemeral loopback port 50544: root, health, OpenAPI,
  characters, models, both model details, refresh and training list returned 200.
  The harness stopped its own process afterwards.
- Actual model list still contains exactly 2 records with original IDs/paths;
  the real exported copy is merged rather than duplicated.
- Persistent pre-execution baseline comparison: 55 resource files have identical
  names/sizes/mtime ticks; only the two intended pre-existing backend Python
  source files have changed hashes. Source hashes for app/schema are unchanged.
  Large model contents were not fully hashed or loaded.
- `git diff --check`: exit 0. No downloads, GPU training, asset writes, destructive
  Git operations or dependency installations.

Local evidence files are under the task artifact directory named in the runtime
command: `c2c-002-red.txt`, `c2c-002-python-final.txt`,
`c2c-002-conda-final.txt`, `c2c-002-runtime.txt`, `c2c-002-baseline.json`.
Test outputs are also recorded through C2C for independent review.

## Remaining boundaries

Real symlink test needs an appropriate Windows environment. Dependency
deprecation warnings from Starlette/httpx and multipart remain unchanged.
No checkpoint loadability, TTS output or training run was verified. Existing
recursive training-directory pairing remains based on normalized filenames;
this task does not redesign the training artifact format or validate model bytes.

NEXT_EXPECTED_STEP: independent review of C2C-002. If accepted, C2C-003 environment
configuration and standard startup baseline, followed by the GPT-SoVITS adapter.
