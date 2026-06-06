# vault watch — daemon 生命周期与增量扫描语义

`aifd vault watch` 不是"每次启动重新全扫"的 daemon。关停 → 重启 期间的进度被持久化到
`~/.aifd/watch-state.json`，重启后只读"上次扫到 → 现在"的增量，已扫过的 bytes 不会重复
通过 detector。

本文档讲清楚：

- state file 长什么样、记录哪些字段
- 关停时怎么落盘
- 重启时怎么恢复
- 五种边界情况（首次跑 / 新文件 / rotation / SIGKILL / state 损坏）
- 为什么这么设计（opportunistic save 的取舍 + DedupeCache 的兜底）
- 怎么排查 state 异常

---

## State file 结构

文件位置：`~/.aifd/watch-state.json`

```json
{
  "version": 1,
  "files": {
    "/Users/quincy/.claude/projects/-Users-quincy-foo/abc.jsonl": {
      "offset": 12345,
      "size": 12345,
      "mtime": 1733412345.0,
      "line_no": 87
    },
    "/Users/quincy/.codex/sessions/2026-06/xyz.jsonl": {
      "offset": 4080,
      "size": 4080,
      "mtime": 1733411111.0,
      "line_no": 12
    }
  },
  "total_catches": 17,
  "catches_by_day": {
    "2026-06-04": 5,
    "2026-06-05": 12
  }
}
```

每条 `files[path]` 记录的字段：

| 字段 | 类型 | 含义 |
|---|---|---|
| `offset` | int | **权威值**。已扫描到的 byte 偏移。下次 seek 到这里继续 |
| `size`   | int | 上次 `stat` 看到的文件大小。rotation 检测用 |
| `mtime`  | float | 上次 `stat` 的 mtime。诊断用，不参与决策 |
| `line_no`| int | 当前估算的行号（best-effort，从已知 offset 向前计数）。仅用于 UI 显示，不参与 offset 推进 |

顶层 `total_catches` 和 `catches_by_day` 是统计字段，给 `aifd vault watch status` 和 `aifd ai
today / weekly / monthly` 的 E10 联动用（`catches_by_day` 用**本地日期**键，所以窗口比较不
需要时区换算）。

`version` 是 schema 版本号。当前 `_STATE_SCHEMA_VERSION = 1`。不认识的 version 会触发**保守
重置** —— 整个 state 当空处理，所有文件下次从 0 重扫。设计选择：宁可重扫也不要喂半懂的
schema 给新代码。

代码位置：`aifd/vault/watch_state.py:WatchState`

---

## 关停时（SIGTERM / SIGINT）

`Daemon.run()` 注册了信号处理，收到 SIGTERM（launchd 触发或 `aifd vault watch stop` 触发）
或 SIGINT（前台 Ctrl-C）走 `_shutdown()`：

```
1. observer.stop() + observer.join(timeout=5)   # 关 watchdog
2. server.stop()                                # 关 HTTP server，释放端口
3. PORT_FILE.unlink()                           # 删 ~/.aifd/watch.port
4. state.save()                                 # 落盘
```

`state.save()` 用 **tmp + rename** 原子写：

```python
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text(json.dumps(...))
tmp.replace(path)    # POSIX 原子操作
```

这意味着：哪怕在写中途 SIGKILL，磁盘上要么是上一次完整的 state，要么是新的完整 state，
**永远不会是半截 JSON**。

代码位置：`aifd/vault/watch.py:Daemon._shutdown`、`aifd/vault/watch_state.py:WatchState.save`

---

## 重启时（恢复 + 增量）

`Daemon.run()` 的启动序列：

```
1. WatchState.load()                  # 从 ~/.aifd/watch-state.json 读回内存
2. server = start_server()            # 起 127.0.0.1 HTTP server
3. notifier.probe_permission()        # 发首次测试通知
4. observer.schedule(...)             # 给每个 root 装 watchdog handler
5. observer.start()
6. worker thread / sweeper thread     # 启动两条后台线程
7. _enqueue_all_tracked()             # ⭐ 把所有已知 jsonl 入队一次
8. _stop_event.wait()                 # block until shutdown signal
```

第 7 步是关键：daemon 一启动就把所有跟踪过的 jsonl 入队，让 worker 跑一遍 `_scan_one`。
worker 拿到 path 后调 `TailReader.read_new_lines(path)`：

```python
key = str(path)
rec = self._state.files.get(
    key, {"offset": 0, "size": 0, "mtime": 0.0, "line_no": 0}   # 没记录 → 从 0
)
...
with path.open("r", encoding="utf-8", errors="replace") as f:
    f.seek(rec["offset"])     # ← 跳到上次扫到的位置
    buf = f.read()             # ← 只读新增的部分
```

