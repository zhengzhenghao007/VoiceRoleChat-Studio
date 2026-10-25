# C2C-010：分段数据集构建验证

STATUS: PASS；ChatGPT iteration 2 独立审查通过，无必需修复。基线 main 28a292a。

实现：从已保存 Schema 3 校对副本生成独立数据集，校验修订号和字节摘要；源音快照、单次顺序解码、逐段单声道 32 kHz PCM16、GPT-SoVITS 标注及 Schema 2 manifest。临时目录完整验证后无覆盖发布，保留原校对、原音及同名已有目录。列表兼容旧元数据，并对损坏/未来版本记录诊断。

Worker 使用既有 Windows Job Object 归属与超时机制；失败清理保留句柄及临时目录，阻止新构建。最终复核和 rename 共用校对存储锁。读取已知任务源音哈希，拒绝同长度替换；解码时长与校对时长偏差超过 20ms 拒绝。每段 0.3–30 秒，最多 1000 段；拒绝无序、重叠、越界、全静音、不支持的语言和标注分隔符。输出峰值、RMS 和长短/轻声/削波警告。

## 实际执行

在 Windows 两个已有环境中执行，无安装、下载或训练：

| 命令 | 真实结果 |
|---|---|
| `python -m unittest discover -s tests -v` | Python 3.12.8：167 项，166 通过、1 跳过，29.535 秒 |
| `& 'C:\Users\zsh\anaconda3\envs\gpt-sovits\python.exe' -m unittest discover -s tests -v` | Python 3.10.20：167 项，166 通过、1 跳过，41.443 秒 |
| `python tests/studio_browser.py --screenshots-dir <evidence>/c2c-010` | Chromium 41 项通过，含实际原生构建、草稿门禁、409/422/429/503/504、手机布局及不发起训练 |
| `python <evidence>/c2c-010-real-api.py` | 真实日语音频副本，实际 HTTP/Worker，201/409/GET/list 通过，1.172 秒 |
| `& <conda-python> <evidence>/c2c-010-real-api.py` | 同一真实验收通过，1.203 秒，两套输出 SHA 相同 |
| `git diff --check` / JS 语法检查 | 通过 |

跳过项为既有 Windows 真符号链接权限测试；模拟逃逸和路径解析失败诊断用例通过。
41 项浏览器流程的推理和转写仍使用替身，数据集生成使用真实轻量解码 Worker；没有把替身检查当作真实模型验收。

真实样本为原有 8.064 秒日语 WAV 的临时副本。两个手工校对窗口 [0.56,3]、[3,5.56] 输出 78080/81920 帧，2.44/2.56 秒，总计 5 秒。未重新运行 Whisper，也没有强制对齐或听感质量验收。

- 片段 1 SHA256：`8765227025d53b12020d8f2763228d213e6cdad87ece7d8cbb4e1d46a7690130`
- 片段 2 SHA256：`466d0e112bf116b4e7320f1eed40729fcb6346469a7d8427a6b6d09cdda5ea5e`
- 源 SHA256：`878cb849691db6ade93e7780583e87f19f47f3c19e35ee809a795d4855e65f03`

证据位于本机 `C:\Users\zsh\.codex\visualizations\2026\10\22\01a161c2-4f3c-7a12-a0ac-2e48a0e427b0`，`c2c-010-*` 日志；不将临时用户音频及绝对路径日志上传仓库。桌面和手机截图已视觉检查，README 附隔离数据桌面截图。

## 失败与修复记录

先执行缺模块/缺 API 等 RED，之后实现 Worker、存储和 API；边界用例实际复现旧 /build 路径逃逸、分隔符注入、时长不符、已知源音替换和路径循环导致列表中断，最小修复后通过。旧 /build 单条输出契约保留。

前端最初在浏览器 RED 前编写，发现后撤回本轮新增 UI/module，先运行缺入口失败再重新实现；此处如实记录流程纠正。第一次原生浏览器构建暴露夹具全静音，替换为生成正弦波夹具，未放宽静音校验；随后修复测试拦截器参数签名，最终 41 项通过。

首次 Python 3.10 全量运行 165 项发生一项既有合成超时用例错误。确定性测试复现 Windows watchdog 关闭连接时平台时钟尚未到截止值，原来误报传输失败。`synthesis_service.py` 最小增加 watchdog 触发标记，用该标记归类超时；RED 后定向 15 项和最终双环境全量通过。未重写 TTS 生命周期。

## 保留与限制

55 项已有资源的大小及修改时间与原审计基线一致，上游 `tts_infer.yaml` SHA256 仍为 `B9481D695F777839ABC5DA1D14B913BACEA3A9DA556B9E0CA0277CCFA85E9AF5`。没有删除、改写或上传原有音频、训练产物和模型权重。

目前仅 Windows、单后端进程构建；Worker 截止不等于整条 HTTP 的硬期限，样本预算不是 OS 内存硬限制。manifest 上限 1 MiB，校对读取上限 8 MiB；极端大文本仍受输出协议上限约束。旧识别记录无源音摘要时无法验证历史对应关系。质量指标不证明语言、内容或对齐正确。

下一最小任务 C2C-011：先修复 `backend/workers/training_worker.py:prepare_dataset` 删除/重建同名目录的旧路径，再设计训练只读消费已准备数据集及可回收任务生命周期。本轮未调用训练接口，未运行 GPU 训练。

## 独立审查复核（iteration 2）

列表异常已有共享 safe() 捕获 RuntimeError，重新运行原定向10项通过，未重复添加无效捕获；审查同时指出的 cleanup_stage 直接 resolve 边界确实缺失，新增清理路径循环用例 RED 后统一使用 safe()，11项通过。加强列表用例确认异常目录不隐藏正常 valid 数据集。完整回归167项。首轮执行记录写入 Windows 沙箱虚拟状态目录，审查未读到；已在实际连接状态目录重新登记真实原日志，output IDs67–73 可读取，无修改测试结果。
