# C2C-011B2：训练命令所有权

STATUS: PASS；iteration1独立审查通过，无必需修复。基线498c2c1。

新增TrainingCommands执行器及可信包装器，替换训练Worker裸Popen.wait。只允许text/hubert/speaker/semantic/sovits/gpt六个固定步骤；训练配置路径从任务ID和固定文件名构造，保留SoVITS --config和GPT --config_file契约。不提供API任意命令或Python -c入口。包装器继承环境，只应用允许的增量；PATH只保存前置片段而非父环境整条PATH，未知改动拒绝。≤64KiB请求在training_jobs/.commands/<uuid>/request.json保留诊断，不写完整环境。

沿用未修改的OwnedWorker suspended→绑定Job→resume；包装器内无shell子进程继承外层Job，stdout/stderr追加既有UUID日志，不创建任意日志。父进程monotonic每命令截止，TRAINING_COMMAND_TIMEOUT默认21600秒、最大86400。内部Event取消与退出/超时/归属失败/清理失败使用不同code；成功或失败均关闭Job，清理失败保留owner并阻止下条命令，可重试。应用关闭先拒绝接纳，再清理训练Job，旧daemon线程之后调用也失败。

## 实际执行

| 命令 | 结果 |
|---|---|
| `python -m unittest discover -s tests -p test_training_commands.py -v` 初次 | 缺模块RED，1错误 |
| 同上首批实现 | 6项通过，2.550秒 |
| 同上增加生命周期/固定步骤测试 | 9项通过，2.908秒 |
| 同上增加GPT参数精确校验 | RED9项1失败；发现错误--config映射，改为既有--config_file |
| `python -m unittest discover -s tests -v` 最终 | Python3.12：196项，195通过、1已知权限跳过（最终时间见原始执行记录） |
| `& <conda-python> -m unittest discover -s tests -v` 最终 | Python3.10：196项，195通过、1同一跳过（最终时间见原始执行记录） |
| `python -m py_compile backend/app.py backend/services/training_command.py backend/workers/training_command_worker.py` / `git diff --check` | 通过 |

原生测试只运行临时目录中无害Python脚本，未运行GPT-SoVITS、Whisper、GPU或真实预处理。覆盖stdout/stderr、非零退出、env增量/未知变量、真实超时后后代心跳停止、内部取消、活动关闭与后续拒绝、启动失败替身、清理失败保留与重试、日志路径、六步骤参数。没有公开取消API或持久队列；不将内部Event误报为用户可取消训练。

本机证据根目录 `C:\Users\zsh\.codex\visualizations\2026\10\22\01a161c2-4f3c-7a12-a0ac-2e48a0e427b0`，前缀c2c-011b2。继承完整环境不写入请求，失败断言不输出进程环境。

## 边界

Windows、单后端进程；其他平台安全归属不可用即拒绝，没有裸Popen回退。日志没有硬磁盘空间上限，Job没有OS内存硬限制。每命令截止不是整个训练任务截止。当前仍有daemon线程/进程内锁，任务JSON尚无可靠队列、取消和重启协调；关闭可能使任务失败，不伪装为已取消。上游全局权重仍共享，未隔离外部写入。C2C-011B3应实现持久训练队列/决策提交、任务截止、恢复及私有权重输出/导出提交。无真实GPU验收。

最终回归时间：Python3.12 35.856秒，Python3.10 48.337秒；均196项/195通过/1跳过。55原资源大小/修改时间不变，上游YAML SHA与基线一致。
