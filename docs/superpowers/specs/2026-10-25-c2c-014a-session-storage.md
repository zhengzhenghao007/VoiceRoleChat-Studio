# C2C-014A：持久会话与消息基础

Goal: implement the durable foundation of014 independently of unavailable real LLM. No real inference, UI or translation yet.

Choose Python built-in SQLite for new sessions only, rather than appending loose message JSON or rewriting the whole repository storage. Transactions atomically append complete user/assistant pairs and increment optimistic revisions. Existing character/audio/training JSON remains unchanged. No third-party dependency.

Lazy storage sessions/studio.sqlite3, ignored byGit; startup and missing-store reads do not create it. Database user_version1; unknown/future/corrupt databases and future session records refused without automatic repair/rewriting. Canonical fixed root, UUID identities, parameterized SQL, no client-selected filesystem path. Existing symlink/reparse or multi-link database refused. Single local backend deployment; short SQLite transactions/busy timeout, no inference during transaction. No deletion/archive API in this slice.

Session snapshots include character id/revision/name/system_prompt/reply/translation languages, captured at create; subsequent role edits do not silently change old conversation context. Title≤120, session revision starts1. List/detail/rename APIs; expected_revision required for rename, stale409. GET messages exposes only complete persisted pairs. Internal append_turn requires UUID request_id, strict expected_revision, bounded user≤8000/assistant≤16000 characters, optional model identifier. Same request+identical pair is idempotent even after later revision; reused request with different content409. No public arbitrary assistant/message append API. Future014B owns generation and cancellation before atomic pair commit.

Bounds: ≤1000 sessions, ≤100 complete turns/session, pages1–100 and offset≤10000, modelid≤200, bounded strict session snapshot/schema on reads. This is a logical data budget, not OS disk quota. Busy/storage errors503, unknown schema409, missing404, capacity429, revision/request conflict409. Corrupt record surfaced diagnostically rather than silently omitted.

API /api/sessions: POST create(character_id,title); GET list(limit,offset); GET /{id}; PATCH /{id}(title,expected_revision); GET /{id}/messages. No contact with LLM or TTS. Runtime data retained locally; backups only when backend stopped, including any SQLite sidecars.

Tests: restart persistence, pair transaction rollback, idempotency/conflicts, concurrent writers, missing-store reads, future schema preservation, corrupt/path failures, API schema/status. DualPython regression/resource55/YAML preservation and independent review before GitHub. C2C012/013 live validations stayPARTIAL.
