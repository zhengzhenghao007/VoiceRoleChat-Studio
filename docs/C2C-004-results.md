# C2C-004 execution report

Date: 2026-10-25 (Australia/Sydney). Baseline: 5ec7d7a.
Status: PASS. ChatGPT independently reviewed the implementation and execution
outputs in iterations 1 and 2, accepting the final JSON-depth hardening on
2026-10-25. It inspected recorded evidence rather than rerunning the commands.

## Delivered behavior

- GET `/api/tts/service`, POST `/api/tts/service/start` and `/stop` return typed
  state/managed/pid/detail responses. HTTP 409 conflict, 503 unavailable/start
  failure, 504 startup/cleanup timeout. Existing routes are retained.
- Read-only loopback OpenAPI probe, no proxy or redirects, 1 MiB response bound,
  socket deadline including delayed headers and trickling bodies; verifies POST
  `/tts`, GET `/set_gpt_weights`, GET `/set_sovits_weights`. Compatibility is not
  authentication, checkpoint loadability or synthesis acceptance.
- Explicit start only; no import/startup model loading. CPU, full precision,
  v2Pro private JSON configuration and log under ignored outputs/tts-service.
  Shell-free argument array, hidden Windows child, configured local resources,
  offline environment. Upstream configuration is never rewritten.
- Nonblocking lifecycle lock rejects concurrent start/stop; a separate guard
  protects ownership and status. Singleton construction is serialized too.
- Only a retained Popen handle can be terminated; no external control endpoint,
  name/port/PID-based kill. External listeners cause 409. Cleanup uses bounded
  terminate/kill waits, retains a live handle if cleanup fails, and closes logs
  after exit. FastAPI normal lifespan shutdown closes the cached manager.

## Actual commands and outcomes

```powershell
python -m unittest discover -s tests -p test_tts_service.py -v
python -m unittest discover -s tests -p test_tts_api.py -v
python -m unittest discover -s tests -v
& 'C:\Users\zsh\anaconda3\envs\gpt-sovits\python.exe' -m unittest discover -s tests -v
git diff --check
```

- Initial RED: service module absent; API RED: api.tts absent.
- Regression RED: status reaped a startup child before the startup loop finished.
  Fix: startup exclusively handles its own exit/cleanup; status reports starting.
- Regression RED: simultaneous cache misses constructed two ownership managers.
  Fix: lock singleton construction independently of each manager's lifecycle lock.
- Intermediate full runs failed the launcher HTTP test after its client timeout
  matched the default 2-second absent-service probe. Only the two identified
  test-owned launcher children were stopped. The fixture now explicitly uses a
  0.1-second probe timeout below its 2-second HTTP client timeout; product defaults
  are unchanged. Both failed outputs are retained in execution records.
- Post-review boundary check: deeply nested JSON already failed safely on
  Python 3.12 but raised RecursionError on 3.10. A real failing 3.10 case was
  captured, then the probe exception boundary was extended to report unavailable.
  The regression case is retained in the response-validation test.
- Full existing Python 3.12.8 and Conda Python 3.10.20 suites: 44 tests each,
  43 pass, 1 Windows symlink privilege skip, exit 0 (12.333s / 20.058s).
  Known dependency deprecation
  warnings remain. Final output is recorded through C2C execution records.
- Tests cover compatible/incompatible/malformed/oversized/redirect/slow HTTP,
  refused connections, external service conflicts, required resource failures,
  early exit, startup timeout, repeated/concurrent start, terminate/kill fallback,
  failed cleanup ownership retention, API errors, singleton and shutdown.
- A real temporary standard-library HTTP child launches via the configured
  interpreter/CLI, becomes ready, and exits after close. Fake weights are empty
  placeholders. This is process integration, not a GPT-SoVITS inference run.
- A real run.py backend starts from an unrelated temporary CWD; health and
  service status/stop endpoints are queried over actual HTTP with an absent
  inference service. No model is loaded.

## Preservation and limits

The existing upstream tts_infer.yaml SHA256 remains
`B9481D695F777839ABC5DA1D14B913BACEA3A9DA556B9E0CA0277CCFA85E9AF5`.
55 original resource files are checked against the persisted C2C-002 metadata
baseline (path/size/mtime ticks, not full content hashes).
No package installation, model download, GPU training, real checkpoint startup
or speech synthesis was performed.

Single backend process only. Normal shutdown is covered; a hard crash may leave
an orphan and there is no PID recovery. The manager assumes upstream remains
one process; it does not terminate grandchildren. Socket/resource diagnostics
do not validate ML dependencies or model bytes. Per-run configs/logs are retained
for diagnosis and are excluded from Git.
The preflight port check and the child's bind have a race window: compatibility
probing cannot prove the response comes from the owned child. Independent
review accepted this limitation for the current local adapter; real integration
should cover it before stronger process/readiness identity claims.

## Changed files

README.md; backend/app.py; backend/config.py; backend/api/tts.py;
backend/schemas/tts.py; backend/services/tts_service.py; tests/test_startup.py;
tests/test_tts_api.py; tests/test_tts_service.py; docs/PROJECT-ROADMAP.md;
docs/C2C-004-results.md;
docs/superpowers/specs/2026-10-24-c2c-004-service-management.md;
docs/superpowers/plans/2026-10-24-c2c-004-service-management.md.

NEXT_EXPECTED_STEP: authorized GitHub publication, then separately plan C2C-005,
serialized model selection and minimal text synthesis with a reference
audio fixture and real playable WAV acceptance.
