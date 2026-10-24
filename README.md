# VoiceRoleChat-Studio

本地优先的 AI 角色语音工作室：围绕角色配置、音频转写、声音训练和模型管理，逐步实现支持多语言字幕与角色声音的对话体验。

**当前处于开发阶段。** 中文工作台已接入角色编辑、模型管理、声音绑定和试听 API，并通过真实浏览器流程测试。真实日语 CPU 合成已验证；LLM 对话和实时语音聊天尚未实现。

## 功能现状

| 模块 | 当前能力 | 验证边界 |
|---|---|---|
| 后端基础 | FastAPI、健康检查、OpenAPI | 已通过实际 Uvicorn HTTP 测试 |
| 角色 | 创建、编辑、版本化 JSON、声音绑定和按角色合成 | 已验证兼容旧记录、修订冲突、绑定和合成配置快照 |
| 音频库 | 上传、解码检查、原音试听、参考片段和录音预览/导入 | WAV/MP3 与 WebM 实际解码通过；录音浏览器测试使用合成麦克风 |
| 语音转写 | faster-whisper 离线加载、串行推理、校验与原子保存 | 已有日语 CPU HTTP 实测；持久任务、取消和逐段编辑待开发 |
| 数据集 | 从音频和转写生成 GPT-SoVITS 标注 | 已有实现；逐段校对、切片与质量检查待开发 |
| 训练 | 后台任务、状态记录和 GPT-SoVITS Worker | 已有训练产物；本轮未重跑 GPU 训练 |
| 模型管理 | 权重配对、版本选择、导出发现、来源去重、ID 冲突处理 | 已有专项回归与真实列表/详情/刷新测试 |
| 推理服务管理 | 状态探测、自有进程启停、超时和正常退出清理 | 已验证真实 CPU 模型启动及清理 |
| 文本合成 | 模型权重串行选择、参考 WAV 校验、WAV 生成与读取 | 已用已有日语模型执行真实离线 CPU 合成；其他语言与长文本待验证 |
| 前端 | 中文角色/模型/音频工作台、声音绑定、服务控制与试听 | 桌面/移动端浏览器验收通过；浏览器测试使用隔离数据和模拟推理 |
| 角色聊天 | LLM、会话历史、双语回复和语音播放 | 规划中 |

## 完整使用流程与开发路线

```text
环境检查 → 创建角色
             ├─ 选择已有模型 ───────────────────────┐
             └─ 上传音频 → 转写校对 → 数据集 → 训练 → 导出模型
                                                   ↓
                                   配置参考音频 → 合成试听 → 绑定角色
                                                   ↓
                           配置 LLM → 文字或录音输入 → 回复/翻译/播放
                                                   ↓
                                         会话保存、备份与导出
```

上图是目标流程，部分步骤仍待实现。详细的 **23 项任务、依赖和验收标准**见 [项目路线](docs/PROJECT-ROADMAP.md)。

- **M1：声音能用**——模型发现、环境配置、真实合成、角色绑定和最小前端。
- **M2：角色能聊**——LLM、会话历史、双语回复、按键录音和自动播放。
- **M3：工作室可发布**——训练工作台、流式打断、系统诊断、备份和首次启动引导。

## 环境要求

- 当前主要开发平台：Windows / PowerShell。
- Python **3.10 或更新版本**；已在 Python 3.10.20 和 3.12.8 的现有环境测试后端。
- 后端依赖见 [backend/requirements.txt](backend/requirements.txt)。
- 训练与推理需要单独准备 GPT-SoVITS、对应的依赖及模型权重；仅安装后端依赖不会完成这些步骤。
- 本仓库不附带声音样本、模型权重、Conda 环境或训练数据。

### 安装后端依赖

从仓库根目录执行：

```powershell
git clone https://github.com/zhengzhenghao007/VoiceRoleChat-Studio.git
cd VoiceRoleChat-Studio
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
```

为避免 PowerShell 激活脚本策略的影响，示例直接使用虚拟环境解释器。
依赖当前没有锁定版本；上面的命令是安装步骤，不代表全新环境已完成验收。

### 启动后端

推荐从仓库根目录检查环境后启动：

```powershell
.\.venv\Scripts\python.exe run.py --check
.\.venv\Scripts\python.exe run.py --host 127.0.0.1 --port 8000
```

