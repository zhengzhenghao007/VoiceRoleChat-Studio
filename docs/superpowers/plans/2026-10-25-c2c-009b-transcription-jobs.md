# C2C-009B 实施计划（待设计审查）

基线 741074f。此文件不是完成报告；尚无本任务运行时代码或测试。

1. 只读验证本机 Win32 Job Object 能力；用临时轻量子进程验证绑定、关闭终止、
   绑定失败无遗留。先 RED/GREEN tests/test_process_ownership.py，再集成。
   文件 backend/services/owned_worker.py（仅本轮需要的最小抽象）。
2. Schema/版本化 JobStore、原子写、恢复规则：schemas/transcription_job.py、
   services/transcription_job_service.py；测试用例先定义终态、nonce、坏状态、
   发布中断和取消优先语义，不在只读 GET 中修改文件。
3. 提取只推理不发布逻辑，新增 workers/transcription_worker.py；小 JSON 状态、
   有界结果文件。验证旧同步接口/旧文件名/数据集消费回归。
4. 有界单任务调度、超时、取消、关闭清理及 FastAPI lifespan 卸载；
   api/transcriptions.py 添加 jobs 路由，测试临时进程和并发请求。
5. 真实离线 CPU HTTP 任务、双环境全回归、原资源保护。记录所有失败/通过，
   README/路线更新。ChatGPT 独立审查→必要小修→授权 GitHub 提交。

执行策略：逐项保持 RED/GREEN 和检查点；额度边界不启动可能无法回收的真实任务。
不下载/安装/训练；用户只需在缺外部凭据/必须人工操作时参与。
009C 编辑器/UI 独立，不能在本任务中顺手重写前端或数据集。

## 续接检查点

设计已收七项细化（见 spec 附录）。首个真实平台预检 PASS，脚本保存在
 tools/windows_job_probe.py；两个 Python 均验证挂起/绑定/恢复/Job 关闭回收。
尚未开始生产 owned_worker、队列、任务 API 或编辑器实现。
下一步：先做进程所有权失败注入 RED/GREEN，不能跳过关卡直接运行 Whisper。
用户持续推进授权有效；无需重复设计确认。C2C-009A 已发布 741074f。

## 执行 ledger（当前设计为权威）

Pre-flight: OwnedWorker.start/poll/stop -> 单调调度与退出回收；infer_path -> 旧同步
保存及私有 Worker 候选；state/nonce/result -> 取消、恢复、只读 API；全局实例 ->
FastAPI 退出。接口逐项核对一致。沿用当前 checkout/现有独立 ChatGPT 审查流程。
Task 1: RED missing module -> 5 GREEN，最终 6 GREEN（父进程崩溃后代清理）。
Task 2: RED missing store -> 9 GREEN；阶段读取、关机写盘失败重试另有 RED/GREEN。
Task 3: RED missing pure worker -> 25 项相关 GREEN，旧同步 13 项保持。
Task 4: RED missing API、未知参数被忽略 -> 严格新请求及单例/生命周期 GREEN。
Task 5: 双环境 135 项（134 PASS/1 skip）；真实离线 CPU HTTP 两套都通过。
Ruling: stdout 不使用管道/IPC，改为有界私有阶段/候选 JSON；更小协议面且避免
原生库输出塞满管道。新结果 GET 只读取，不提供编辑；009C 后续实现。
Ruling: 后台只支持已验证的 Windows 所有权，其他平台 503；不降低清理保证。
Ruling: 既有 Windows 执行环境/资源和用户连续开发意图下继续原 checkout，避免
切换连接/模型绝对路径。没有重置或丢弃用户成果。
待独立审查；本轮未创建训练或下载任务。
