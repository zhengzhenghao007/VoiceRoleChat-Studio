# C2C-009A 离线转写基线验收

TASK_ID: C2C-009A
STATUS: PASS，Iteration 2 最终独立审查 DONE/PASS，无剩余必修项。
日期：2026-10-25（Australia/Sydney）；基线 9db4d93。

## 本轮交付

Whisper 构造明确 `local_files_only=True`，保留本地模型、设备、精度配置；
加载缺失/损坏时返回安全且可操作的 503，不缓存失败对象，修复后可重试。
非法语言在模型加载前返回 422，模型特定不支持的语言同样拒绝。
复用音频库 canonical UUID/扩展名/真实路径规则；非法名称 400，缺失或逃逸 404。
推理锁覆盖懒生成器、元数据与片段验证、结果发布；本轮刻意采用较宽的锁范围，
保证同目标按推理顺序发布，暂不增加第二套锁或多进程协调。

验证时间、概率有限/范围、段落起止与时长（容差 0.01 秒）；无声段也校验。
总处理段最多 100000，文本最多 1 Mi 字符，编码 JSON 最多 8 MiB。
原有 API 字段及 transcripts/<audio-stem>.json 合约保留；同目录临时文件
flush/fsync 后 replace，失败保留原结果，清理暂存，拒绝目标路径逃逸。
上传转写在上传完成后通过 run_in_threadpool 卸载模型调用。

Codex 裁决：请求支持已安装 Whisper 的语言集合，而不缩至示例的五种；
数据集模块仍只接受原有五种语言，本轮未扩大训练语言承诺。
本轮为 C2C-009 的第一小项，不是任务队列、取消、硬超时或逐段编辑完成声明。

## 实际测试命令与结果

| 命令 | 结果 |
|---|---|
| `python -m unittest discover -s tests -p test_transcription_offline.py -v`（初始 RED） | 9 项：7 failure、1 error，exit 1；构造、路径、错误、保存、串行与线程卸载缺陷被确认 |
| 同上（初次 GREEN） | 9 项通过，exit 0 |
| 同上（补充元数据 RED） | 12 项中 1 failure：无声段越界未拒绝，exit 1 |
| `python -m unittest discover -s tests -v`，Python 3.12.8 | 107 项，106 通过/1 已知跳过，24.482 秒，exit 0 |
| `C:\Users\zsh\anaconda3\envs\gpt-sovits\python.exe -m unittest discover -s tests -v`，Python 3.10.20 | 107 项，106 通过/1 已知跳过，35.581 秒，exit 0 |
| `python <evidence>/c2c-009a-real-api.py` | 实际本机 Uvicorn + HTTP，离线 CPU 转写与上传转写均 200，缺失本地模型 503；5.156 秒，exit 0 |
| `git diff --check` | 通过，exit 0 |

新增 12 项测试使用临时上传/结果/数据集目录与假懒模型；包含结果兼容、
真实数据集消费者读取、并发遍历互斥、坏元数据、发布失败保旧文件、目标逃逸、
泛化错误、非法语言提前拒绝和异步上传线程身份校验。
跳过项为既有 Windows 真符号链接权限需求，不是新增转写测试失败。
本轮没有前端修改，C2C-008 Chromium 26 项证据保留，不宣称重新运行浏览器。

## 真正的离线 CPU HTTP 结果

临时目录中复制既有 `datasets/test_character_japanese_v1/audio/voice.wav`，
使用已有 small / cpu / int8 模型缓存，设置 HF_HUB_OFFLINE 与
TRANSFORMERS_OFFLINE；产品代码仍独立强制 local_files_only。

- 输入时长：8.064 秒。
- 返回语言：ja，probability 1.0。
- 片段：0.56–5.56 秒。
- 文本：あのなさとる、まあいい、また今度話そう。
- 普通 API 结果 JSON 与响应段落一致，上传转写返回相同文本。
- 指定不存在的本地模型后 503，不含临时目录路径。
- 原音 SHA256 与 mtime 均未变；临时 HTTP 服务已退出。

既有 55 项资源大小/mtime 与基线一致；上游 YAML SHA256 仍为
B9481D695F777839ABC5DA1D14B913BACEA3A9DA556B9E0CA0277CCFA85E9AF5。
未改动用户原音、旧转写、角色、模型与训练数据；无安装、下载或 GPU 训练。
证据在本机 visualizations/2026/10/22/01a161c2-4f3c-7a12-a0ac-2e48a0e427b0：
c2c-009a-red.txt、c2c-009a-metadata-red.txt、c2c-009a-green.txt、
c2c-009a-python312.txt、c2c-009a-python310.txt、c2c-009a-real-api.py/.txt。

## 剩余问题与下一步

现有同步接口仍占用请求直到推理完成。线程卸载不等于取消/超时，排队锁也没有
持久任务语义。旧结果成功重转写会有意替换同名结果；没有修订或编辑 API。
仅保证同一进程内串行，继续使用单进程后端。
下一项 C2C-009B：设计持久任务、隔离 Whisper worker、超时/取消/重启恢复，
然后增加版本化转写结果与逐段校对。不能把本轮算作整项 C2C-009 完成。

## 独立审查修复（Iteration 2）

Iteration 1 审查要求：跨片段起点不能倒序，包括空白段。
新增 RED：13 项中 1 failure，确认倒序仍被发布；随后增加 previous_start
在丢弃空白文本之前检查，允许相同起点，不在本轮额外拒绝有序重叠段。
定向 13 项全部通过（0.172 秒），覆盖空白段在前/后、保留旧结果以及相同起点。
最终完整回归：Python 3.12 108 项（107 pass/1 skip），24.208 秒；
Python 3.10 同样 108 项（107 pass/1 skip），35.872 秒，均 exit 0。
最后补充的等起点/空白段断言还通过了定向测试；运行时代码未再变化。
本次只修改排序校验，遵照审查不重复真实 CPU 推理；原有真实结果证据仍有效。
原始证据：c2c-009a-order-red.txt、c2c-009a-order-green.txt、
c2c-009a-python312-final.txt、c2c-009a-python310-final.txt。
