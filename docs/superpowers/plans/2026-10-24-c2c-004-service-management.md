# C2C-004 Service Management Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task in the current chat. Codex executes; ChatGPT independently reviews.

**Goal:** Manage and inspect a local GPT-SoVITS service without taking ownership of unrelated processes.
**Architecture:** A single-process manager owns an optional Popen handle, serializes lifecycle operations and probes the local upstream API. FastAPI exposes typed status/start/stop operations and releases owned resources on shutdown. No service starts during module import or ordinary backend startup.
**Tech Stack:** Python 3.10+, standard-library subprocess/threading/urllib, existing FastAPI/Pydantic, unittest.
**Spec:** `docs/superpowers/specs/2026-10-24-c2c-004-service-management.md` (user confirmed).

## Global Constraints

- 本轮不实现生成音频、训练或前端。
- 不修改上游安装、现有权重和训练产物。
- 启动业务后端时不自动启动推理服务。
- 工作室只停止自己启动且仍持有进程句柄的进程。
- 默认仅连接和绑定本机回环地址。
- 本轮默认 CPU，以避免隐式 GPU 占用。
- 多 Uvicorn worker 不受支持，README 必须说明单进程运行约束。
- No package installations, model downloads or arbitrary shell commands.

## Review Focus

- A reachable non-GPT HTTP service must not be called ready or stopped.
- A manually started GPT service must remain running after stop/shutdown requests.
- Slow startup and concurrent start/stop must not create orphaned or duplicate processes.
- Unexpected JSON, oversized responses and refused connections must remain bounded and diagnosable.
- Changing runtime paths must not rewrite upstream YAML or alter registry/character/training data.

## Task 1: Configuration and bounded readiness probe

**Files:** Modify `backend/config.py`; create `backend/services/tts_service.py`, `backend/schemas/tts.py`, `tests/test_tts_service.py`.
**Interfaces:** `ServiceStatus` includes state (stopped/starting/ready/unavailable/failed), managed: bool, pid: int|None, detail: str. `TTSService.status() -> ServiceStatus` performs a bounded read-only probe. No inference requests.

- [x] Write failing tests for no listener, expected OpenAPI routes, unrelated listener, invalid JSON, oversized body, timeout and loopback-only configuration.
- [x] Run `python -m unittest discover -s tests -p test_tts_service.py -v`; verify relevant failures.
- [x] Add validated port and positive finite timeout settings: `GPT_SOVITS_API_PORT=9880`, `GPT_SOVITS_REQUEST_TIMEOUT=2`, `GPT_SOVITS_START_TIMEOUT=120`, `GPT_SOVITS_STOP_TIMEOUT=10`. Fixed managed bind address 127.0.0.1; no per-request URL/command input.
- [x] Probe `/openapi.json` with redirects/proxies disabled, bounded read (1 MiB), checking POST `/tts` and GET weight-switch routes. Emit useful errors without upstream body dumps.
- [x] Rerun probe tests; absence of a service is a status result, not a backend import failure.

## Task 2: Owned process lifecycle

**Files:** Extend `backend/services/tts_service.py` and `tests/test_tts_service.py`.
**Interfaces:** `TTSService.start() -> ServiceStatus`, `stop() -> ServiceStatus`, `close() -> None`; typed service exceptions for conflict/timeout/start failure. Constructor accepts injectable process/probe/clock dependencies for isolated tests.

- [x] Add failing tests for already-ready unmanaged service, port conflict, early exit, deadline exceeded, repeat start, concurrent start/stop and bounded terminate/kill fallback.
- [x] Generate a private per-run JSON/YAML-compatible config under `outputs/tts-service/`, with `custom` v2Pro settings, CPU, is_half=false and configured absolute local weight/resource paths. Never edit upstream YAML. Validate required script/interpreter/config resources before spawning.
- [x] Invoke `[python, '-s', 'api_v2.py', '-a', '127.0.0.1', '-p', port, '-c', private_config]` in configured tool root with shell=false and hidden Windows process creation. Stream stdout/stderr to owned log file, not an undrained pipe.
- [x] Serialize lifecycle operations; track only the returned process handle. Poll readiness and process exit until startup deadline. If startup fails, terminate only that owned process and release log handles.
- [x] `stop` returns conflict for an unmanaged ready service; `close` never kills unmanaged processes. Stop/kill waits use configured bounds. Test children do not spawn grandchildren; document the upstream process assumption.
- [x] Run all lifecycle tests with fake services and controlled lightweight child processes; do not start real GPT-SoVITS automatically.

## Task 3: API, shutdown and delivery

