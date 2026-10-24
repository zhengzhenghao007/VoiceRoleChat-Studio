# C2C-006 Character Voice Implementation Plan

> Execute inline with superpowers:executing-plans; ChatGPT reviews the whole task.

**Goal:** Persist editable characters with safe versioned voice bindings.
**Architecture:** Extract existing character schemas/storage from its router;
atomic JSON service with process-wide editing lock, reused synthesis validation.
**Tech Stack:** Existing FastAPI/Pydantic and Python JSON/path/threading.
**Spec:** docs/superpowers/specs/2026-10-25-c2c-006-character-voices.md.

## Constraints/review focus

Preserve existing IDs, legacy fields, original user files, route compatibility,
and C2C-005 lock/timeout/CPU behavior. No training/download/install/UI rewrite.
Guard accidental erasure by null/omitted fields, concurrent lost updates,
future-schema downgrade, escaped JSON paths, and voice binding without inference.

## Task 1: Character schema and atomic persistence

Files: backend/schemas/character.py, backend/services/character_service.py,
tests/test_characters.py; extract shared VoiceSettings in schemas/tts.py and
add SynthesisService.validate_voice(settings) without network work.
Interfaces: CharacterService.create/get/list/update; CharacterError.status_code;
validated CharacterCreate/Patch/Response and VoiceConfiguration(version=1).

- [x] Write failing tests for schema/fields, legacy read/migration, persistence
  after service reconstruction, expected_revision, concurrent service instances,
  future schema, corrupt data, ID/path containment and atomic write failure.
- [x] Implement atomic storage and binding validation with exact spec defaults.
  Keep API imports CharacterCreate/Response available for existing callers.
- [x] Run python -m unittest discover -s tests -p test_characters.py -v; expect PASS.

## Task 2: Editing/binding APIs, role synthesis and delivery

Files: backend/api/characters.py, tests/test_character_api.py, README.md,
docs/PROJECT-ROADMAP.md, docs/C2C-006-results.md.
Interfaces: original API plus PATCH /api/characters/{id} and
POST /api/characters/{id}/synthesize; delegate frozen voice to SynthesisService.

- [x] RED: temporary-store API roundtrip, immutable/unknown fields, voice binding,
  cleared voice, conflict, and role synthesis through fake upstream HTTP.
- [x] Implement thin router with explicit errors/dependencies; no implicit service
  start and no writes to old records on list/detail.
- [x] Run both full suites; preserve original 55 resource metadata/YAML hash.
- [x] Document API, schema compatibility, revision contract and current limits.
- [x] C2C execution output review and bounded fixes; authorized push follows commit.

## Ledger

- Autonomous continuation uses existing architecture; no repeat human approval.
- Preflight: VoiceSettings inherited by synthesis/character configuration; storage
  validator must not call inference_session or instantiate a running process.

- ChatGPT PLAN approved with refinements: distinguish omitted/null PATCH values,
  shared cross-instance lock, no silent default repair for explicit schema 2,
  strict IDs/atomic create and update, no inference during binding, frozen voice.
- Tasks 1/2 local implementation complete: 16 added tests; full suites 76 passed
  and 1 known skip each (15.002s Python 3.12 / 23.679s Python 3.10).
- Ruling: ignore noncanonical backup-directory names during listing — these are
  not character IDs and should not turn a valid list into 404 — cost: manually
  renamed noncanonical role directories require restoration to their stored ID.
- Publication pending after whole-change independent ChatGPT review.
- Final review: ChatGPT PASS, no required fixes. Verified publication SHA is
  reported at delivery rather than in this pre-commit snapshot.
