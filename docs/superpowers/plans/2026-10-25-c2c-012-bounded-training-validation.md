# C2C-012 Bounded Training Implementation Plan

Goal: expose constrained epoch/batch options and verify one real short offline pipeline within explicit4GiBGPU limits.
Architecture: extend existing request/response/options and worker config only; reuse accepted durable supervisor, private outputs and commit proof. InlineTDD/currentcheckout, user routine-authority delegated.

- [x] RED tests/test_training_options.py for defaults/strict limits/unknown fields, config batch/epochs/save interval, request persistence and old missing-options records. Add schemas TrainingOptions and worker args without upstream edits.
- [x] Native fake-pipeline option roundtrip + dualPython tests. Validate current environment/paths read-only; fix only proven small startup blockers through RED/GREEN before any real submission.
- [x] Prepare isolated audit inputs from existing Japanese sample; one real180s queue task with batch1/epochs1, no downloads/retries. GPU/disk/footprint guard. Record exact success/failure and owned cleanup.
- [x] If newmodel commits, managedCPU one-utterance load/HTTP check using newmodel, then ownstop. Otherwise report PARTIAL, preserve diagnostic and no substituting oldmodel. Resource55/YAML audit; README/results -> C2C independent review -> required fixes -> GitHub push.

Ruling: One realattempt only; failure is useful evidence and does not authorize an automatic training retry. CLI/metadata probes are not training. FullGPUtraining/downloads remain excluded.

Execution: real attempt PARTIAL, four preprocessing steps exited0; SoVITS24/100 then pipeline_failed after173.938s. No retry/model commit/inference; cleanup confirmed,55 original resources unchanged. Independent review/publication pending.
