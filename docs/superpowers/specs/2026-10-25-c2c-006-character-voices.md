# C2C-006 character editing and voice binding

The user authorized autonomous roadmap progress. Codex chooses to extend the
existing JSON storage rather than introduce a database or alter character IDs.
Read legacy records without rewriting them; migrate only on explicit editing.
No model loading, training, downloads or edits to original user records in tests.

## API and storage

Existing POST/GET /api/characters and GET /{character_id} remain compatible.
PATCH /{character_id} partially edits creation fields and optional voice_config.
Omitted voice stays unchanged; explicit null clears it. Other required fields
cannot become null/blank. Reject unknown/immutable fields. Optional
expected_revision provides optimistic concurrency (mismatch 409). An empty
patch is rejected 422. No delete API this task.

New characters persist schema_version=2, revision=1, created_at, updated_at.
Legacy records view as schema_version=1/revision=0 with voice_config=null;
PATCH preserves unknown legacy keys and created_at, writes schema_version=2
and increments revision under one process-wide lock. Future versions are
rejected with a diagnosable 409; malformed storage yields 500, never silent loss.
Adjacent temporary JSON and os.replace prevent partial writes. Canonical
32-hex character IDs and resolved path containment prevent file escape.

voice_config: version=1, model_id, reference_audio, prompt_text, prompt_lang,
text_lang; reuse synthesis field constraints. Validate model pair and reference
with the same C2C-005 rules before saving, without starting or probing the
inference process. Binding a model does not claim it was trained by the role;
keep legacy voice_file/model_status metadata intact.

POST /{character_id}/synthesize accepts only text (1..1000); snapshot the saved
voice settings and delegate to C2C-005. Missing voice=409; missing/deleted model
or invalid reference returns the existing precise error. No arbitrary TTS
parameters or path inputs in this route. Editing later cannot change an
already-started request's copied settings. Require explicit owned service start.

## Validation

Temporary character stores test creation/read/edit/restart, partial/null fields,
legacy migration without read-time writes, future schemas, corrupt JSON,
revision conflicts across service instances, failed atomic writes, ID/path and
symlink containment, binding validation and role synthesis delegation. Existing
real role/model files remain untouched. Run both full Python suites and retain
the known Windows symlink skip. ChatGPT independently reviews before the
user-authorized source/docs/tests push. No frontend work in this task.
