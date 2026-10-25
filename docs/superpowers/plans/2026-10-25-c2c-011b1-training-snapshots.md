# C2C-011B1 Implementation Plan

Goal: independent immutable-by-convention training inputs before preprocessing.
Architecture: focused services/training_snapshot.py uses011A validator; worker after exclusive work ownership snapshots prepared dataset. Legacy untouched. Current checkout, inline TDD under continuous authority.

1.RED tests/test_training_snapshots.py using actual temporary010dataset fixture. Snapshot bytes/digests, rebased labels, mutation/conflict/partial failure and no commands. Then bounded safe copy/provenance helper.
2.RED worker integration assertion updated to expect verified task-local inputs; integrate only prepared mode. Preserve source metadata for model lineage; retain partial diagnostics.
3.Dual Python full tests; README/results/roadmap, records; C2C independent review and required fixes, then publish. No GPU, downloads, external mutation or lifecycle claims.011B2 queue/cancel/recovery still pending.

Execution ledger: approved refinements adopted. Exact original manifest retained; only copied labels rebased. Pre/post original and copied PCM/hash validation before atomic provenance. Target inputs exclusive; fixed file set,1MiB chunks/128MiB total. Original after completed copy no longer consulted.20targeted tests pass;187full eachPython (186pass/1skip), no external commands.55resources/YAML preserved. Empty/invalid provenance reservation on storage failure is not accepted as success; no preprocessing until full helper returns. Global weights and lifecycle remain011B2.
