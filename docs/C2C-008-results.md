# C2C-008 音频库与录音导入验收

TASK_ID: C2C-008
STATUS: PASS；ChatGPT 独立代码审查 DONE/PASS，无必修项。
日期：2026-10-25，Australia/Sydney。

## 交付

音频库 API 与中文音频页：上传、列表、详情、原音播放、显式检查旧文件、
新建参考片段、填入角色草稿。新增录音申请/录制/预览/导入状态与失败重试。
上传保留旧 helper/响应字段，转写上传接口仍兼容。

独立 PyAV 子进程强制本地容器读取，禁止外部媒体协议；上传分块不超过 1 MiB、
文件最多 50 MiB，输入最多 1800 秒、200000 帧、64000000 级别处理样本预算
（实际上限 64 * 1024 * 1024）。默认 30 秒超时，可配置至 120 秒。
超时只终止本次自有子进程，失败清理保留引用以便后续/退出重试。
参考片段另存 3–10 秒 mono 32000 Hz PCM16 WAV，按 round(seconds * 32000)
定位采样边界，并由父进程独立验证格式、帧数、实际源长度和完整输出。
没有操作系统级硬内存上限，不将帧/采样预算描述为此类保证。

存储名为 canonical UUID + 允许扩展名，拒绝路径/符号链接逃逸。
元数据有 Schema、源大小和 mtime 校验，损坏/过期时兼容显示 uninspected。
文件与 sidecar 分别原子发布，普通异常回滚新文件；不是跨文件断电事务。
浏览器录音最多 180 秒/50 MiB；停止、权限取消、错误和 pagehide 释放轨道，
预览 Blob URL 在替换/丢弃/导入成功/退出时撤销，失败保留预览。

## 实际执行

在允许本机子进程与 HTTP 的开发环境运行，未安装依赖：

| 命令 | 结果 |
|---|---|
| `python -m unittest discover -s tests -p test_audio_library.py -v`（初始 RED） | exit 1，新增 Schema 不存在，确认测试先失败 |
| `python -m unittest discover -s tests -p test_audio_library.py -v`（实现后） | 通过；最终总套件含真实 WAV/MP3 解码与参考转换 |
| `python -m unittest discover -s tests -p test_audio_api.py -v` | 4 项通过，含上传转写兼容、旧文件检查、错误与播放 |
| `python -m unittest discover -s tests -v`，Python 3.12.8 / av 18.0.0 | 95 项，94 通过、1 跳过，23.922 秒，exit 0 |
| `C:\Users\zsh\anaconda3\envs\gpt-sovits\python.exe -m unittest discover -s tests -v`，Python 3.10.20 / av 17.1.0 | 95 项，94 通过、1 跳过，35.438 秒，exit 0 |
| `python tests/studio_browser.py --screenshots-dir <evidence>/c2c-008` | 26 项检查全部通过，exit 0 |
| `node --check frontend/app.js`、`node --check frontend/audio.js` | 通过，exit 0 |
| `git diff --check` | 通过；Windows LF/CRLF 提示不是测试失败 |

跳过项仍为 Windows 创建真实符号链接所需权限；模拟解析逃逸已覆盖。
实际 MP3 测试用 libmp3lame 编码夹具再解码和裁剪；未将扩展名检查冒充解码。
非法数据、截断 WAV、错容器、超体积、子进程超时/缺依赖/错协议、
假 worker 返回错误片段、元数据失败回滚均有用例。

浏览器先 RED（缺少音频页）；实现后曾发现测试夹具原生假麦克风缺少
`--use-fake-ui-for-media-stream`，补齐该参数及 fake-device 后通过。
测试 setter 的错误 evaluate 调用已修正。没有修改浏览器库或请求真实麦克风。
最终覆盖旧 17 项工作台行为、音频上传/播放/裁剪到草稿、拒绝权限、
合成麦克风预览/显式导入/轨道停止、虚拟时间 180 秒自动停止、
导入失败保留预览重试、取消未完成权限、退出清理、手机布局和无意外页面错误。
HTTP 使用实际临时 FastAPI 服务；推理仍为假服务，音频解码为真实 PyAV 子进程。
桌面 1440 与手机 390 截图均已打开检查：内容可读、堆叠合理、无横向溢出。
README 音频截图来自隔离测试数据。

## 真实本地文件检查与保护

只读检查 `uploads/1872fed43b834d91afb88080700f099c.mp3`：严格 MP3 解码返回 422。
进一步只读容器诊断发现 MP4 `ftyp`，按 M4A 解码为 AAC、48000 Hz、mono、
8.064 秒。原文件未改名、未重写、未生成元数据。此项是已发现的数据格式问题；
建议保留原件，导入实际扩展名正确的 M4A 副本。

既有 55 项资源大小/mtime 与基线一致（不是全量内容 hash 证明）。
上游 tts_infer.yaml SHA256 仍为
B9481D695F777839ABC5DA1D14B913BACEA3A9DA556B9E0CA0277CCFA85E9AF5。
没有模型下载、依赖安装、GPU 训练或真实麦克风采集。

本机证据目录：
`C:\Users\zsh\.codex\visualizations\2026\10\22\01a161c2-4f3c-7a12-a0ac-2e48a0e427b0`。
包括 c2c-008-red.txt、c2c-008-api-green.txt、c2c-008-python312-final.txt、
c2c-008-python310-final.txt、c2c-008-browser-final.txt、
c2c-008-real-inspect.txt、c2c-008-real-container-diagnosis.txt 与截图子目录。

## 决策与边界

按 ChatGPT PLAN 细化执行：小型 worker 协议、解码预算/时限、元数据陈旧回退、
独立参考检查、只追加片段、canonical 播放、录音资源状态。
Codex 决策：worker 通过当前解释器和绝对脚本路径运行，避免 cwd 导入差异；
音频 UI 独立为 audio.js 模块；真实容器错名保持原件并报告，不自动修数据。
语义变更集中于音频边界，未重写架构。

本轮未真实测试 FLAC/OGG/M4A 上传成功、真实硬件麦克风或全新环境安装；
M4A 只读解码已有实际证据。无法将这些列为完整格式/设备兼容验收。
单用户单后端进程边界保留，无数据库、多进程协调或音频删除功能。
下一项最小任务：C2C-009 转写任务与逐段校对，先检查本地 Whisper 资源，禁止隐式下载。

独立审查核对执行记录 41–43，3.10 原始输出随后补录为独立记录。
非阻塞建议：未来扩展 worker 协议时，将 stdout 限制前移至读取期间；
当前可信本地 worker 仅输出小型 JSON，父进程在接收后校验 64 KiB。

## 补充格式验证（2026-10-25）

不修改产品实现，在临时目录生成 4 秒测试音并经实际 API 上传、读取、生成参考片段。
`python <evidence>/c2c-008-formats.py` 在 Python 3.12 / av 18.0.0 与
Conda Python 3.10 / av 17.1.0 均 exit 0：
FLAC/flac、M4A/AAC、OGG/Opus 三组上传、播放、参考 API 均 200；
每份输出独立 wave 校验为 mono 32000 Hz PCM16、96000 帧（3 秒）。
日志为 c2c-008-formats312.txt 与 c2c-008-formats310.txt。
因此上文“未真实测试这些格式上传”是首次交付时的历史限制，本补充关闭了
代表性容器流程覆盖缺口；不代表所有 codec/容器变体或真实麦克风设备均已验收。
未修改用户文件、生产配置或产品代码；不增加 unittest 计数。
