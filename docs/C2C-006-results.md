# C2C-006 execution report

Date: 2026-10-25 Australia/Sydney. Baseline e1a5d48.
Status: PASS. ChatGPT independently inspected current code and recorded RED/
green outputs on 2026-10-25; no required fixes. It did not rerun the commands.

## Behavior

Extracted CharacterCreate/Response contracts into schemas/character.py while
retaining their imports from api.characters for existing callers. Existing
create/list/detail routes remain; PATCH adds partial editing, revision checks,
full voice-configuration replacement or explicit null clearing. Empty patches,
unknown/read-only fields, null required fields and invalid revisions are rejected.

New JSON records are schema 2/revision 1. Legacy records view as schema 1/revision
0 without disk writes; explicit edit merges original unknown fields, preserves
creation time and legacy training metadata, and atomically migrates to schema 2.
Declared schema 2 records must have their required fields, correct types and
positive revision; corrupt records are diagnosed rather than filled silently.
Future schemas return 409 and cannot be downgraded. UUID/resolved-path checks
protect file reads/writes. Non-character backup directory names are ignored.

One module-level RLock covers read/check/merge/write across CharacterService
instances. Adjacent unique temporary files, flush/fsync and os.replace prevent
partial JSON; failed create/update never publishes incomplete content. Normal
reads do not lock or rewrite immutable snapshots.

Shared VoiceSettings retains C2C-005 request semantics; version 1 voice bindings
reuse its model/reference validation without creating a manager, probing a
service, switching weights, generating audio or downloading. Only requested
new bindings are validated on edit; omitted bindings are preserved.

POST /api/characters/{id}/synthesize accepts only text, snapshots saved voice
settings and delegates to the existing serialized synthesis adapter. Missing
binding returns 409; deleted reference/model resources retain precise errors.
Concurrent role editing does not alter already-started synthesis.

## Actual verification

```powershell
python -m unittest discover -s tests -p test_characters.py -v
python -m unittest discover -s tests -p test_character_api.py -v
python -m unittest discover -s tests -v
& 'C:\Users\zsh\anaconda3\envs\gpt-sovits\python.exe' -m unittest discover -s tests -v
git diff --check
```

- Initial RED: schemas.character and API dependency absent.
- Boundary RED: an unrelated backup directory caused a list error, and explicit
  null expected_revision was accepted. Filter canonical character directory
  names and reject explicitly null revisions; regression tests retained.
- Final Python 3.12.8 and Conda Python 3.10.20: 77 tests each, 76 pass/1 known
  Windows symlink privilege skip, exit 0. Dependency deprecations remain.
- Temporary-store tests cover create/edit/list/detail/reopen, lossless legacy
  migration, no read-time write/mtime changes, future/corrupt/incomplete schema,
  concurrent cross-instance optimistic locking, atomic create/update failure,
  path containment, omitted/cleared voices and schema validation.
- API tests exercise actual temporary JSON storage plus fake upstream HTTP for
  role voice synthesis; verify frozen request settings during concurrent edits,
  missing/deleted model/reference behavior and exact output retrieval.
- Production character dependency test proves binding never instantiates
  api.tts.TTSService. Existing real legacy-role list/detail and full application
  import/launcher tests still pass. No actual user role is created or edited.
- Original 55 resource paths/sizes/mtime ticks remain unchanged; original upstream
  YAML SHA256 remains B9481D695F777839ABC5DA1D14B913BACEA3A9DA556B9E0CA0277CCFA85E9AF5.
  Large resource bytes were not rehashed. No training, download or installation.
- Real CPU synthesis was established in C2C-005; this task verifies character
  delegation with a fake upstream, without claiming a new real-model run.

## Changed files and remaining boundaries

Modified: backend/api/characters.py; backend/schemas/tts.py;
backend/services/synthesis_service.py; README.md; docs/PROJECT-ROADMAP.md.
Added: backend/schemas/character.py; backend/services/character_service.py;
tests/test_characters.py; tests/test_character_api.py; this report;
docs/superpowers/specs/2026-10-25-c2c-006-character-voices.md;
docs/superpowers/plans/2026-10-25-c2c-006-character-voices.md.

Single backend process remains required. expected_revision is optional, so
clients omitting it explicitly accept last-successful-update behavior. Binding
validity is checked at save time and again for synthesis, not continuously.
There is no role deletion, database, UI integration or voice auto-conversion.
Next: independent review and authorized publication, then C2C-007 minimal real
frontend workbench for characters, models, reference configuration and audition.
