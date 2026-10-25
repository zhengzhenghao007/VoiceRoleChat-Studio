# C2C-014B：后端文字角色回复

EXECUTED — TASK_ID: C2C-014B — STATUS: PARTIAL（后端代码通过，真实模型未配置）

独立审查iteration1：DONE/PASS_WITH_PARTIAL_LIVE_VALIDATION，ACCEPTED=true，无必须返工项，允许发布。

新增reply/poll/cancelAPI。单个全局活动回复，无排队；使用会话创建时的角色提示词与回复语言。
上下文按完整轮次保留最新连续历史，40消息/总16000/单条8000字符；超大系统提示词先拒绝。
生成成功后进入committing，仅在SQLite完整消息对提交成功后completed；网络/认证/取消/修订冲突不留下半条消息。
已持久提交请求优先回放且验证user_text，重启或提供方缺失不触发重复生成；请求标识以会话UUID和requestUUID为作用域。

进行中及终态内存缓存上限64，活动任务不会淘汰；失败/取消缓存命中不自动重试。
未提交任务状态不持久化，重启或淘汰后404；没有自动恢复或重跑。只有完整消息与回执是持久数据。
没有SQLite版本升级，也没有公开任意助手消息写入、地址/密钥/提示词修改接口。
生成取消等待本端异步HTTP清理，但不声称提供方计算已停止。提交开始后取消409；退出先关闭回复接纳，等待提交线程而不取消它。
关闭期间其他服务依然通过finally清理；不在SQLite事务内调用网络。

## 实际命令与结果

证据目录 `C:\Users\zsh\.codex\visualizations\2026\10\22\01a161c2-4f3c-7a12-a0ac-2e48a0e427b0`，前缀c2c-014b。

| 命令 | 结果 |
|---|---|
| `python -m unittest discover -s tests -p test_replies.py -v` 初始RED | 缺少schemas.reply，导入错误 |
| 同命令首轮GREEN | 6项通过，0.504秒 |
| 取消竞态RED→GREEN | 新增取消等待者断开/提供方吞取消用例，8项中2失败；记录取消意图、合并重复取消并shield清理后8项通过，0.635秒 |
| `python -m unittest discover -s tests -p test_replies_api.py -v` RED | 缺少api.replies，导入错误 |
| `python -m unittest discover -s tests -p 'test_replies*.py' -v` API首轮 | 10项通过，0.787秒 |
| 双Python首轮全量 | 273项，272通过、1既有符号链接权限跳过；3.12为69.632秒，3.10为104.773秒 |
| 关闭顺序RED | 10项manager检查中1失败：旧接线先关闭训练队列；重接为回复管理器先关闭接纳和自有任务 |
| `python -m unittest discover -s tests -v` 最终 | Python3.12.8：274项，273通过、1既有权限跳过，69.285秒 |
| `& 'C:\Users\zsh\anaconda3\envs\gpt-sovits\python.exe' -m unittest discover -s tests -v` 最终 | Python3.10.20：274项，273通过、1同一跳过，104.774秒 |
| 整链路HTTP适配验收 | reply202→completed、消息2条；实际本机HTTP假提供方只请求1次，重试同请求回执一致且无新提供方请求；不是真实模型推理 |
| 原资源核验 | 原55项大小/UTC修改时间不变；上游YAML SHA256保持B9481D695F777839ABC5DA1D14B913BACEA3A9DA556B9E0CA0277CCFA85E9AF5；未创建项目测试数据库 |
| `git diff --check` | 通过 |

覆盖：角色快照/语言进入system上下文、整轮裁剪和40消息预算、重启后已提交回放且不访问失效提供方、缓存上限、忙碌、失败无消息、旧修订拒绝、取消前Worker未启动、重复取消、调用者断开、提交中拒绝取消、关闭等待提交和关闭接纳。
实际HTTP夹具返回FAKE REPLY；只写隔离临时数据库，没有用户会话或模型数据上传。

## 剩余

真实LLM仍未配置，不能宣称真实回复质量验收完成；C2C-012训练仍PARTIAL，未重试。
尚无聊天页面、双语翻译、聊天音频和流式打断。下一最小任务014C：工作台会话/历史/发送/取消UI，保留草稿和明确任务未知状态，使用隔离提供方浏览器验收。