所以哪怕 daemon 关了 5 分钟、5 小时、5 天，每个文件**只读"上次扫到 → 现在"的 delta**。已经
跑过 detector 的 bytes 不会重新跑。

代码位置：`aifd/vault/watch.py:TailReader.read_new_lines`

---

## 五种边界情况

| 场景 | 行为 |
|---|---|
| **正常关停 + 重启** | 增量扫，每个文件从 `rec["offset"]` 开始 |
| **首次跑**（没 state file） | `WatchState.load()` 返回空 state；每个 jsonl 当新文件，`rec["offset"]` 默认 0，从头全扫一次 —— 这次性能开销最大 |
| **新增的 jsonl**（state 里没记录） | 当作首次跑那种 case 处理：从 0 全扫 |
| **文件被 rotate / truncate**（`stat.st_size < rec["offset"]`） | TailReader 检测到 size 缩了，记录被重置成 `{"offset": 0, ...}`，从 0 重扫整个文件 |
| **state file 损坏 / 不认识的 version** | `load()` 打 warning 后返回空 state；等价于首次跑，所有文件从 0 全扫 |

### Rotation 检测细节

```python
if stat.st_size < rec["offset"]:
    logger.debug(
        "File %s shrank (%d → %d), reading from start",
        path, rec["offset"], stat.st_size,
    )
    rec = {"offset": 0, "size": 0, "mtime": 0.0, "line_no": 0}
```

任何让文件 size 缩水的操作都触发重扫：log rotation、`truncate`、provider 改了 schema 把旧
session 删了重写。**保守策略 —— 重扫一遍只是浪费几 ms CPU；漏扫一行可能漏一个真 secret**。

### Partial trailing line 处理

Claude / Codex 写 jsonl 不是原子的：你可能扫到一半正好读到 `{"role":"user","content":"my key i` 没换行。
TailReader 会把这种**最后一行没 `\n` 结尾**的 buffer 留着不消费，offset 只推进到最后一个完整
行的末尾。下次读会把这半行 + 它的后续一起读到、当成完整一行送 detector。

```python
emit = lines
if lines and not lines[-1].endswith(("\n", "\r")):
    emit = lines[:-1]
    consumed = sum(len(line) for line in emit)
else:
    consumed = len(buf)
```

不会**漏行**也不会把**半行**喂给 detector（半行触发误报的概率比完整行高得多）。

---

## SIGKILL（`kill -9`）行为

`kill -9` 没有信号处理机会，`_shutdown()` 不会跑，state file 不落盘。重启时怎么办？

要拆成两个时间点看：

```
T0  ─── 上一次 state.save() 成功落盘
        │
        │  worker 持续在扫文件，offset 在内存里推进
        │  期间可能命中 → state.save()（opportunistic save，见下节）
        │
T1  ─── 最后一次 state.save() —— 内存里的 offset 真正落盘
        │
        │  worker 继续扫，offset 又往前走，但内存里
        │
T2  ─── kill -9 —— 内存里 T1..T2 的 offset 推进**丢失**
```

T2 重启时，每个文件的 offset 回到 T1 那次落盘的值。T1..T2 之间扫过的 bytes 会被**重新扫一遍**。

会出什么问题？

- ❌ **不会漏扫**：扫过的会再扫一遍，不会少
- ⚠️ **可能重复命中通知**：如果 T1..T2 之间扫过的 bytes 里有真 secret，重启后会再扫到同一个

第二点由 `DedupeCache` 兜底：

```python
_DEDUPE_TTL = timedelta(minutes=5)
```

按 `(category, snippet_redacted)` 做 key，5 分钟内同一 secret 只弹一次通知。如果你 SIGKILL
后**马上**重启，重复检测的 secret 落入 dedupe 窗口被吃掉，用户不会收到重复通知。

注：DedupeCache 是**内存中**的 LRU + TTL，重启后是空的。所以兜底只在"上次通知 → 重启完
成扫到同一处" 5 分钟内有效；如果你停了 1 小时再重启，重启会把"1 小时前已经通知过"的 secret
再通知一次。这个 corner case 接受的折衷 —— 把 dedupe 也持久化到 disk 是过度工程，比"偶尔
重复通知一次同一已知 secret"的成本高得多。

---

## 为什么 `_scan_one` 是 _opportunistic save_

注意 worker 里这一行：

