# C2C-011B3：持久训练队列、取消与原子产物提交

STATUS: PASS；iteration1独立审查通过，无必需修复。基线 `04eebb6`。

本轮完成训练后端生命周期，尚未验证真实 GPU 训练或声音质量。所有原生训练测试仅运行临时目录中六个固定步骤的无害假脚本，输出明确标记为 SIMULATED / NOT TRAINED 的字节，不加载预训练模型。

## 实现与验收语义

- 一个监督器、一个外层 Windows Job Object 流水线、最多五个排队任务。持久入队序号保证相同时间戳也按 FIFO 执行。训练根目录 Windows 文件锁在恢复或状态修改前获得，另一个进程不能接管；没有 PID 文件接管。
- `request.json` 固定身份、nonce、请求摘要、配置和来源摘要；父进程独占写 `state.json`，子进程只写严格、限大小的进度与候选。POST/start 保留201；公开取消202；旧 GET 字段兼容，新增决策/error_code和诊断读取。公开 API 不再为请求创建训练线程。
- 监督器在首次训练 API 访问时启动并恢复，非训练功能及健康检查不初始化训练存储。应用退出先关闭训练接纳，再处理外层流水线及其他模块清理。
- 取消、超时、退出意图先持久保存，进程树确认回收后才进入终态。清理失败保留归属、阻止队列，允许重试。取消意图写盘失败不返回成功，也不擅自当作取消；真正截止或退出遇到存储故障仍会回收进程，但不伪报持久终态，并阻止新任务。
- 全任务期限以单调时钟计算，默认86400秒、最大604800秒，排队时间不计。之前的每命令期限配置保留并传入子进程。准备、输入复制和全部嵌套命令属于外层 Job；父进程候选哈希与系统 IO 按字节限界，不能抢占阻塞的系统调用，提交前仍会复核决策及截止。
- 排队时绑定来源摘要，执行前重新验证。预制数据集继续使用独立片段快照；旧式输入也先对角色、音频、转写作有界复制并核对摘要，任务只用副本构建私有数据集。失败保留部分诊断输出。
- 预处理日志/特征、GPT/SoVITS权重及候选导出均位于任务私有目录，不向上游共享权重目录或全局实验目录写入。两个固定模型文件、角色、路径、大小、摘要及候选身份都须校验。每权重最多8GiB，流式哈希，过大先拒绝；禁止额外候选文件和畸形源路径。
- 父进程确认子进程退出并回收后，构造最终manifest与提交证明，在状态锁下复核新决策，再无覆盖rename完整模型目录。目录提交是完成点，之后状态写入失败可通过证明恢复completed。模型manifest补全注册器必需的experiment_name，正式目录可发现，私有目录不可发现。
- 重启不重跑queued/preparing/training，未提交任务标记interrupted；已有取消/超时/关闭意图协调恢复。有效提交证明恢复completed。坏/未来状态与请求只诊断，旧平铺记录只读，包括原有cosyvoice记录；旧任务取消返回409。

## 实际执行结果

| 命令/验证 | 实际结果 |
|---|---|
| `python -m unittest discover -s tests -p test_training_queue_store.py -v` 初次 | 缺模块RED；随后5项存储/提交测试通过，后续扩充至8项 |
| `python -m unittest discover -s tests -p test_training_queue.py -v` 初次 | 缺模块RED；8项首轮GREEN，后续扩充至14项 |
| `python -m unittest discover -s tests -p test_training_pipeline.py -v` 初次 | 2项：1失败、1错误；私有权重配置及候选协议实现后通过 |
| `python -m unittest discover -s tests -p test_training_queue_api.py -v` 初次 | 2项缺持久依赖错误；实现后通过，扩充至3项含惰性初始化 |
| `python -m unittest discover -s tests -p 'test_training_queue*.py' -v` 最终 | 25项通过，5.671秒 |
| `python -m unittest discover -s tests -p test_training_native.py -v` 共享冲突/注册修复后 | 真实HTTP+外层/嵌套Job的4项通过，11.735秒；假流水线成功、旧模式成功、运行取消及截止后后代心跳停止 |
| `& 'C:\Users\zsh\anaconda3\envs\gpt-sovits\python.exe' -m unittest discover -s tests -p test_training_native.py -v` | 4项通过，24.999秒（截止时钟同步后） |
| `python -m unittest discover -s tests -v` 最终 | Python3.12.8：229项，228通过、1已知权限跳过，56.329秒 |
| `& 'C:\Users\zsh\anaconda3\envs\gpt-sovits\python.exe' -m unittest discover -s tests -v` 最终 | Python3.10.20：229项，228通过、1同一跳过，85.775秒 |
| `python tests/studio_browser.py --screenshots-dir <evidence>/c2c-011b3` | Chromium41项通过；真实工作台HTTP，隔离数据、模拟转写/推理，数据集使用真实轻量解码；没有训练请求 |
| `git diff --check` | 通过 |
| 原资源核验 | 原55项大小与UTC修改时间均未变，上游配置SHA256仍为 `B9481D695F777839ABC5DA1D14B913BACEA3A9DA556B9E0CA0277CCFA85E9AF5` |

