# C2C-009B 持久转写任务设计

状态：设计待审查，尚未实现。基线：C2C-009A 741074f。
用户授权持续推进；不需要重复功能确认。为使生命周期可独立验收，
把逐段编辑/UI 顺延为 C2C-009C；C2C-009 整体仍在进行中。

## 目标

增加显式后台转写任务：有界队列、单个隔离 Whisper 子进程、进度状态、
超时、取消、关闭和重启恢复。保留现有两个同步接口，不暗改其返回格式。
不下载、不安装、不训练；真实测试继续用现有 CPU 缓存和短音频副本。

## 接口与存储

- POST /api/transcriptions/jobs：canonical stored_filename、可选 language；
  返回 202 和 task_id。最多 1 running + 5 queued，满时 429，不默默排队。
- GET /api/transcriptions/jobs：只读列表；GET /jobs/{id}：状态详情。
- POST /jobs/{id}/cancel：queued 直接 cancelled；running 先请求终止并
  回收自有进程，确认结束后 cancelled；terminal 返回原状态，保证幂等。
- 阶段 queued/running/succeeded/failed/cancelled/timed_out/interrupted；
  不编造百分比，展示 queued/loading/transcribing/publishing 等阶段。
- 状态目录 transcripts/.jobs/<UUID>/state.json（已在忽略范围内），
  带 schema_version、run_nonce、时间、输入摘要、错误代码和 result_id。
- 新结果 transcripts/<task_UUID>.json：唯一记录，不覆盖旧转写；保留
  旧消费者所需 stored_filename/language/duration/text/segments 字段，
  另增 schema_version=2、id、revision=1、task_id、run_nonce 与时间字段。
  新结果通过 basename 仍可供当前数据集消费者读取。

## Worker 与所有权

把现有模型推理拆成不写持久结果的纯逻辑；同步接口继续调用该逻辑并按旧合约
原子保存。独立 worker 仅接收父进程生成的受限 request 文件，不接受任意 URL。
父进程复制不超过 50 MiB 的输入快照到任务私有目录并记录 SHA256，检查原音
复制前后 stat 一致。worker 使用相同解释器、shell=False、隐藏窗口、
local_files_only=True；只能写私有临时结果，不发布最终结果。

父进程用单个调度线程管理队列和唯一 child handle；支持可配置硬截止时间，
终止并有界等待，仅操作持有的自有句柄。不得按持久 PID 盲杀进程。
Windows 使用带 KILL_ON_JOB_CLOSE 的 Job Object 并在 child 执行前安全绑定
（先挂起/分配/恢复）；绑定失败则终止 child、任务失败，不降低清理保证。
其他平台使用可测试的进程组/父进程退出策略；未支持平台明确拒绝后台任务。
这一原生所有权边界必须先用轻量假 worker 验证，不能先跑真实 Whisper。

worker 输出文件最大 8 MiB，父进程读取时有界并再次验证全部 Schema、
nonce、源 ID/摘要、片段起点顺序与总时长；stdout 仅小状态协议，读取时有界。
输入、worker JSON、临时结果只在任务目录内，拒绝路径/链接逃逸。

## 发布、取消、重启

同一任务锁决定最终胜者：取消/超时已生效时不得发布结果。
先完成子进程退出及输出校验，再原子发布带 nonce 的独立最终结果，
最后原子写 succeeded 状态。这是两个文件操作，不能宣称跨文件崩溃事务。
若发布后状态写入失败，恢复时只在结果 Schema、task/nonce/源摘要全部匹配且
没有持久 cancelled/timed_out 标记时确认成功；否则标 interrupted/冲突诊断。
取消决策先持久化、再终止 worker，防止退出前迟到结果变成功。

启动时 queued 不自动执行（标 interrupted，用户显式重试），running 标
interrupted 或按上述提交规则恢复；从不依据旧 PID 接管/杀其他进程。
损坏/未来版本状态可诊断跳过，不阻断全部列表，也不被静默重写。
退出时停止调度、取消队列、终止并回收 child，有界 join；清理失败保留所有权并
对外显示失败，不伪报取消完成。重试使用新 task_id，不复用旧 nonce 或记录。

## 验收与边界

先假 worker：正常、启动失败、超时、卡住/退出失败、坏/大协议、崩溃；
队列满、并发提交、重复取消、取消/发布竞争、写盘失败、结果错 nonce、
重启不同状态及 JSON 损坏、退出清理、无修改原音/旧结果。
再临时目录实际缓存 CPU HTTP 提交/查询/成功和安全取消，双 Python 全回归。
独立审查通过后才上传代码。009C 再增加结果 GET/PATCH+expected_revision、
逐段增删改/时间校对和工作台任务 UI；训练切片属于 C2C-010。

## 开放实现决策

核对 Win32 Job Object 在本机 Python 3.10/3.12 的可用性和嵌套 Job 限制；
若环境不允许绑定，只把后台任务标 unavailable，保留同步接口，不假装硬取消。
进度协议/恢复提交日志与用户取消先后顺序需审查后固定，再写实现。

## 审查细化与预检检查点

已读取 ChatGPT PLAN 必要细化，以下优先于前文模糊部分：
1. 使用小范围 ctypes CreateProcessW 取得有效进程/主线程句柄，挂起创建后
   绑定 KILL_ON_JOB_CLOSE，再 ResumeThread；不得用 Popen 私有句柄接口。
2. 最终结果 os.replace 成功就是提交点。同任务锁内取消先赢则持久意图，
   发布先赢则成功不可再取消；等待退出不长持任务锁。
3. 取消/超时的持久意图和实际回收状态分开；无法回收则阻止新 worker。
   启动恢复只信有效 task/nonce/摘要/Schema，不按 PID 接管，不因文件存在伪成功。
4. 快照有界复制并检查原件 stat，私有目录所有路径拒绝链接逃逸。
5. request 字段/大小、stdout 读取中预算、8 MiB 候选输出和最终结果均验证。
6. 1 running + 5 queued 在同锁内收单；单调运行截止、拒收/取消/有界关闭，
   生命周期单例，重复测试客户端不能创建多调度器。
7. 新任务唯一结果与旧同步合约隔离；逐段编辑/UI 另开 009C。

2026-10-25 原生只休眠子进程预检在 Python 3.12.8/3.10.20 均 PASS：
挂起创建→执行前分配 Job→恢复→关闭 Job→5 秒内进程结束，句柄清理完成。
可复现：python tools/windows_job_probe.py（仅 Windows）。
未加载模型、未创建产品任务、未修改原件。不是失败注入/嵌套 Job/父进程崩溃
测试完成声明，也不是生产 owned_worker 抽象。下一步先为这些失败路径写 RED。
本机日志 c2c-009b-job-preflight312.txt / c2c-009b-job-preflight310.txt。
