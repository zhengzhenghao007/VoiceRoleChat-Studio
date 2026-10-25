# C2C-009B 后台转写任务验收

TASK_ID: C2C-009B
STATUS: PASS，ChatGPT 独立审查 DONE/PASS，无必修项。
日期：2026-10-25 Australia/Sydney，基线 3c9cea0。

## 交付与接口

Windows 单后端进程：持久队列、一个自有离线 Whisper Worker、五个排队名额、
运行截止、取消、进程清理、重启恢复。原有同步/上传转写合约保持。
新增 POST/GET /api/transcriptions/jobs，GET /jobs/{id}，POST /jobs/{id}/cancel，
GET /jobs/{id}/result。新请求拒绝未知字段，未支持的客户端 timeout 不会被静默忽略。
提交 202、队列满 429、结果未就绪 409、无安全进程能力 503。
有效任务可查状态/真实阶段，不虚构进度百分比。

输入快照复制块 1 MiB，最大 50 MiB，复制前后 stat 与摘要检查。
私有 request/state 在 transcripts/.jobs/<id>/，子进程只写私有候选和进度。
父进程用读取时预算验证 16 KiB 请求、1 KiB 阶段、8 MiB 候选，严格匹配
源 ID/摘要、task/nonce、Schema、时间顺序；最终结果为独立 schema2/revision1
transcripts/<task_id>.json，保留现有数据集消费者需要的字段。

Win32 CreateProcessW 挂起创建；设置 KILL_ON_JOB_CLOSE 后先分配 Job、再恢复
主线程。显式管理进程/线程/Job 句柄，不用持久 PID 接管，也不用 Popen 私有句柄。
启动任一步失败都先清理；失败清理保留所有权，可重试，阻止新 Worker。
正常退出、取消、超时、关闭及父进程崩溃均有对应进程回收边界。

取消/超时意图先持久化，确认退出才进入终态；结果原子替换是成功提交点。
提交后状态写失败不再接受取消覆盖成功；重启只凭完整有效结果恢复成功。
未提交的旧 queued/running 变 interrupted，不自动重跑；坏/未来版本元数据诊断
跳过并保留。两个文件的发布不是断电原子事务；没有持久 PID 盲杀。

## 实际命令与结果

| 命令 | 结果 |
|---|---|
| `python -m unittest discover -s tests -p test_process_ownership.py -v` 初始 RED | 模块不存在，exit 1 |
| 同上 GREEN/最终 | 首轮 5 项 PASS；加入父进程崩溃后最终 6 项 PASS，1.177 秒 |
| `python -m unittest discover -s tests -p test_transcription_jobs.py -v` 初始 RED | 模块不存在，exit 1 |
| 后续任务 RED/GREEN | 首轮假 Worker 对未启动对象的 close 语义错误已修夹具；9 项 PASS；阶段、关机失败重试、严格 API 分别有新增 RED 后修复 |
| `python -m unittest discover -s tests -p test_transcription_worker.py -v` 初始 RED | 模块/纯推理函数不存在，exit 1 |
| `python -m unittest discover -s tests -p 'test_transcription*.py' -v` | 中间回归 30 项 PASS（最终新增用例已在全套覆盖） |
| `python -m unittest discover -s tests -v` Python 3.12.8 | 135 项，134 PASS/1 已知 skip，27.693 秒，exit 0 |
| `C:\Users\zsh\anaconda3\envs\gpt-sovits\python.exe -m unittest discover -s tests -v` Python 3.10.20 | 135 项，134 PASS/1 已知 skip，39.735 秒，exit 0 |
| `python <evidence>/c2c-009b-real-api.py` | 真实离线 CPU HTTP 三任务通过：成功/运行态取消/缺模型失败，5.813 秒，exit 0 |
| 同脚本，Conda Python 3.10 | 同样通过，12.829 秒，exit 0 |
| `git diff --check` | exit 0，只有 Windows 行尾提示 |

全部自动测试只用临时目录/假懒模型/轻量自有子进程；原有真实符号链接权限
用例仍是唯一 skip，路径解析逃逸另有覆盖。没有安装、下载或 GPU 训练。
新覆盖：启动每步失败、清理失败保留句柄、实际执行前拒绝分配、嵌套 Job、
正常退出、父进程 os._exit 后后代心跳停止、容量并发、排队/运行取消、
deadline、错 nonce/超大输出/坏阶段、worker 崩溃/启动失败、写盘失败、
取消意图恢复、提交后成功状态写失败恢复、终态幂等取消、损坏/未来版本诊断、
结果读取、全局生命周期单例与关闭失败重试。

## 真实离线 CPU HTTP

临时目录复制既有 datasets/test_character_japanese_v1/audio/voice.wav：
8.064 秒，现有 small/cpu/int8 缓存，子进程 local_files_only=True。
两套 Python 均返回日语文本 `あのなさとる、まあいい、また今度話そう`，
片段 0.56–5.56 秒，独立 schema2 结果可读。
第二任务在 running 状态收到取消，最终 cancelled，未发布结果；这一取消可能
早于模型加载，不冒充“已在解码中途取消”的验收。
第三任务指定不存在的本地模型，最终 failed/model_unavailable。
最后 worker/active_id 均为空，临时服务停止；源音 SHA256/mtime 均未变。
后台任务的 timeout 回收用假 Worker 时钟/真实进程所有权分别验证；本轮没有
让真实 Whisper 故意耗尽整个推理截止时间。

既有 55 项资源大小/mtime 与基线一致；上游 YAML SHA256 仍为
B9481D695F777839ABC5DA1D14B913BACEA3A9DA556B9E0CA0277CCFA85E9AF5。
证据目录仍为本机 visualizations/2026/10/22/01a161c2-4f3c-7a12-a0ac-2e48a0e427b0，
主要文件 c2c-009b-ownership-red/green/final.txt、c2c-009b-jobs-red/green.txt、
c2c-009b-worker-red/first.txt、c2c-009b-api-red/first.txt、
c2c-009b-progress-red.txt、c2c-009b-shutdown-red.txt、
c2c-009b-strict-request-red.txt、c2c-009b-python312/310.txt、
c2c-009b-real-api.py、c2c-009b-real-api312/310.txt。

## 实施裁决与限制

- 在既有连接和用户同意持续开发的当前 checkout 继续；未复制/移动原用户数据。
- 后台新接口仅 Windows；其他平台明确不可用，同步接口仍可用。
- stdout 不作 IPC：无继承输出句柄/管道，不接收不限量 stdout；使用有界 JSON
  文件报告真实阶段和候选结果，父进程读取时限制。原生库 console 输出不作协议。
- 新增只读 result API，使后台任务可从 HTTP 取回结果，不把编辑器顺带实现。
- 失败提交留下的私有任务目录可在重启时被诊断为坏元数据；不自动删历史文件。
- 无 OS 硬内存限额、数据库或多进程锁；继续限制单用户、单业务进程。
  排队快照占用磁盘，历史任务/输入暂不自动清理。逐段编辑与任务 UI 属于 009C。
- 本轮未改前端，未重复浏览器 26 项；其既有证据保持，不作为本轮新执行结果。

下一步：ChatGPT 独立审查全部代码与输出，处理必要修复后授权 GitHub 上传。
之后推进 C2C-009C 版本化结果校对与工作台，不将 C2C-009 整体标完成。