已知跳过为需要额外 Windows 权限的真实符号链接测试；路径逃逸、解析故障及进程排他锁另有实际/模拟检查。

### 失败、复现与修复

1. 新增固定时间戳FIFO、磁盘故障退出、超大候选用例，实际RED共3失败；加入持久入队序号、失败时进程回收及读前大小检查后通过。
2. 新增旧记录列表/诊断用例，复现旧记录没有入队序号导致KeyError；展示列表保持兼容排序，FIFO仅用于新队列。
3. 新增配置传递与旧模式快照用例，实际1失败/1错误；保留命令期限配置并独立复制旧输入后通过。
4. 首次训练总回归49项，旧测试仍期待已移除的Thread而错误；另一次原生取消心跳未启动。没有隐藏失败，增强诊断后继续核查。
5. 首次双环境并行全回归中，3.12的225项通过；3.10出现1项失败：4秒任务截止在解释器/准备完成前触发，测试却假定后代已存在。改为先确认后代启动，再用注入单调时钟跨过截止，仍检查真实进程树心跳停止；生产默认仍为time.monotonic。
6. 随后的诊断捕获一次准备阶段流水线失败。用真实Windows读句柄确定性复现：持有progress.json读取期间，原子替换失败为JobError。仅在本轮训练进度发布增加0.5秒内的PermissionError有界重试，不放宽其他错误，不改全项目存储实现；真实读句柄RED→GREEN，原生流水线随后通过。
7. 模型发现闭环RED复现成功导出仍不在注册器列表：缺少experiment_name。export_models补全必需字段；已提交假模型可发现且status=ready，仍不等于权重可加载。
8. 畸形候选源字段字典导致TypeError的RED，增加显式类型校验后变为受控拒绝。全任务截止意图无法写盘的RED，增加预算到期仍回收的故障路径后通过。

完整日志保留在本机 `C:\Users\zsh\.codex\visualizations\2026\10\22\01a161c2-4f3c-7a12-a0ac-2e48a0e427b0`，本项前缀 `c2c-011b3-*`；先前失败文件不覆盖，最终全量为 `python312-verified.txt` / `python310-verified.txt`。测试输出通过执行记录供独立审查，不上传用户音频或模型。

## 文件范围

新实现：`backend/schemas/training_queue.py`、`backend/services/training_queue_store.py`、`backend/services/training_queue.py`、`backend/workers/training_queue_worker.py`。
接入：`backend/api/training.py`、`backend/app.py`、`backend/config.py`、`backend/schemas/training.py`、`backend/workers/training_worker.py`。
测试：新增 `tests/test_training_queue_store.py`、`test_training_queue.py`、`test_training_queue_api.py`、`test_training_pipeline.py`、`test_training_native.py`；更新 `tests/test_startup.py`、`test_training_safety.py`。
文档：README、路线图、本报告及本项spec/plan。

## 未执行与下一步

未安装/下载依赖或模型、未调用真实GPT-SoVITS预处理、未进行GPU训练或权重加载/声音质量验收。日志与进程没有OS硬磁盘/内存限制，外部有写权限程序仍可改动工作文件；断电和阻塞系统IO不是本轮可完全防护的情形。模型完整性验证可读较大文件，训练 API 首次恢复可能需要时间。

通过独立审查后完成C2C-011后端生命周期。下一项C2C-012为真实训练产物导出/注册与受控短训练验收，需先做只读环境/资源预检并固定小预算；完整训练UI仍在C2C-019。不因本轮假权重通过就宣称真实模型可训练或可试听。