使用已有 Python 环境时，将 `.\.venv\Scripts\python.exe` 替换为对应解释器。也可从任意目录以绝对路径调用 `run.py`。
启动器会设置后端模块目录，默认绑定 `127.0.0.1:8000`。
直接使用 Uvicorn 时，仍可执行 `python -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8000`。
正常启动会创建所需数据目录；`--check` 只读检查，不创建目录、不启动服务、不加载 ML 模块或下载模型。

自动化诊断使用 `python run.py --check --json`，stdout 为 JSON。退出码：`0` 表示必需检查通过（可含训练资源缺失告警），`1` 表示依赖或配置错误，`2` 表示命令行参数无效。依赖检查只证明模块可以发现；训练资源检查只核对路径及类型，不证明硬件或模型可用。

打开：

- 健康检查：[http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
- 声音工作台：[http://127.0.0.1:8000/studio/](http://127.0.0.1:8000/studio/)
- 交互式 API 文档：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- OpenAPI：[http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json)

健康检查预期返回 `{"status":"healthy"}`。它仅表示业务服务可响应，不证明 GPU、Whisper 或 GPT-SoVITS 模型已加载。

### 使用声音工作台

后端启动后，直接打开 [声音工作台](http://127.0.0.1:8000/studio/)。前端由同一后端提供，无需额外安装 JavaScript 依赖、启动静态服务器或配置 API 地址。

1. 创建或选择角色，填写角色设定并保存。
2. 在“模型”页查看完整/不完整配对，选择用于当前角色的模型。
3. 上传一段 3–10 秒 PCM WAV，填入准确的参考文字和语言，保存声音绑定。上传不会自动保存角色。
4. 显式点击“启动 CPU 服务”，再生成短句试听。使用播放器播放或下载 WAV，完成后可停止服务。

未保存修改会阻止试听；切换角色前会提示是否放弃草稿。修订冲突和校验失败保留表单，重新加载角色需明确确认。失效的模型绑定不会被自动换掉或清空。
页面不会自动加载推理模型。外部未托管服务仅显示状态；聊天、录音、转写和训练界面留到后续任务。“对话偏好”目前只保存设置，不代表聊天功能已可用。

工作台截图（隔离测试数据）：

![中文角色声音工作台](docs/images/studio-desktop.png)

## GPT-SoVITS 与转写配置

项目默认在根目录的 `GPT-SoVITS/` 查找外部安装，目前仅支持 v2Pro 训练流程。
训练前必须自行准备兼容的上游环境和预训练文件。

| 路径（相对 `GPT-SoVITS/`） | 用途 |
|---|---|
| `GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large/` | BERT |
| `GPT_SoVITS/pretrained_models/chinese-hubert-base/` | HuBERT |
| `GPT_SoVITS/pretrained_models/sv/pretrained_eres2netv2w24s4ep4.ckpt` | 声纹权重 |
| `GPT_SoVITS/pretrained_models/v2Pro/s2Gv2Pro.pth` | SoVITS 生成器初始权重 |
| `GPT_SoVITS/pretrained_models/v2Pro/s2Dv2Pro.pth` | SoVITS 判别器初始权重 |
| `GPT_SoVITS/pretrained_models/s1v3.ckpt` | GPT 初始权重 |

配置通过启动后端之前设置的环境变量生效：

| 环境变量 | 默认值 / 约束 |
|---|---|
| `GPT_SOVITS_ROOT` | `<repo>/GPT-SoVITS`；工具、预训练资源和训练权重发现使用此目录 |
| `GPT_SOVITS_PYTHON` | 保留原开发机 Conda 回退路径；其他机器请显式配置 |
| `GPT_SOVITS_VERSION` | `v2Pro`；当前其他版本会返回明确配置错误 |
| `GPT_SOVITS_GPU` | `0`；当前仅支持单个 GPU 编号，检查不探测真实 GPU |
| `GPT_SOVITS_API_PORT` | `9880`；1–65535，固定使用本机回环地址 |
| `GPT_SOVITS_REQUEST_TIMEOUT` | `2` 秒；大于 0、最多 30 秒，单次探测总时限 |
| `GPT_SOVITS_START_TIMEOUT` | `120` 秒；大于 0、最多 600 秒，启动就绪等待时限 |
| `GPT_SOVITS_STOP_TIMEOUT` | `10` 秒；大于 0、最多 60 秒，停止等待总预算 |
| `GPT_SOVITS_SYNTHESIS_TIMEOUT` | `180` 秒；大于 0、最多 600 秒，状态验证、权重切换与合成共享期限 |
| `WHISPER_MODEL_SIZE` | `small`；模型名称或模型标识 |
| `WHISPER_DEVICE` | `cpu`；可选 `cpu`、`cuda`、`auto` |
| `WHISPER_COMPUTE_TYPE` | `int8`；如 `float32`、`float16`、`auto` 等受支持类型；硬件兼容性在实际加载时判断 |

```powershell
$env:GPT_SOVITS_ROOT = 'D:\tools\GPT-SoVITS'
$env:GPT_SOVITS_PYTHON = 'C:\path\to\your\gpt-sovits\python.exe'
$env:WHISPER_MODEL_SIZE = 'small'
$env:WHISPER_DEVICE = 'cpu'
python run.py --check
```

在启动后端的同一终端设置。两个路径配置的相对值均以仓库根目录解析，与当前工作目录无关。空值、无效版本及无效设备配置会被拒绝。没有隐式加载 `.env` 文件。
角色、数据集、导出模型和任务数据仍保存在仓库内原有目录，不会随工具目录迁移。训练权重扫描跟随 `GPT_SOVITS_ROOT`，导出 manifest 扫描仍在项目的 `models/`。
其他参数见 [backend/config.py](backend/config.py)。首次真实转写可能尝试获取缺失的 Whisper 模型文件；仅启动后端和运行本仓库测试不会触发该模型加载。

## 推理服务启停

业务后端启动时不会自动启动 GPT-SoVITS。准备好上述外部解释器、`api_v2.py`、GPT/SoVITS 初始权重和 BERT/HuBERT 后，显式调用：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/tts/service
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/tts/service/start
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/tts/service/stop
```

本轮以 CPU、`is_half=false`、v2Pro 启动上游服务，子进程设为离线模式，不主动获取缺失模型。
每次启动将独立配置和日志写入 `outputs/tts-service/<run-id>/`，不会改写上游 `tts_infer.yaml`。
资源文件存在并不保证其内容有效；启动失败时查看对应 `service.log`。

返回 `state`、`managed`、`pid`、`detail`。状态含义：`unavailable` 未就绪；`starting` 正在启动；`ready` 兼容接口可响应；`stopped` 已完成显式停止；`failed` 自有进程退出或启动/清理失败。
`ready` 仅验证 OpenAPI 的推理和权重切换路由，不验证服务身份、模型加载或合成质量。探测不发起合成。
手动启动的兼容服务显示 `managed=false`、`pid=null`；对任何外部监听服务请求启停都返回 409，工作室不会接管或结束它。
并发启停返回 409；缺文件或提前退出返回 503；启动或清理超时返回 504。停止时先终止，再在剩余预算内强制结束自有进程；清理失败保留句柄供重试。

**仅支持一个业务后端进程**，不要使用多个 Uvicorn worker 或同时运行多个工作室后端。
正常退出会清理自有子进程；强制结束后端、系统崩溃不保证清理。当前按上游单服务进程管理，不负责其自行派生的孙进程，也不会根据进程名或 PID 文件接管遗留进程。
合成接口只允许操作工作室托管的就绪服务；手动启动的外部服务仍保持只读检测。

### 文本合成与试听

先在 `/api/models` 选取 `ready` 模型，上传或准备一段 **3–10 秒 PCM WAV** 参考音频，并确认其对应文本。参考路径只能位于项目 `uploads/` 或 `datasets/` 中，不接受绝对路径或 `..`。

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/tts/service/start
$request = @{
    model_id = '<从模型列表复制 ID>'
    text = 'こんにちは。'
    text_lang = 'ja'
    reference_audio = 'uploads/<已上传的参考音频>.wav'
    prompt_text = '<参考音频中的准确文本>'
    prompt_lang = 'ja'
} | ConvertTo-Json
$result = Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/tts/synthesize `
    -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($request))
$result
Invoke-WebRequest ('http://127.0.0.1:8000' + $result.audio_url) -OutFile "$env:TEMP\voicerolechat-demo.wav"
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/tts/service/stop
```

文本和参考文本各 1–1000 字符，参考 WAV 最大 10 MiB。语言支持上游 v2 代码 `zh/ja/en/ko/yue/all_zh/all_ja/all_ko/all_yue/auto/auto_yue`，模型是否擅长该语言需实际验证。
服务在一把锁内依次选择 GPT、SoVITS 权重，再完成非流式合成；并发合成或启停返回 409。模型不存在为 404，模型不完整为 409，非法请求/参考音频为 422，未托管或未就绪为 503，上游异常为 502，超时为 504。
不确定的上游失败会清理自有进程，需要显式重新启动后重试，以免迟到的请求影响下一次选择。
结果包含 `id/model_id/audio_url/sample_rate/duration_seconds`，校验后的 WAV 原子保存到 `outputs/tts/`，最大 32 MiB。参考音频使用临时快照，不修改原文件；读取接口只开放合法生成 ID。
已验证一条日语短句的 CPU 合成和非静音 WAV；这不代表全部模型、语言、硬件或声音质量已通过验收。

## 角色编辑与声音绑定

`POST /api/characters` 创建角色；`PATCH /api/characters/{id}` 只更新提交的字段。编辑时带上最近读取的 `expected_revision`，版本冲突返回 409，此时先重新读取再决定如何合并。
角色 ID 为 32 位小写十六进制字符串。`id/created_at/schema_version/revision` 不可直接修改；空 PATCH、未知字段和必需字段的空值返回 422。

绑定声音的 PATCH 示例：

```json
{
  "expected_revision": 1,
  "voice_config": {
    "version": 1,
    "model_id": "<模型列表中的 ID>",
    "reference_audio": "uploads/<参考 WAV>.wav",
    "prompt_text": "<参考音频中的文本>",
    "prompt_lang": "ja",
    "text_lang": "ja"
  }
}
```

声音配置为完整对象替换；省略 `voice_config` 保留绑定，显式 `"voice_config": null` 清除绑定。
保存时复用模型与参考 WAV 的校验，不要求推理服务启动，也不切换模型。绑定不代表角色完成过训练；旧的 `voice_file/model_status` 元数据仍然保留。
需要发声时先启动托管服务，再向 `POST /api/characters/{id}/synthesize` 提交 `{"text":"こんにちは。"}`。它使用已保存的声音配置，返回相同的 WAV 结果和读取地址。没有绑定时为 409。
正在合成的请求保留开始时的配置快照；之后编辑角色只影响后续请求。模型或参考文件被删除后，下一次合成会重新校验并报错。

新记录使用 `schema_version=2`、`revision=1`。旧记录读取时展示版本 1、修订号 0 和空声音配置，但**不重写旧文件**；首次编辑才原子迁移到版本 2，并保留未知旧字段及创建时间。高于当前支持的存储版本返回 409，损坏配置返回可定位的 500，不自动覆盖。并发保护限于单个后端进程。

## 模型目录与 API 行为

模型注册器读取：

```text
<GPT_SOVITS_ROOT>/GPT_weights_v2Pro/       # *.ckpt，例如 actor_1234abcd-e15.ckpt
<GPT_SOVITS_ROOT>/SoVITS_weights_v2Pro/    # *.pth，例如 actor_1234abcd_e8_s400.pth
models/<job_id>/manifest.json      # 导出记录与对应权重
```

- 按规范化实验名配对，GPT 优先选择最高 epoch；SoVITS 优先 step、再 epoch。
- 同源导出模型只有在两份来源权重和实验身份均匹配时才与训练记录合并。
- `ready` 表示发现 GPT 和 SoVITS 两份文件，**不等于已验证权重可加载或可以合成声音**。
- `incomplete` 表示只有一侧权重。无有效权重的导出记录不进入列表。
- 无冲突模型保留原有短 ID。发生冲突时使用带稳定摘要后缀的扩展 ID；查询歧义短 ID 返回 **409**，不存在的 ID 返回 **404**。客户端应使用列表返回的 ID。
- 损坏或非法 manifest 会被跳过并记录告警；导出路径受到目录范围校验。旧 Windows 绝对路径仅按导出目录尾部安全映射，不读取任意外部位置。

## API 概览

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/health` | 服务健康检查 |
| POST / GET | `/api/characters` | 创建角色 / 列出角色 |
| GET | `/api/characters/{character_id}` | 角色详情 |
| PATCH | `/api/characters/{character_id}` | 编辑角色或替换/清除声音绑定 |
| POST | `/api/characters/{character_id}/synthesize` | 使用保存的角色声音合成 |
| POST | `/api/voices/upload` | 上传音频 |
| GET | `/api/voices` | 列出音频（旧文件可显示为未检查） |
| GET | `/api/voices/{stored_filename}` | 音频详情 |
| GET | `/api/voices/{stored_filename}/audio` | 播放原音频 |
| POST | `/api/voices/{stored_filename}/inspect` | 显式解码检查旧音频 |
| POST | `/api/voices/{stored_filename}/reference` | 新建 3–10 秒参考 WAV，不覆盖原音 |
| POST | `/api/transcriptions` | 转写已上传音频 |
| POST | `/api/transcriptions/upload` | 上传并转写 |
| POST | `/api/datasets/build` | 构建数据集 |
| POST | `/api/training/start` | 启动训练，可能消耗 GPU 资源 |
| GET | `/api/training` | 训练任务列表 |
| GET | `/api/training/{job_id}` | 训练任务详情 |
| GET | `/api/models` | 模型列表 |
| GET | `/api/models/refresh` | 刷新模型发现 |
| GET | `/api/models/{model_id}` | 模型详情 |
| GET | `/api/tts/service` | 本地 GPT-SoVITS 服务状态 |
| POST | `/api/tts/service/start` | 显式启动自有 CPU 服务 |
| POST | `/api/tts/service/stop` | 停止自有服务 |
| POST | `/api/tts/synthesize` | 选择模型对并合成 WAV |
| GET | `/api/tts/audio/{audio_id}` | 读取已生成 WAV |

请求体及上传格式以运行中的 `/docs` 为准。训练接口不是普通健康检查，不要将它加入自动冒烟测试。

## 开发与测试

测试开发依赖见 [backend/requirements-dev.txt](backend/requirements-dev.txt)，从根目录运行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

常规测试使用临时空文件、假 HTTP 服务和轻量子进程，不加载真实模型，也不会启动 GPU 训练。真实 CPU 验收单独执行并记录。
部分测试只读访问当前本地角色和模型记录，因此本地损坏的配置文件可能影响测试结果。

开发依赖声明固定了 `httpx==0.28.1`；这不是完整的运行时或传递依赖锁文件，也不是全新环境安装验收。
最近验证：两套现有 Python 环境均运行 **108 项测试：107 项通过、1 项跳过**，包括真实 HTTP 启动、合成事务、角色持久化、音频解码/裁剪、离线转写和静态入口。另有 Chromium 工作台 **26 项流程检查**全部通过。
跳过项是需要额外 Windows 权限的真实符号链接测试；另有模拟路径解析逃逸测试通过。
浏览器验收使用已有 Python Playwright 与 Chromium（不是运行工作台的依赖），不自动安装或下载：

```powershell
python tests/studio_browser.py --screenshots-dir "$env:TEMP\voicerolechat-browser-evidence"
```

该测试使用临时角色、模型、上传和输出目录及模拟推理，覆盖草稿、修订冲突、迟到响应、模型失效、离线重试、启停和试听，生成桌面/手机截图。真实模型的 CPU 证据与浏览器替身验证分别记录。
这不是全新环境安装或 GPU 推理的完整验收。详见 [C2C-001 审计](docs/C2C-001-audit.md)、[C2C-002 实现记录](docs/C2C-002-results.md)、[C2C-003 启动验证](docs/C2C-003-results.md)、[C2C-004 服务管理](docs/C2C-004-results.md)、[C2C-005 合成验证](docs/C2C-005-results.md)、[C2C-006 角色声音](docs/C2C-006-results.md)、[C2C-007 工作台](docs/C2C-007-results.md) 和 [C2C-008 音频库](docs/C2C-008-results.md)。

## 音频导入与参考片段

打开工作台的「音频」页，可上传 WAV、MP3、M4A、FLAC、OGG 或 WebM，单文件最多 50 MiB。
上传以扩展名对应的容器进行真实解码，拒绝空文件、损坏文件和格式不匹配；旧文件不会自动改写。
选择原音并填写开始/结束秒数，可另存 3–10 秒的单声道 32 kHz、16-bit PCM WAV。
点击「用于当前角色」只填入角色草稿；补充对应参考文本、语言并保存后才能用于角色试听。

录音需要浏览器麦克风权限（localhost 或 HTTPS）。点击开始、停止后先本地预览，再显式点击导入；
导入失败保留预览供重试。最长 180 秒，停止、取消或离开页面会释放麦克风。
浏览器验收仅使用合成麦克风，没有采集用户真实声音。

后端需要 PyAV（`av`，见运行依赖）。解码在隔离子进程中运行，默认超时 30 秒，
可用 `AUDIO_PROCESS_TIMEOUT` 配置，最大 120 秒；限制时长、帧数和处理样本预算。
原文件与元数据分别发布，普通异常会回滚新文件；突然断电可能留下无元数据文件，列表按未检查兼容读取。
这些限制不是操作系统级的内存硬限制。

![音频库示例（隔离测试数据）](docs/images/studio-audio-desktop.png)

## 离线转写

`POST /api/transcriptions` 接收上传返回的 `stored_filename` 和可选语言代码（如 `ja`）；
`POST /api/transcriptions/upload?language=ja` 支持上传并转写。省略语言为自动检测。
Whisper 只读取已经准备好的本地模型/缓存，绝不隐式下载；`WHISPER_MODEL_SIZE`
可填已有模型名或完整本地模型目录。缺失、损坏或设备配置不兼容时返回 503。
请先显式准备模型资源，并在启动后端的同一个 Python 环境验证。

结果保存到 `transcripts/<音频 UUID>.json`，成功重转写会替换该结果；失败保留旧结果。
当前仍是同步请求，同一进程中串行执行；上传接口使用线程池避免阻塞事件循环，
不代表可取消或有推理硬超时。持久任务和逐段编辑尚未实现。
已有 8.064 秒日语样本通过实际离线 CPU HTTP 验收，详见 [C2C-009A 结果](docs/C2C-009A-results.md)。

## 仓库结构与本地数据

```text
backend/        FastAPI 路由、Schema、服务与训练 Worker
run.py          根目录启动与只读环境检查入口
frontend/       中文工作台静态资源，调用真实后端 API
tests/          后端和模型注册测试
docs/           审计、测试记录与开发路线
characters/     本地角色配置
uploads/        上传的原始音频
transcripts/    转写结果
datasets/       数据集、音频副本与标注
training_jobs/  任务状态、配置和日志
models/         导出模型及 manifest
outputs/        生成结果
GPT-SoVITS/     用户单独准备的外部安装
```

音频、角色数据、模型、训练产物及外部安装默认由 `.gitignore` 排除，不随代码上传 GitHub。
更新前请备份自己的数据；本地绝对路径迁移仍需检查配置和相关记录。

## 常见问题

- **`No module named 'api'`**：从根目录启动时加入 `--app-dir backend`。
- **`No module named 'faster_whisper'` 或上传依赖缺失**：确认安装依赖和启动服务使用同一个 Python 解释器。
- **模型列表为空**：仓库不附带权重；检查上述目录、文件命名及 manifest 告警。
- **音频扩展名正确仍被拒绝**：检查真实容器；审计曾发现一份名为 `.mp3` 的旧文件实际为 M4A/AAC。保留原件，导入扩展名与真实容器一致的副本；不要仅凭文件名认定解码格式。
- **模型显示 ready 但不能发声**：模型列表只检查文件配对；确认已启动托管服务、权重可以加载、参考 WAV 及文本有效，并查看服务日志。
- **训练启动失败**：核对 `GPT_SOVITS_PYTHON`、外部安装和预训练文件，查看 `training_jobs/` 中的日志；不要直接删除原有产物。
- **测试在受限环境挂起**：曾观察到 Windows 沙箱中的异步本机套接字初始化受限；请在允许本机通信的开发终端运行，并区分环境故障与代码失败。

## 许可证

本项目代码使用 [MIT License](LICENSE)。GPT-SoVITS、Whisper、预训练权重和用户导入的音频/声音模型各自遵守对应许可证与授权条件，本仓库的代码许可证不替代它们。
