# C2C-011B3 Durable training lifecycle

Baseline04eebb6. User delegates routine design and requests continued implementation/upload. No GPU training/download/install in this task. Windows/single backend; existing user model/data protected. Current API creates one daemon per request, state updates race, global weights publish before parent outcome. Previous input snapshots and owned command runner retained.

## Decision

Use one durable supervisor and one outer OwnedWorker for the entire pipeline (including preparation), not a thread per job. Outer Job Object encloses existing per-command jobs and their descendants. Parent alone writes job state and publishes models. Child emits bounded authenticated-by-identity/nonce/request-digest progress and candidate files; no child writes canonical task state. Read-only runtime roots from trusted parent config, never supplied by API. Six steps remain fixed. All new weights and preprocessing output private per task, no new writes to GPT-SoVITS global logs/weight roots. Legacy records read-only; direct helper compatibility retained for tests but API uses supervisor only.

## Storage/contracts

`training_jobs/.queue/<job>/state.json` strict schema1, request.json (request,nonce/config/fingerprints), progress.json, candidate.json; child export/<job> stages models. Existing training_jobs/<job>/input snapshots/work/log retained. Manager Windows file lock prevents a second supervisor on same root; no PID adoption. New job identity32hex and run_nonce; immutable request digest. Max1running+5queued; deterministic FIFO. POST /start retains201, GET list/details retains old field names; POST /{job}/cancel202; GET /diagnostics exposes malformed/future/legacy pending records without rewriting them. Response adds schema_version,decision,error_code; statuses add timed_out/interrupted. Progress truthful milestones only (0..99 before model commit).

Persist cancel/timeout/shutdown intent before termination; terminal outcome only after confirmed process-tree cleanup. Cleanup failure retains owner, blocks queue, displays decision and cleanup error, retry permitted. Whole-task monotonic timeout default86400s max604800 plus previous command deadline. Queue wait excluded. Shutdown closes admission first, queued tasks interrupted, active interrupted only after cleanup; no future daemon work. Non-Windows submit503, no unsafe fallback.

At submission validate existing input contracts and bind character config + prepared manifest hash, or legacy audio/transcript hashes. Validate again before pipeline, reject changed source. Prepared snapshots keep independent bytes; no implicit source upgrade while waiting. Each source read is bounded (50MiB audio,8MiB transcript,1MiB config/manifest).

## Parent commit/recovery

Child writes only private weights, private experiment, work input copies, existing UUID log and candidate. Pipeline callbacks replace direct state writes, preserving direct legacy helper behavior where required. Training configs direct GPT and SoVITS weight outputs to work/weights; export candidate contains fixed two files/manifest and identity+nonce+request hash+file hashes. No pickle/model load for verification. Parent waits and reaps child, validates candidate and staged manifest/path/file hashes (max8GiB each), creates final manifest paths and training_task commit proof, checks fresh durable decision/deadline under state lock, then Windows no-overwrite rename to models/<job>. Directory rename is completion commit. Persist completed after commit; failed state persistence can recover from verified commit proof. Cancellation before rename wins; after committed model it cannot undo success. No existing models overwritten, incomplete private exports invisible to model registry.

Startup reads schema1 new queue only, never re-runs pending tasks. Valid committed result recovers completed, durable cancel/timeout intent recovers its outcome, otherwise queued/preparing/training become interrupted. Missing/invalid committed files become interrupted diagnostic. Unknown/future/malformed state/request are read-only diagnostics. Old flat records readable including cosyvoice, old unfinished records diagnosed without rewriting. Cross-process writer exclusion via file lock; external file tampering and power loss remain limits, no OS memory/log hard bounds claimed.

## Validation

TDD store/queue limits/FIFO/decisions/restart/commit races/failed atomic persistence/candidate tamper; API schema/legacy/errors/no Thread; pipeline runtime callbacks and private output configuration. Native harmless fake upstream six-step scripts exercise actual outer process, nested jobs and fake weight export, cancel/deadline descendant heartbeats, missing inputs, shutdown and stale source. No real pretrained weights read or models loaded. DualPython full suites; existing browser flows if API lifecycle changes affect them.55-resource metadata+upstream YAML check. Independent C2C review before GitHub push.