```python
def _scan_one(self, path: Path) -> None:
    any_hit = False
    for line_no, line in self.tail.read_new_lines(path):
        for match in _scan_line(...):
            if self.dedupe.should_notify(...):
                self._handle_match(match)
                any_hit = True
    if any_hit:
        self.state.save()        # ⭐ 只有命中才落盘
```

**只有真命中 secret 时才 `state.save()`**。如果一批新行扫完都没命中，**state 不立刻落盘**。

为什么？jsonl 是高频写入的（Claude Code 一个 session 每秒可能新增几十行）。如果每扫一个
文件都落盘，磁盘 I/O 会成为瓶颈。落盘**只在两个时机**：

1. **命中 secret 时**（opportunistic）—— 保证发出通知 + 状态可恢复
2. **正常 shutdown 时**（SIGTERM）—— 保证 daemon 关停时 state 完整

代价：`kill -9` 之后会重扫从上一次 opportunistic save 到 kill 的 bytes。一般也就几 MB，
detector 跑一遍几十 ms。可接受。

如果未来需要更强保证（比如某个特定场景 SIGKILL 频率高），可以加一个**周期性 flush**（比如
每 60s 调一次 `state.save()`）。当前 v0.6 没加，理由：launchd `KeepAlive=true` 下，daemon
crash 直接重启，整套 lifecycle 围绕"我们一般是正常 shutdown"设计。

---

## 排查指引

### 看 daemon 跟踪了哪些文件 + 扫到哪了

```bash
cat ~/.aifd/watch-state.json | jq '.files | to_entries[] | {path: .key, offset: .value.offset, size: .value.size}'
```

正常情况下每个 path 的 `offset` 应该接近文件当前 size（差距 = 上次落盘后新增的字节）。

### state file 损坏怎么办

```bash
# 看 daemon log，如果 state file 不认识会有 warning
aifd vault watch tail | grep -i "corrupt\|reset"

# 最坏情况：删 state file，daemon 会全量重扫
aifd vault watch stop
rm ~/.aifd/watch-state.json
aifd vault watch start
```

全量重扫的代价：800MB jsonl 的情况下大概 3 秒（v0.4 scan 实测）。`_DEFAULT_MIN_CONFIDENCE
= 7`，跳过熵层只跑 regex 层。

### 怀疑 offset 推进有 bug

```bash
# 前台跑 daemon + DEBUG log
aifd vault watch stop
aifd vault watch start --foreground -vv

# 在 log 里搜 TailReader 决策
# 会看到 "File ... shrank" / "Cannot read" 等行
```

### 怀疑漏扫

```bash
# 强制全量重扫（删 offset 但保留 catches 统计 —— 也可以保守一点直接删整个 state file）
aifd vault watch stop
python3 -c "
import json
from pathlib import Path
p = Path.home() / '.aifd' / 'watch-state.json'
s = json.loads(p.read_text())
s['files'] = {}        # 清空 offset 表
p.write_text(json.dumps(s, indent=2))
"
aifd vault watch start
```

或者直接交叉验证 —— `aifd vault scan` 一次（事后全量扫），对比 `aifd vault watch status`
的 `total_catches`。

---

## 相关代码

| 文件 | 作用 |
|---|---|
| `aifd/vault/watch_state.py:WatchState` | 数据类 + load / save / record_catch / catches_in_window |
| `aifd/vault/watch_state.py:catches_in_window` | 给 `aifd ai today` 用的公共 helper（不依赖 watchdog）|
| `aifd/vault/watch.py:TailReader.read_new_lines` | offset-based 增量读 + rotation 检测 + partial trailing line |
| `aifd/vault/watch.py:Daemon.run` | 启动序列（load → schedule → worker → initial sweep）|
| `aifd/vault/watch.py:Daemon._shutdown` | 关停序列（observer.stop → server.stop → state.save）|
| `aifd/vault/watch.py:Daemon._scan_one` | opportunistic save 逻辑 |
| `aifd/vault/watch.py:Daemon._sweep_loop` | 5 分钟周期 sweep（watchdog drop 的 fallback）|
| `aifd/vault/watch.py:DedupeCache` | 5 分钟 LRU + TTL，兜底重复通知 |
| `tests/test_vault_watch.py` | state save/load 原子性、版本迁移、TailReader 各种 case 的测试 |

---

## 相关文档

- [vault-watch.md](./vault-watch.md) — 命令参考 + 架构图 + 故障排查
- [secret-scan.md](./secret-scan.md) — detector 原理 + watch mode security 威胁模型
- [ai-retro.md](./ai-retro.md) — `aifd ai today / weekly / monthly` 的 JSON schema（含 E10 `watch_catches`）
