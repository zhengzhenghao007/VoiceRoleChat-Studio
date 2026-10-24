# C2C-008 Audio Library Implementation Plan

> Inline superpowers:executing-plans; ChatGPT independent whole-task review.

**Goal:** Validate and manage audio assets, generate safe reference WAV clips,
and preview/import browser recordings without changing original files.
**Architecture:** Streaming staged upload, bounded isolated PyAV worker, atomic
asset metadata, canonical retrieval, existing plain-JS Audio workbench tab.
**Tech Stack:** Existing Python/FastAPI/PyAV, native MediaRecorder/DOM, Playwright.
**Spec:** docs/superpowers/specs/2026-10-25-c2c-008-audio-library.md.

## Constraints/review focus

No downloads/installs/training/ML; no writes to original user assets in tests.
Bound memory/time/decoded duration, disable external media protocols, preserve
legacy upload consumers, reject path escape and stale metadata, and release
microphone/object URL resources. Reference clipping never replaces originals.

## Task 1: Worker and validated storage

Files: backend/workers/audio_worker.py, backend/services/audio_service.py,
backend/services/file_service.py, backend/schemas/audio.py, backend/config.py,
backend/requirements.txt, tests/test_audio_library.py.
Interfaces: AudioService.save_upload/get/list/inspect/create_reference/audio_path;
existing async save_uploaded_audio wrapper; worker JSON metadata and exit codes.

- [x] RED tests: actual WAV upload/metadata/read, invalid bytes/truncation/size,
  no unbounded read, helper compatibility, worker timeout and missing dependency,
  metadata and canonical paths, legacy list, clip exact PCM and rollback.
- [x] Implement forced-format local decode worker with process deadline and
  stream/resource limits, normalized reference clip, and atomic publication.
- [x] GREEN python -m unittest discover -s tests -p test_audio_library.py -v.

## Task 2: APIs and audio/recording UI

Files: backend/api/voices.py, frontend/index.html/app.js/style.css,
tests/test_audio_api.py, tests/studio_browser.py, tests/test_startup.py.
Interfaces: preserve upload; add library/detail/audio/inspect/reference routes;
Audio tab, local original playback, clip-to-draft, recording preview/import.

- [x] RED then implement API mappings and library/clip behavior using temp stores.
- [x] Add UI safe rendering, validation/worker busy states, reference selection,
  explicit recording with preview/import, track/object URL cleanup and limits.
- [x] Extend browser fixture to isolate AudioService and synthetic recording;
  validate no real mic/data/model usage and prior workbench regression.

## Task 3: Delivery evidence

Files: README.md, docs/PROJECT-ROADMAP.md, docs/C2C-008-results.md.

- [x] Both full Python suites, actual browser checks and updated screenshots;
  optional read-only inspect of an existing original MP3 without sidecar writes.
- [x] Verify original resource metadata/YAML, record failures/green outputs and
  independent ChatGPT review; resolve bounded findings and publish authorized Git.

## Ledger

- Existing av 18.0.0 (Python 3.12) and 17.1.0 (Conda 3.10) found, no install.
- Preflight: upload helper feeds transcription, clip filenames feed C2C-005
  reference path validation, browser fixtures must redirect upload/metadata roots.

## Execution ledger

- PLAN refinements applied: local forced demux, small JSON protocol, frame/sample
  budgets, worker deadline/owned cleanup, bounded streaming upload and closes,
  metadata rollback/stale fallback, independently checked new PCM clip, safe
  playback and explicit recording state/resource lifecycle.
- Codex ruling: direct absolute worker script/current interpreter for cwd safety;
  audio.js ES module keeps the existing plain-JS app bounded. File+sidecar is
  exception-safe publication, not a cross-file crash transaction.
- Final: 95 tests on each Python (94 pass/1 known Windows skip), Chromium 26
  checks PASS. Original 55 resource metadata/YAML hash preserved. See results.
- Actual old .mp3 is M4A/AAC; readonly diagnostic passed with correct demuxer.
  Preserve source and report, never silently rename or rewrite user assets.
