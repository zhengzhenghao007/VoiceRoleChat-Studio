# C2C-012 Bounded real training export/inference verification

Baseline8fff649; user requests continued implementation and GitHub/README updates. C2C011 lifecycle independently accepted. This task adds bounded training options and attempts one short offline real validation, never full training or automatic retry. Existing inputs/weights unchanged; new successful model/output may be added to ignored runtime folders, never GitHub.

Preflight observed: RTX3050Laptop4096MiB, driver546.30, Torch2.5.1+cu124, cuda available and16x16 CUDA matmul passed. Four configured pretrained files exist (S1/S2G/S2D/SV), BERT/HuBERT local weights and Japanese dictionary present, required Python modules found. D: free58.8GiB. Existing8.064s mono32k Japanese WAV and original Japanese transcript19chars available read-only. No assumption of training feasibility from these checks.

## Minimal feature

Add TrainingOptions to TrainingRequest: strict ints sovits_epochs1..100(default8), gpt_epochs1..100(default15), batch_size1..8(default2). Unknown options rejected. Persist options in immutable request/state and expose in response. Omitted options preserve old defaults, including schema1 records/request byte hashes. Worker passes options to both train functions, safe checkpoint interval min(existing interval,epochs) ensures1-epoch outputs. Direct helper defaults retained. No upstream code edits, no architecture changes or unbounded hyperparameter surface. Fix Conda DLL prefix only if actual deterministic preflight/test proves existing parent.parent incorrect; no speculative changes.

## One real validation envelope

After options tests/plan review, use existingConda/localmodels only, force HF/transformer offline environment, no install/download. One real queue submission: batch1, S2/GPT each1epoch, whole task180s, percommand≤120s. Snapshot existing WAV/transcript into isolated audit inputs; no source edits. Use separate training-jobs/input roots under evidence, actual upstream config read-only, models published only under newUUID in project models if successful. Read-only GPU readiness requires≥3GiB free and not busy; disk≥5GiB free, otherwise report resource block and do not start. Monitor audit work footprint; request cancellation if >2GiB (cooperative audit guard, noOSdiskclaim). No automatic retry after failure/OOM/timeout. Ensure owned cleanup, preserve logs/private artifacts.

If completed: verify model commit proof, registry list/details matches same pair, load newly generated weights through managed CPU TTS on an ephemeral port, one short Japanese utterance using existing8.064s WAV/text as reference; max180s inference/start budget per existing service, stop only own service. Validate finite nonzero PCM, file digest andaudio HTTP/download. No quality/generalization claim for1epoch, no replacement of user's current role bindings. If training fails, report PARTIAL with concrete stage/error; do not call existing pretrained/old model success proof of new training. A fake test is not real verification.

## Tests/delivery

TDD defaults/strict-invalid/options persist/old-request compatibility/config epoch,batch,checkpoint intervals; native fake pipeline carries options. DualPython full regression. Real attempt logged independently with hardware/options/outcome/timing/cleanup.55old resources/YAML baseline preserved. README truthfully distinguishes real success from fake lifecycle results. Independent C2C review before publishing. If real acceptance blocked, retain specific minimal next repair and continue independent roadmap work rather than changing hardware/installing or full retry.
