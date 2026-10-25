# C2C-014A：版本化会话与完整消息轮次

EXECUTED — TASK_ID: C2C-014A — STATUS: PASS

独立审查iteration1：DONE/PASS，ACCEPTED=true，无必须返工项，允许发布。

使用标准库SQLite建立独立的sessions/studio.sqlite3，仅首次合法创建会话时初始化。
GET/health/模块导入不会建立缺失数据库。角色ID、角色修订、名字、提示词及两种语言在创建时快照保存。
提供会话创建/列表/详情/改名及消息读取API，不开放任意用户/助手消息写入，不调用LLM或TTS。

内部append_turn以BEGIN IMMEDIATE事务同时保存完整消息对与修订号；不预写孤立用户消息。
相同请求UUID/内容返回原TurnReceipt（原修订和消息ID），即使后面已有新轮次；不同内容复用UUID返回409。
不同请求的旧修订同样409。消息生成和网络操作不在数据库事务内。
列表与消息读取使用只读连接和读事务，避免并发写入时看到不一致的修订/消息数。

数据库user_version1和记录schema1都受版本门控，未来/损坏数据不自动修复。
写入既有数据库前先以只读方式探测版本；未知版本不以写模式尝试恢复日志。
固定目录和数据库、相关journal/wal/shm路径拒绝链接/重解析/数据库硬链接；SQL使用参数绑定。
上限1000会话、100完整轮次/会话、分页100；逻辑预算不是磁盘/内存硬配额。
进程内没有长期数据库连接；2秒SQLite busy timeout。只支持本机单后端部署，不承诺不可信外部程序改写文件时的安全。

## 实测

证据目录：`C:\Users\zsh\.codex\visualizations\2026\10\22\01a161c2-4f3c-7a12-a0ac-2e48a0e427b0`，前缀c2c-014a。

| 命令 | 真实结果 |
|---|---|
| `python -m unittest discover -s tests -p test_sessions.py -v` 初始RED | 缺少schemas.session，导入错误 |
| 同命令实现首轮 | 7项主体断言通过，但两项夹具清理失败：测试中的sqlite3连接上下文不会自动close，Windows文件仍被占用 |
| 同命令修夹具后 | 显式closing连接并提交注入记录，7项通过，0.250秒 |
| 同命令最终存储专项 | 8项通过，0.296秒，增加硬链接/路径逃逸、原回执重试和只读保护 |
| `python -m unittest discover -s tests -p 'test_sessions*.py' -v` | 10项通过，0.449秒，包含实际ASGI API契约/无效角色不创建DB |
| `python -m unittest discover -s tests -v` | Python3.12.8：262项，261通过、1既有Windows符号链接权限跳过，68.303秒 |
| `& 'C:\Users\zsh\anaconda3\envs\gpt-sovits\python.exe' -m unittest discover -s tests -v` | Python3.10.20：262项，261通过、1同一跳过，103.024秒 |
| 独立根目录Uvicorn真实HTTP探测 | /health200；OpenAPI新会话/LLM路由注册；/api/sessions200空列表；读前后未创建项目DB；自有测试服务器确认停止 |
| 原资源核验 | 55项大小/UTC修改时间未变；上游YAML SHA256保持B9481D695F777839ABC5DA1D14B913BACEA3A9DA556B9E0CA0277CCFA85E9AF5 |
| `git diff --check` / `git check-ignore sessions/studio.sqlite3` | 差异格式通过；私有会话存储被忽略 |

重点故障注入：INSERT消息对后、更新修订前抛SQLite错误，事务回滚，消息仍为空且revision1。
两个不同连接同时提交revision1只有一个成功，另一个revision_conflict，最终仅一对消息。
未来数据库和未来会话记录拒绝后逐字节不变；非SQLite文件不重建；角色快照损坏明确invalid_record。
API拒绝用户指定system_prompt、无效角色/标题、越界分页和任意助手消息POST。
测试只用隔离临时数据，没有向用户项目数据库写入测试消息。

## 范围与下一步

原角色/音频/训练存储不改动，没有下载、模型加载、GPU尝试或LLM请求。
尚无角色聊天、生成任务状态、取消、上下文裁剪、翻译、播放队列或聊天UI；不能把存储基础称为完整聊天。
C2C-012真实训练、C2C-013真实LLM验证仍保持PARTIAL。
下一最小任务014B：利用此存储和013适配器完成固定角色快照的文字回复、上下文预算、取消与幂等提交；以假提供方验证，真实LLM等待外部条件。