**Files:** Create `backend/api/tts.py`, `tests/test_tts_api.py`; modify `backend/app.py`, README and roadmap; add `docs/C2C-004-results.md`.
**Interfaces:** GET `/api/tts/service`, POST `/api/tts/service/start`, POST `/api/tts/service/stop`; singleton manager dependency. Normal status HTTP 200; lifecycle conflict HTTP 409; startup unavailable/failure HTTP 503; timeout HTTP 504. Shutdown closes only owned service.

- [x] Write API tests for typed states, exception mappings, dependency isolation and shutdown ownership; run them failing.
- [x] Register the router and a FastAPI lifespan cleanup hook without changing existing routes or starting inference on startup.
- [x] Run `python -m unittest discover -s tests -v` and the same command using the existing GPT-SoVITS Python 3.10 environment. Retain the known OS symlink skip explicitly.
- [x] Verify real backend HTTP status operations against an absent/controlled local service; preserve resource metadata. Real GPT model startup, if attempted separately, must be identified as such and its own process stopped.
- [x] Document single-worker constraint, state semantics, timeouts, commands and current validation limits. Update roadmap only to verified status.
- [x] Record real commands/outputs, send EXECUTED via the restored ChatGPT project, resolve required task-local fixes, then mark complete after review.
- [ ] Under existing user authorization, stage only intended source/docs/tests and push a normal Git commit to the verified GitHub repository; exclude models/data/logs/private runtime configs.

## Plan review refinements (2026-10-24)

ChatGPT independently checked the design, plan, upstream api_v2.py and TTS_Config.
The following clarifications are part of this plan before implementation:

- Probe success requires a JSON object with a paths object, POST `/tts`, GET
  `/set_gpt_weights` and GET `/set_sovits_weights`. Similar paths/wrong methods
  are rejected. Use an overall probe deadline in addition to individual socket
  timeouts and the 1 MiB body limit. Readiness means compatible API only.
- No listener means unavailable; a successful explicit stop means stopped.
  An unmanaged compatible service has managed=false and pid=null. Start and
  stop return 409 when a live external service would otherwise be taken over.
- Start/stop use a nonblocking lifecycle operation lock: a concurrent operation
  during startup returns 409 rather than waiting behind a long startup deadline.
  Short state/handle updates are protected separately so status stays useful.
- Every run gets `outputs/tts-service/<run-id>/config.json` with exactly the
  private custom CPU/v2Pro fields described in Task 2; stdout/stderr go to its
  own log. Hash the existing upstream YAML before/after lifecycle integration.
- Startup timeout cleanup has a separate bounded terminate/kill deadline.
  Do not discard a live process handle if cleanup itself fails; report that
  failure and retain ownership so later cleanup remains possible.
- Normal shutdown cleans up owned children; hard crash/OS termination cannot
  guarantee cleanup. No PID-file recovery or external /control request.

These are refinements of the selected ownership/timeout design, not new product
features. Human plan confirmation is still required before writing product code.


## Execution ledger — 2026-10-25

- User confirmed this plan; continuing inline in the existing workspace under
  the prior permission to preserve this checkout and publish verified changes.
- Pre-flight: Task 1 schema/settings consumed by Task 2 manager and Task 3 API;
  exception mappings and lifecycle ownership contracts agree with the spec.
- Task 1: complete. Service-module RED observed; strict bounded probe tests GREEN.
- Task 2: complete. Owned lifecycle, timeout/kill/retained-handle tests GREEN;
  actual temporary standard-library child starts and closes. No ML imports.
- Task 3: API implementation complete. Missing-router RED observed; API GREEN.
  Found and reproduced startup status-reaping and concurrent singleton misses;
  minimal fixes passed regression tests. Full final verification and review
  evidence is in docs/C2C-004-results.md and the C2C execution output records.
- Ruling: use http.client instead of the plan's suggested urllib — its raw
  connection socket permits a total-deadline shutdown watchdog for trickle
  responses while inherently avoiding proxy/redirect handling — cost is one
  short-lived watchdog thread per probe.
- Ruling: native PowerShell ledger in this approved plan instead of POSIX helper
  scripts — execution host is Windows and no task checkout/scratch ledger was
  present — cost is manual progress bookkeeping; tests remain the same gates.
- Independent whole-change reviewer: ChatGPT in the existing project, as agreed.
- Final review: PASS, iterations 1 and 2, no required fixes. An additional
  Python 3.10 JSON-depth failure was reproduced and fixed before publication;
  final suites: 43 passed / 1 existing skip each (12.333s / 20.058s).
- Publication checkbox is intentionally pending in this pre-commit snapshot;
  verified remote commit and delivery outcome are reported in the final response.
