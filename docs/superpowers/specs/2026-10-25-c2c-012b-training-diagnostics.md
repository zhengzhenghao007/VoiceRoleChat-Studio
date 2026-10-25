# C2C-012B：训练失败诊断

Context: C2C-012 consumed its one real attempt; inner CommandError was replaced by generic pipeline_failed. No further real training under this task.

Design: propagate only a fixed allowlist of command errors (timed_out, exit_nonzero, cancelled, ownership_failed, cleanup_failed, closed) as command_* progress codes. Unknown exceptions remain pipeline_failed. Preserve bounded current phase from trusted worker memory; do not expose arbitrary exception text, commands, credentials or stack traces. Parent alone owns terminal status; command_timed_out is a failed pipeline, distinct from whole-task timed_out. Cancellation/whole-task decisions retain priority. Existing progress/request version1 and old records remain readable. Log a fixed diagnostic line in the already-owned job log when possible; logging failure must not prevent failure reporting/cleanup. No raw exception strings.

Scope: worker exception mapping, progress allowlist, runtime phase forwarding and parent final error message; focused fake tests, dual Python regressions, README/results and independent review. No GPU, model downloads, retry or architecture changes.

Alternatives: raw exception string leaks paths/content and unbounded output; only worker logs cannot expose actionable API codes. Prefer bounded typed codes plus current phase.
