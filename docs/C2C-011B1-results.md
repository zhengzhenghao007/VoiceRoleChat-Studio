# C2C-011B1：训练输入快照

STATUS: PASS；iteration1独立审查通过，无必需修复。基线 f0826a7。

预制数据集训练在独占任务工作目录内创建 inputs/<dataset>，逐字节复制固定清单的 manifest、review和WAV，原manifest逻辑路径不改，仅重建副本transcript.list指向任务内部音频。来源记录含job_id、原manifest/review摘要、每段SHA/帧数、数量/时长、任务相对路径和创建时间，并进入模型导出metadata。不是硬链接。未知额外文件不复制。

复制前完整校验原数据，复制时摘要对比，复制后重新验证源内容和副本PCM/摘要/标注，最后原子发布来源JSON才返回给预处理。Worker快照失败不会调用外部命令。文件逐个独占创建，任务inputs拒绝复用；失败保留部分文件供诊断。来源目标先独占保留再原子替换为完整JSON；写入失败可能留下空/无效占位，不能视为成功记录，Worker不会进入预处理。

限制：最多1000段，WAV每个≤1920044字节，manifest≤1MiB，review及标注≤8MiB，快照及来源总量≤128MiB，复制块≤1MiB。元数据有界读取，不根据标注中的任意绝对路径决定复制输入。Legacy训练分支保持011A行为。

## 实际执行

| 命令 | 结果 |
|---|---|
| `python -m unittest discover -s tests -p test_training_snapshots.py -v` 初次 | 6项，5缺模块错误；非法输入拒绝用例初次通过，随后在真实实现上再次验证 |
| 同上实现后 | 6项通过，0.952秒 |
| `python -m unittest discover -s tests -p test_training_safety.py -v` 集成RED | 13项，1失败，证明仍传原目录 |
| 同上集成GREEN | 13项通过，2.044秒 |
| `python -m unittest discover -s tests -p 'test_training_*.py' -v` | 20项通过，3.170秒 |
| `python -m unittest discover -s tests -v` | Python3.12.8：187项，186通过、1已知权限跳过，33.373秒 |
| `& 'C:\Users\zsh\anaconda3\envs\gpt-sovits\python.exe' -m unittest discover -s tests -v` | Python3.10.20：187项，186通过、1同一跳过，45.351秒 |
| `git diff --check` | 通过 |

证据使用真实临时两片段WAV与Schema2产物。验证精确文件字节、重建标注、来源哈希、源文件后续改写不影响副本、复制中同大小/同mtime内容篡改拒绝、部分复制保留、目标冲突、非法身份、文件与总预算、未知额外文件忽略、坏源不发布成功记录。Worker集成上游run_command全部拦截，API原有Thread替身；未运行真实预处理/GPU、未下载或安装。前端未改，没有重跑浏览器，不冒充旧浏览器证据为本轮结果。

本机日志为 `C:\Users\zsh\.codex\visualizations\2026\10\22\01a161c2-4f3c-7a12-a0ac-2e48a0e427b0\c2c-011b1-*`。无运行时用户数据提交仓库。

## 后续与边界

完成快照之后不再依赖源数据文件；但拥有任务目录写权限的外部进程仍可修改副本，这不是OS强制不可变。当前训练仍用daemon线程和等待式子进程，缺取消/期限/恢复，外部共享上游权重目录竞争也未隔离。C2C-011B2继续处理自有进程、持久队列与任务恢复，尚未做真实GPU训练验收。

保护核验：55项原资源大小/修改时间不变，上游YAML SHA256与基线一致。来源记录未单列重建标注摘要，为审查记录的非阻塞增强；严格标注核验已实施。
