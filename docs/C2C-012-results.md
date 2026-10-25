# C2C-012：受限训练参数与一次真实训练验证

EXECUTED — TASK_ID: C2C-012 — STATUS: PARTIAL

## 交付

TrainingOptions 严格限制 SoVITS/GPT 轮数1–100、批量1–8，默认8/15/2保持不变。
请求、持久任务和原生 Worker 传递选项；保存周期确保最后一轮落盘。
旧 schema1 请求缺少选项时只在解析时补默认，不改原始请求字节或摘要。
修复现有 Windows Conda python.exe 的 DLL 路径前缀：环境根目录直接包含解释器，不能取其祖父目录。
不改上游训练代码，也没有安装或下载依赖、模型。

## 实际命令与结果

证据目录为本机 `C:\Users\zsh\.codex\visualizations\2026\10\22\01a161c2-4f3c-7a12-a0ac-2e48a0e427b0`，以下简称 `<evidence>`。

| 命令 | 实际结果 |
|---|---|
| `python -m unittest discover -s tests -p test_training_options.py -v` 初始RED | 缺少TrainingOptions导入错误；加入实现后，新增Conda前缀检查复现失败；4项最终通过 |
| 训练相关测试集合 | 66项通过，25.255秒，包含原生假流水线的参数往返、旧记录兼容与HTTP非法参数422 |
| `python -m unittest discover -s tests -v` | Python3.12.8：233项，232通过、1个既有Windows符号链接权限跳过，56.548秒 |
| `& 'C:\Users\zsh\anaconda3\envs\gpt-sovits\python.exe' -m unittest discover -s tests -v` | Python3.10.20：233项，232通过、1个同一跳过，86.008秒 |
| `python <evidence>/c2c-012-real-audit.py` | 只读预检通过：现有依赖/权重/日语词典可读取，微型CUDA矩阵运算通过并退出，无已有推理监听，磁盘余量足够 |
| `python <evidence>/c2c-012-real-audit.py --run` | 唯一一次真实提交201，最终PARTIAL/退出1，详细如下；禁止直接重复此命令，审计脚本留有单次执行标记 |
| 原55项资源大小及UTC修改时间核验 | 55项完整保留，0项变化 |
| `git diff --check` | 通过 |

## 真实训练：未完成闭环

任务 `1b6237bae53f449980074b12954a6ca7`，使用已有8.064秒日语WAV及对应19字符转写的独立副本。
RTX3050 Laptop 4096MiB，开始空闲3494MiB，Torch2.5.1+cu124。
单任务180秒、每命令120秒，SoVITS/GPT各1轮、batch1；离线环境变量由父进程传给全部后代。
私有审计目录约束采用轮询2GiB预算，实际采样峰值2757583字节；这不是OS硬磁盘配额。

文本/BERT、HuBERT、说话人特征和语义预处理均退出0，约54秒进入SoVITS。
日志记录单轮包含100步，完成约24步后结束；任务约173.938秒进入failed，error_code为pipeline_failed。
结合每命令120秒及运行时间，命令期限是主要推断；当前进度协议丢失内层异常，仅靠保存日志不能证明唯一根因。
未观察到OOM堆栈，也不能将没有OOM日志当成硬件完整验收。
整个审计含回收耗时186.328秒；任务期限不等于带预检和清理的审计墙钟期限。

训练与队列均确认清理，之后GPU空闲3545MiB、利用率0。
没有 `models/<job_id>`，没有GPT训练、完整新权重对、模型注册或新模型合成验收；未用旧模型替代。
未增加预算自动重试。实际训练日志、报告JSON、任务私有目录及失败产物保留在本机证据目录，不上传音频/模型。

## 保护与剩余问题

原始音频/转写摘要和修改时间不变；原55项数据/模型仍完整。
上游配置SHA256仍为 `B9481D695F777839ABC5DA1D14B913BACEA3A9DA556B9E0CA0277CCFA85E9AF5`。
本轮只改训练Schema、Worker、相关测试和文档，不改角色绑定。

1. 真实训练预算不足以在此机器完成一轮，C2C-012保持部分完成；后续真实验证需另行制定预算，不能悄悄扩成完整训练。
2. `backend/workers/training_queue_worker.py` 将内层异常统一成pipeline_failed，细节不可诊断；下一次训练前应以假进程测试补充有限错误码与日志记录，不需要重跑GPU。
3. 原生假权重证明提交与注册协议，不证明真实权重可加载或声音质量。

下一最小任务可先补训练错误诊断，再按依赖开展C2C-013提供方适配；已有模型聊天不依赖新训练完成。
独立审查iteration1：PASS_WITH_PARTIAL_REAL_VALIDATION，ACCEPTED=true，无必须返工项。
代码可以发布；真实训练闭环仍为PARTIAL，不能标为完整验收。
