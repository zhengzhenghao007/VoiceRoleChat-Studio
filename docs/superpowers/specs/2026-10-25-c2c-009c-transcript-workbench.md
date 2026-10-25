# C2C-009C Transcript correction and workbench

Status: design for independent planning review. Baseline f4c7e8c.
User delegated roadmap/design choices and continued execution; no repeat approval.

## Chosen approach

Keep raw legacy and job transcripts unchanged. Save correction as a new review
(schema3, UUID, revision1+) in transcripts/<review_id>.json, compatible with the
existing dataset consumer's flat language/text/segments/duration/audio fields.
Avoid editing schema2 job results: job recovery/nonce verification stays unchanged.
Subsequent edits only target review records and require expected_revision AND
expected_sha256, returning409 on stale revision or external file changes.

Alternatives considered: mutate job output in place (less code, weakens immutable
inference provenance); embed editing in queue state (mixes task lifecycle and
content). Independent review copies give stable raw evidence and smaller coupling.

## Record API/storage

GET /api/transcriptions/records: canonical UUID JSON records, summaries and safe
diagnostics for malformed/future records; no read-time migration or writes.
GET /records/{id}: envelope id/kind/revision/sha256/editable plus transcript body,
optional safe local source-audio URL. Missing source audio must not hide text.
Recognize original unversioned transcripts (revision0), schema2 immutable job
results, schema3 editable reviews. Unknown paths/files never read outside root.

POST /reviews: source_id, expected_source_sha256, language and full segments.
Read canonical source, verify hash, validate and derive joined text server-side.
Save exact bounded source bytes to deduplicated .review_sources/<sha256>.json on
explicit create for provenance even if an old synchronous endpoint later replaces
its original JSON. Then atomically publish unique review; never rewrite source.
No multi-file crash transaction claim; orphan source snapshots can remain safely.
GET /reviews/{id} and PATCH /reviews/{id}: versioned edits, full language+segments,
expected revision/hash; immutable duration, source reference/provenance/created_at.

Bounds: same 8MiB JSON, <=100000 rows/1Mi characters; nonempty trimmed text,
finite times with0<=start<end<=duration(+0.01), chronological nonoverlap, supported
Whisper language. Empty or overlapping save is rejected422 with useful message.
Raw overlapping results can still be viewed and corrected in browser before save.
Atomic sibling staging/fsync/replace, safe canonical real paths, shared process
lock for review writes. Lists skip bad records diagnostically without rewriting.
No raw transcript deletion or migration; no task/model/training architecture change.

## Workbench

Add fourth Chinese 转写 tab using existing typography/palette and plain-JS module.
Audio detail button sends selected audio to task form; explicit language/submit,
job list and cancel, real-stage polling only while tab visible, no auto model load.
Completed task opens raw transcript; record list also exposes existing transcripts.
Source audio playback with per-row seek/play, clear missing-audio status.
Rows edit start/end/text, add/remove and reorder; save corrected copy or revision.
Server validation is authoritative; show 409 conflict without dropping draft.
TextContent/DOM only, canonical audio links. Empty/loading/error/retry states.
Separate saved/draft/request token/epoch; pending-save newer edits remain dirty,
late record loads cannot replace current selection. Switching record prompts on
dirty draft; switching tabs preserves drafts. beforeunload warns; pagehide stops
polling/audio. Role and transcript drafts remain independent and both protected.

## Verification

TDD pure temporary record/API stores: readonly legacy/job reads, explicit copies,
source/hash/revision conflicts, invalid times/overlap/text/language, atomic failure,
path escape, corrupt/future data diagnostics, orphan audio, old dataset consumer.
Extend native Playwright isolated fixture with fake jobs (real HTTP/storage, no ML)
for submit/query/cancel, correction/reload/conflict, dirty confirmation, request
identity, edits pending save, safe text and mobile no overflow. Existing26 checks
remain. Browser fixtures redirect ALL transcription/review/task roots.
Dual Python full suites; verify original55 resource metadata and YAML preserved.
No downloads/installs/training or real microphone. Real job CPU evidence retained009B.

Next: C2C010 segmented dataset building from reviewed records; not implemented here.
