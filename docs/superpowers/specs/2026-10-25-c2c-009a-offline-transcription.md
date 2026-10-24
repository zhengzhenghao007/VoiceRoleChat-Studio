# C2C-009A Offline transcription baseline

User delegated continued roadmap execution until quota; this is a bounded first
slice of C2C-009, not completion of jobs or segment editor.

## Goal and evidence

Existing synchronous transcription can download a model implicitly, exposes raw
exception text, blocks the async upload handler, and directly overwrites result
JSON. Establish an offline, safe, testable baseline before adding task lifecycle.
Readonly preflight with existing cached small/CPU/int8, local_files_only=True:
8.064-second Japanese audio transcribed in 3.188 seconds with expected sentence.
No model downloaded, original audio/result unchanged.

## Design

- Keep current POST response shape and existing transcript filename contract for
  downstream dataset consumers; use canonical AudioService path validation.
- Set local_files_only=True on WhisperModel. Missing/broken local model => 503
  with actionable generic local-resource guidance, no exception/path leakage.
  No automatic fallback download, provider changes or dependency installation.
- Serialize model use across inference and generator consumption with a process
  lock. Existing synchronous API runs in FastAPI worker; upload calls the same
  function through run_in_threadpool after validated upload.
- Persist complete valid result JSON through same-directory temporary file,
  flush/fsync/atomic replace; preserve prior result if inference/serialization/
  replace fails. Bound transcript path to configured real directory, reject
  symlink final paths. Original audio and old results never migrated on reads.
- Validate requested language before ML load; typed known language code or null.
  Validate finite nonnegative segment timing and duration before publication.
- TDD using temporary uploads/results and fake lazy model; actual offline CPU
  API evidence in isolated temporary store with a copy of existing short WAV.

## Limits and next slice

Single-process only. The existing API remains synchronous request/response;
thread offload is not cancellation or a hard inference timeout. Durable jobs,
owned subprocess timeouts/cancel/restart recovery and segment editor follow in
C2C-009B. No UI/architecture/training changes in this slice.
