# C2C-009C 转写校对工作台验收

TASK_ID: C2C-009C
STATUS: PASS，ChatGPT 独立审查 DONE/PASS，无必修项。
日期：2026-10-25 Australia/Sydney，基线 f4c7e8c。

## 交付与数据边界

增加转写记录列表/详情、校对副本创建/读取/修订 API，以及中文「转写」工作区。
原始未版本化 JSON 与 schema2 后台结果保持只读；校对保存为新 UUID 的 schema3
文件，revision 从1递增，不改变旧任务的 nonce 提交/恢复规则。
精确原始 JSON 字节经8MiB有界读取、SHA256校验，显式创建时保存在
.review_sources/<sha256>.json，避免原同步接口未来重转写导致原文不可追溯。
快照去重，遇到同名坏快照拒绝覆盖；快照先发布，后发布校对记录，允许安全孤儿
快照，不声称跨文件崩溃原子。GET/LIST 不创建快照、不迁移或重写旧记录。

PATCH 同时检查 expected_revision/expected_sha256，共享进程锁内比较、校验、
递增、原子替换。保留 duration、原音引用、来源身份/哈希、created_at。
服务端派生完整 text，拒绝未知字段、空白文字、无效/非有限时间、逆序/重叠、
越界、非法语言；最多100000段、1Mi字符、8MiB存储。原始重叠结果仍可查看、
在浏览器修正后保存。原音缺失不隐藏文字，播放地址只允许本地 canonical 音频。

新增 GET /api/transcriptions/records，GET /records/{id}；
POST /reviews，GET/PATCH /reviews/{id}。新副本201，冲突409、非法修改422、
缺失404。旧同步/后台任务及数据集消费者保持兼容，未改进程管理或 Whisper参数。

## 工作台

音频详情「转写此音频」→选择语言→显式提交后台任务→查询阶段/取消→打开结果。
只在「转写」标签可见时轮询，离开标签/页面停轮询及片段播放。
取消意图与确认 cancelled 分开显示；任务失败保留服务器诊断代码。
记录列表识别原始/任务/校对三类；片段可试听、改起止/文字、增删和重排。
不同记录的迟到响应不得覆盖当前记录；读取失败恢复显示记录的选中身份并可重试。
保存响应采用 draftEpoch，提交期间的新编辑保留dirty；409保留草稿并提供明确重载。
切换记录询问丢弃，切换标签保留草稿；beforeunload同时保护角色、录音及转写草稿。
全程原生DOM/textContent/value，恶意文本不执行HTML。

## 实际测试与失败证据

| 命令/环境 | 结果 |
|---|---|
| `python -m unittest discover -s tests -p test_transcript_reviews.py -v` 初始RED | 新模块不存在，exit1；实现后8项通过 |
| `python -m unittest discover -s tests -p test_transcript_review_api.py -v` 初始RED | 新依赖不存在，exit1 |
| `python -m unittest discover -s tests -p 'test_transcript_review*.py' -v` 中间GREEN | 10项通过，0.427秒；之后增加并发/失败快照用例 |
| `python -m unittest discover -s tests -v` Python3.12.8 | 147项，146PASS/1已知skip，27.931秒，exit0 |
| 同上 Conda Python3.10.20 | 147项，146PASS/1已知skip，44.470秒，exit0 |
| `python tests/studio_browser.py --screenshots-dir <evidence>/c2c-009c` | 新标签缺失初始RED；已有26项先通过，扩展后37项通过；最终日志见后续记录 |
| `node --check frontend/transcriptions.js`、app.js、audio.js | 全部通过 |
| `git diff --check` | 通过，只有Windows行尾提示 |

后台新增12项覆盖原始只读、精确快照/去重/坏快照、哈希/修订冲突、并发实例
仅一方提交、非法内容、原子失败保旧、读取异常/未来版本、路径逃逸、孤立音频，
以及真实旧数据集消费者读取校对结果。唯一skip仍为既有Windows真符号链接权限项。

浏览器初始失败后修复了下拉框缺少精确可访问名称，补充 aria-label。
另有实际RED确认读取失败后选中记录与仍显示的记录不同，导致重试被跳过；
修复恢复已显示记录的身份。读取重试成功后的旧错误提示也另有RED/GREEN记录。
最终包括原26项及11项转写检查：提交/阶段/取消/结果、原始不变与新副本、
修订冲突/重载、pending保存新草稿、dirty切换/标签保留、片段增删重排验证、
请求身份、读取失败重试、孤立音频、DOM/手机、可见标签轮询。

浏览器使用真实临时FastAPI/HTTP、schema3存储、PyAV上传处理，但转写调度为
临时假Worker手动推进，未调用真实Whisper或真实麦克风。角色、模型、上传、
转写、校对快照和任务依赖全部覆盖到临时根目录。未把替身流程称作真实推理。
真实离线CPU后台任务证据保持C2C-009B，不需要重跑模型。

## 视觉与资源

已打开1440宽桌面与390宽手机完整截图：输入/按钮/文字可读，手机堆叠，
没有横向溢出。桌面覆盖原音缺失仍可校对文字，手机覆盖可播放与片段编辑。
截图含隔离样例和故障注入状态，不含用户真实角色或转写内容。
原55项资源大小/mtime一致；上游YAML SHA256仍为
B9481D695F777839ABC5DA1D14B913BACEA3A9DA556B9E0CA0277CCFA85E9AF5。
无安装、下载、训练，未修改用户原音/模型/旧转写。

证据目录：本机visualizations/2026/10/22/01a161c2-4f3c-7a12-a0ac-2e48a0e427b0，
包含c2c-009c-reviews-red/first.txt、api-red/green.txt、browser-red/second/third.txt、
browser-retry-red.txt、browser-notice-red.txt、browser-final.txt、python312/310.txt，
截图在c2c-009c子目录。日志均记录实际命令结果，未伪造通过。

## 裁决和限制

选择独立校对副本而不修改schema2任务结果，代价是新增一个记录与源快照；
换取原始推理/恢复协议不受编辑影响。继续同一用户授权checkout和单进程边界。
GET/LIST只发现canonical根目录UUID JSON；不迁移任意旧文件名，坏文件诊断保留。
没有持久浏览器草稿、完整修订历史/撤销、任务自动清理、多进程写锁或模型下载。
源快照/历史任务占用磁盘，暂不自动删除。校对支持Whisper语言，数据集仍有其
现有五语限制。本轮仅证明旧数据集能读新记录，不宣称已完成分段切片。
下一项C2C-010：从校对记录构建对应片段音频与标注，并做语言/分隔符/质量检查。

最终浏览器重跑37项PASS，读取失败重试和旧提示清除均已实测；未再改运行时代码。
最终桌面/手机截图已打开检查，README截图使用隔离数据，已清除过期错误提示。
