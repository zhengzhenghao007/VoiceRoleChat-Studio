# C2C-012B：训练错误诊断

EXECUTED — TASK_ID: C2C-012B — STATUS: PASS

独立复审iteration1：DONE/PASS，ACCEPTED=true，无必须返工项；允许按现有授权发布。

修复 C2C-012 发现的错误信息丢失：CommandError 仅按固定列表映射为
`command_timed_out/command_exit_nonzero/command_cancelled/command_ownership_failed/command_cleanup_failed/command_closed`。
未知错误仍是pipeline_failed，不暴露原始异常、路径、命令或堆栈。
失败进度保留可信的最后流水线阶段和已完成里程碑；监督器回收后才写终态。
命令期限失败为failed，整项任务期限为timed_out；父进程的取消、截止和退出意图优先。
清理失败仍阻止后续任务，不将诊断代码视为进程已退出证明。

Worker只向本次调用独占创建的日志追加固定FAILURE标记，不创建或接管旧日志；日志写入失败不影响错误上报。
Progress保持schema1，继续解析旧pipeline_failed/input_changed进度和旧请求，旧记录不重写。
本项没有GPU训练、模型加载、下载或真实训练重试，不能反向证明C2C-012的失败原因。

## 实测

证据目录：`C:\Users\zsh\.codex\visualizations\2026\10\22\01a161c2-4f3c-7a12-a0ac-2e48a0e427b0`，本项前缀c2c-012b。

| 命令 | 结果 |
|---|---|
| `python -m unittest discover -s tests -p test_training_diagnostics.py -v` RED | 3项中1失败1错误：无映射函数、父进程丢失命令错误码 |
| 同命令GREEN首轮 | 3项通过，0.384秒；随后增加日志IO失败和未知阶段脱敏两项，纳入全量回归 |
| `python -m unittest discover -s tests -p test_training_native.py -v` | 6项通过，17.838秒；真实HTTP与Windows进程树，运行的均为无害假脚本 |
| `python -m unittest discover -s tests -v` | 240项：239通过、1既有符号链接权限跳过，64.322秒 |
| `& 'C:\Users\zsh\anaconda3\envs\gpt-sovits\python.exe' -m unittest discover -s tests -v` | 240项：239通过、1同一跳过，101.524秒 |
| 原资源核验 | 55项，0项大小/UTC修改时间变化 |
| `git diff --check` | 通过 |

原生新增检查：SoVITS假脚本退出7，API为command_exit_nonzero并保留SoVITS阶段；
文本假脚本休眠30秒、命令限1秒，API为failed/command_timed_out并保留文本阶段；两者均确认监督器已回收。
原有运行取消、整任务截止和清理失败阻塞用例仍在完整回归中。

限制：权重可训练、可加载与质量仍未完成真实验收；日志仍可能受磁盘故障影响。
下一步C2C-013：本地LLM提供方配置、模型发现和连接测试，不依赖新训练产物。
