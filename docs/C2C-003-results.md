# C2C-003 execution report

Date: 2026-10-22 (Australia/Sydney). Baseline: dd0bfb6, clean working tree.
Status: PASS. ChatGPT independently inspected current code, diffs, this report
and four execution records, accepting the launcher/configuration changes and the
two justified registry integration adjustments on 2026-10-22. The review examined
recorded real execution evidence; it did not independently rerun commands.

## Deliverables

- `run.py`: standard root entry point; defaults to loopback port 8000. Resolves
  backend imports from its own location, not caller CWD. `--check` and
  `--check --json` inspect dependencies/configuration without starting services,
  loading ML modules, installing packages, downloading models or creating data.
- `backend/config.py`: preserves default values; adds environment overrides for
  GPT_SOVITS_ROOT/PYTHON/VERSION/GPU and Whisper model/device/compute type.
  Relative installation/interpreter paths resolve against the repository root.
  Empty/control-character values, unsupported version/device/compute type and
  invalid GPU index are rejected with actionable configuration errors.
- `backend/requirements-dev.txt`: includes runtime requirements and explicitly
  declares the TestClient dependency httpx==0.28.1. No packages were installed.
- `tests/test_startup.py`: subprocess-isolated configuration/CLI tests, light
  diagnostic tests, missing-data checks and real HTTP startup from another CWD.
- README and roadmap updated with actual behavior and verification boundaries.

Two small integration changes were necessary beyond the initial suggested file
scope: `backend/services/model_service.py` uses the configured GPT-SoVITS tool
root for its default training-weight directories; `backend/api/models.py` obtains
the data root from config rather than requiring a local tool checkout to exist.
The failing custom-root test demonstrated that otherwise training would use one
installation while registry discovery silently used another. Existing default
IDs, schemas and response semantics remain intact. Exported models and all other
data still live under the original repository root. Exact known absolute source
paths in a configured external tool root can participate in deduplication;
arbitrary manifest source files are not opened.

## Diagnostic contract

```powershell
python run.py --check
python run.py --check --json
python run.py --host 127.0.0.1 --port 8000
```

- Exit 0: required checks pass; optional training resources may have warnings.
- Exit 1: required dependencies, Python version or configuration are invalid.
- Exit 2: invalid CLI options or port. `--json` requires `--check`.
- JSON has `ok`, `project_root`, `checks`; each check has name/status/message.
- Dependency presence uses find_spec; this does not prove import-time native
  libraries can load. Path checks do not establish GPU access or weight validity.
- Data directories are created only by normal app startup, never diagnostics.
- Original machine-specific Python fallback is retained for compatibility;
  new machines should explicitly set GPT_SOVITS_PYTHON. No implicit .env reader.
- v2Pro only; one numeric GPU index only. Multi-GPU syntax is deliberately
  rejected because the existing preparation and training entry points consume
  that setting differently. No Worker rewrite or hardware execution this task.

## Actual verification

```powershell
python -m unittest discover -s tests -p test_startup.py -v
python -m unittest discover -s tests -v
& 'C:\Users\zsh\anaconda3\envs\gpt-sovits\python.exe' -m unittest discover -s tests -v
python run.py --check --json
git diff --check
```

- Initial red: missing root launcher caused import error in new test module.
- Intermediate: 8 startup methods, 7 passed and custom tool-root registry lookup
  failed. Fixed only the integration points described above.
- Final Python 3.12.8: 30 tests, 29 passed / 1 skipped, exit 0.
- Final Conda Python 3.10.20: 30 tests, 29 passed / 1 skipped, exit 0.
- Skip remains the real Windows symlink test from C2C-002 (missing OS privilege).
- Both environments actually launch `run.py` in an unrelated temporary CWD,
  obtain HTTP 200 with healthy JSON, and stop only their own server process.
- Existing root/health/OpenAPI/character/model list/detail/refresh tests pass.
- Default installation, interpreter and Whisper settings retain prior values.
- Tests cover relative config paths, external tool roots, malformed values,
  invalid ports, missing dependency specs, missing data without creation,
  unsupported Python reporting and no heavy imports in diagnostic mode.
- Actual `python run.py --check --json` exits 0 with valid JSON on this machine.
- 55 existing resource files were compared with the previously persisted local
  baseline: names/sizes/mtime ticks unchanged. Large contents were not hashed.
- `git diff --check` passes. No GPU training, inference, package installation or
  model download occurred. Full clean-environment installation is not verified.

Evidence is recorded through C2C and available locally in the task artifact
directory under `c2c-003-red.txt`, `c2c-003-first.txt`,
`c2c-003-python-final.txt`, `c2c-003-conda-final.txt`.

## Remaining boundaries

Runtime/transitive dependencies are not fully locked. Existing Starlette/httpx
and multipart deprecation warnings remain. Diagnostics do not test external
Python imports, GPU availability, actual checkpoint loading or speech quality.
The default Conda interpreter remains machine-specific until explicitly configured.

NEXT_EXPECTED_STEP: independent review, then user-authorized GitHub publication.
After acceptance, plan C2C-004 GPT-SoVITS local adapter and availability detection.
