# C2C-014B：受限文字角色回复

Goal: backend role-chat reply lifecycle, reusing013 local HTTP and014A atomic pair storage. No frontend/translation/voice or real provider installation in this slice.

API POST /api/sessions/{id}/replies accepts request_id UUID, expected_revision and user_text≤8000; returns202 status. GET /replies/{request_id} polls; POST /replies/{request_id}/cancel requests cancellation. One global in-flight reply, no queue. Completed/failed/cancelled metadata cache bounded64. Completed receipts recover from SQLite after restart; uncommitted job state is deliberately volatile (unknown404 after restart), no automatic retry/resume. History alone is durable. No schema migration or partial messages.

Use immutable session role snapshot and reply language as system prompt, then contiguous recent complete pairs within40messages/16000total/8000each. Trim whole oldest pairs; oversized system/new request rejects before inference, never truncates original stored messages. Provider is resolved lazily after committed-request replay, so history/idempotent replies work if provider later unavailable. Missing model rejected before accepting work. No model download/cloud calls/GPU work.

Duplicate active request + same user text returns original status, different text409; committed replay returns original receipt regardless current revision and does not infer again. Failed/cancelled entries not automatically rerun while cached. Different new request while busy429. Provider failure/cancel/stale revision commits neither user nor assistant. Success only after SQLite pair transaction. Fixed error codes, no exception/body disclosure.

Cancellation while generating cancels our async HTTP operation and awaits client cleanup; it does not claim to terminate provider-side computation. Once committing starts, cancel409 commit_in_progress; shutdown waits for commit rather than cancelling its thread. Before commit, cancellation wins and no pair is saved. Admission closes on backend shutdown. SQLite transactions stay short and never contain network calls. Abrupt process death may lose job status but completed pairs remain atomic/idempotent.

Tests: fake provider generation/context/complete pair, concurrent retries, error/cancel no orphan, stale revision, commit race and shutdown, completed replay after restart with unavailable provider, missing model, API contract and dual full suites. Preserve55resources/YAML; actualLLM remainsPARTIAL until available. Independent review before publish.
