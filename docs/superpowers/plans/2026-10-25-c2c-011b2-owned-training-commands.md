# C2C-011B2 Implementation Plan

Goal: bounded owned command lifetime before durable training queue.
1.RED tests/test_training_commands.py with harmless temporary Python child/descendant; implement services/training_command.py and workers/training_command_worker.py. Bounded request/environment deltas, owned runner polling/deadline/cancel, retained cleanup.
2.Replace only training_worker.run_command adapter and add config TRAINING_COMMAND_TIMEOUT plus startup env tests; app shutdown hook closes training owners. No publiccancel/queue claim.
3.DualPython full regressions/resourceprotection; docs/README/results, independent C2C review, then publish. Continuous authority/current checkout/inlineTDD retained.011B3 durable states/queue/cancel and private weight export next.

Execution ledger: approved fixed-step contract/environment PATH-prefix/log ownership/shutdown admission refinements adopted. Existing WinAPI unchanged. Native9 tests pass, final196eachPython (195pass/1skip), noGPU. Corrected GPT --config_file through additional RED. Final times35.856s/48.337s.55resources/YAML preserved. Publiccancel/durablequeue/whole-job deadline/private weight commit notimplemented;011B3.
