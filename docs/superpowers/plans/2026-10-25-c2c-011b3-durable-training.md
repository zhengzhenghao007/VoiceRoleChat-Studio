# C2C-011B3 Durable Training Implementation Plan

> Inline executing-plans/TDD under continuing authorization; no agents/worktree churn. Independent C2C whole-change review before publication.

Goal: Parent-owned durable queue, cancel/timeout/recovery and atomic private weight publication.
Architecture: focused strict schema, queue store/export helper, supervisor, trusted pipeline worker adapting existing functions. No real GPU.

- [x] 1.RED schemas/store/commit tests in tests/test_training_queue.py; add schemas/training_queue.py and services/training_queue_store.py (bounded source fingerprints, legacy projection, safe state, export validation/commit proof). Test no-overwrite and failure/recovery.
- [x] 2.RED supervisor fake-owner tests (FIFO/queue/admission/decisions/cleanup/restart), then services/training_queue.py and cancellation API. One lazy instance started/stopped by lifespan, exclusive root lock. Atomic state under RLock, file IO validation outside final commit lock. Preserve public legacy response field names.
- [x] 3.RED pipeline config/callback tests; adapt training_worker runtime hooks, private experiment/weights/export, add workers/training_queue_worker.py. Native test fixtures build only harmless six registered scripts and dummy config files; actual process ownership/cancel/deadline/commit. Bind input/request hashes. Keep legacy direct helper behavior bounded.
- [x] 4.API tests through dependency override and real native HTTP, dualPython full suites and browser regression if affected; resource preservation. README/roadmap/results/execution records; C2C review, required fixes, commit/push verify remote. No real GPU/download/install.

Ruling: Outer owned process chosen over cooperative thread cancellation because snapshot and preparation IO must not outlive task timeout. Cost: serialize bounded trusted runtime config and separate parent state/child progress.
Ruling: Startup never resumes interrupted/pending tasks, avoiding duplicate expensive work. Explicit fresh submission is retry.

## Execution ledger

Store+queue+API+outer worker implemented; parent-only canonical state and final model commit, private GPT/SoVITS outputs and preprocessing. Cross-process root lease, persistent FIFO order; submit sources bound by hash. Legacy runtime also creates bounded checked input copies. Per-command timeout propagated. Native fake upstream six-step pipeline real HTTP passes including old/new input, model discovery, cancellation and outer+nested descendants stopped. Atomic progress publication Windows read-sharing issue reproduced with actual held reader; local0.5s PermissionError retry. Export experiment_name corrected by registry RED; candidate malformed path types fail controlled. Storage failure cannot disable actual deadline/exit cleanup, but no unpersisted terminal acknowledged.

Final dual suites229each/228pass/1known skip:3.12 56.329s;3.10 85.775s. Browser41pass after lazy queue initialization.55resources/YAML unchanged. All prior RED/failures retained; no GPU/model load/download/install. Read docs/C2C-011B3-results.md before independent whole-change review. Planned tasks1-4 implementation/verification complete, awaiting independent gate.

Ruling: Supervisor lazy initialization at first training API access prevents unrelated backend tests/features from mutating or recovering training storage; lifespan still controls admission/shutdown. Recovery happens only after exclusive root lease.
Ruling: Use injected monotonic clock to trigger native deadline only after descendant readiness; actual tree-kill assertion retained, no dependency on cold interpreter speed. Production uses real monotonic clock.
Ruling: Deadline/shutdown storage failure still reaps worker, preserves failure/nonterminal state and blocks admission; no false durable cancellation acknowledgement. Startup reconciles old state.

Independent review iteration1: PASS, no required fixes. Preserve deadline/IO and local-filesystem trust limits. C2C-011 backend lifecycle accepted; next012 bounded real-resource verification.
