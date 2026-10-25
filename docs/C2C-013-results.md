# C2C-013：本地 LLM 提供方适配

EXECUTED — TASK_ID: C2C-013 — STATUS: PARTIAL（代码通过，真实提供方缺失）

独立审查iteration1及端口边界复审iteration2均为PASS_WITH_PARTIAL_LIVE_VALIDATION，ACCEPTED=true，无必须返工项，允许发布。

## 实现

本机兼容HTTP适配器、环境变量延迟配置、模型发现与固定提示连接测试已实现。
`GET /api/llm/config`不发请求；`GET /api/llm/models`发现模型；`POST /api/llm/check`仅发送固定短提示。
没有任意公开completion或配置写入API，后续014可复用内部complete(messages)。
协议参考2026-10-25查阅的 [Ollama官方兼容文档](https://docs.ollama.com/api/openai-compatibility)，仅实现其文字非流式子集。

配置仅限HTTP回环及/v1路径；localhost直接固定到127.0.0.1，避免DNS解析绕过，IPv6支持[::1]。
拒绝远程地址、userinfo、query、fragment和其他路径，不使用环境代理、自动跳转或重试。
密钥仅环境保存，repr/API/错误不回显。无效可选配置不影响后端健康或其他功能。
配置首次使用缓存，变更需重启；没有隐式.env加载、提供方启动、模型拉取/加载或云端调用。
本机提供方自身可能代理云模型，回环目标限制不构成其离线推理证明。

请求40条/总16000/单条8000字符；固定max_tokens默认128；原始响应256KiB、模型列表1000项、输出16000字符。
每实例单请求，整体asyncio期限和网络超时，取消关闭客户端/响应，拒绝压缩响应；有界同步JSON解析后复查截止。
错误是固定detail.code，未知上游正文不透传。期限不表示可抢占操作系统阻塞或同步解析。
运行依赖声明httpx，并补根目录只读启动检查，未安装任何软件。

## 真实执行结果

证据根目录为 `C:\Users\zsh\.codex\visualizations\2026\10\22\01a161c2-4f3c-7a12-a0ac-2e48a0e427b0`，本项前缀c2c-013。

| 命令 | 结果 |
|---|---|
| `python -m unittest discover -s tests -p test_llm.py -v` RED | 缺失services.llm_service导致导入错误 |
| 同命令首轮GREEN | 6项通过，1.159秒 |
| `python -m unittest discover -s tests -p 'test_llm*.py' -v` 首轮HTTP | 10项通过；客户端有界关闭后，假服务打印预期ConnectionAbortedError；修正夹具处理该关闭事件 |
| 同命令最终 | 12项通过，5.795秒；含取消后响应关闭、未知正文脱敏、并发、超时、模型/文字预算等 |
| `python -m unittest discover -s tests -v` | Python3.12.8：252项，251通过、1既有Windows符号链接权限跳过，68.368秒 |
| `& 'C:\Users\zsh\anaconda3\envs\gpt-sovits\python.exe' -m unittest discover -s tests -v` | Python3.10.20：252项，251通过、1同一跳过，103.765秒 |
| `python -m unittest discover -s tests -p test_startup.py -v` 新httpx依赖检查RED→GREEN | RED为11项中1失败；补依赖声明后11项通过，5.992秒 |
| 同启动测试Conda3.10 | 11项通过，10.392秒 |
| 实际环境ASGI接口+本机HTTP提供方探测 | /health200；/api/llm/config200、model_not_configured；/api/llm/models503/provider_unavailable，约2.39秒；没有实际模型推理 |
| 原资源核验 | 55项大小和UTC修改时间不变；上游YAML SHA256仍为B9481D695F777839ABC5DA1D14B913BACEA3A9DA556B9E0CA0277CCFA85E9AF5 |
| `git diff --check` | 通过 |

HTTP夹具使用真实ThreadingHTTPServer和回环套接字；返回FAKE REPLY，不是真实LLM。
配置读取无上游流量；故意设置错误环境代理仍成功；302未跟随、401正文不透传、超大/残缺JSON拒绝、慢请求504。
已有启动测试仍实际启动根目录Uvicorn；没有重新跑无变化的前端浏览器流程，上次41项通过的边界保持。
全量回归后只补httpx启动依赖诊断和调整import位置，随后双环境启动检查通过；没有更改LLM处理逻辑。

最终URL边界补测复现端口0被默认80替换（8项中1失败）；改为只在端口缺省时使用80，端口0受控拒绝。
修复后Python3.12的12项LLM专项全部通过，5.816秒；Conda3.10同12项通过，7.524秒。

## 验收缺口

本机没有运行中的默认本地提供方，未配置模型；未安装/下载或使用云端凭据补齐环境。
连接协议可独立验收，真实模型发现、实际文本生成与质量验收留待已有本地提供方准备好后显式执行。
尚未实现会话、角色提示词编排、聊天UI、流式回复、翻译或聊天声音队列。
下一最小任务014A可先完成版本化会话/消息存储，不依赖真实LLM服务；014B再接入请求生命周期和角色文字聊天。
