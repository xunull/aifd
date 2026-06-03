# Skill 识别机制

`aifd ai skill list` 是如何在 Claude Code 和 Codex 里发现用户调用过的 skill（斜杠命令）的。

两家工具的 session 存储格式完全不同，所以走两条独立的代码路径。最终都产出
统一形态的 `SkillInvocation` 记录，聚合器再把它们汇总为 `SkillStats`。

```
                   user 跑 `aifd ai skill list`
                                │
                                ▼
                ┌───────────────┴───────────────┐
                │                               │
         ClaudeProvider                   CodexProvider
        .list_skill_invocations          .list_skill_invocations
                │                               │
       ┌────────┴────────┐             ┌────────┴────────┐
       │ 扫 jsonl 事件流 │             │ SQLite 主路径   │
       │                 │             │ jsonl 兜底      │
       └────────┬────────┘             └────────┬────────┘
                │                               │
                └───────────────┬───────────────┘
                                ▼
                       list[SkillInvocation]
                                │
                                ▼
                   aggregate_skill_stats()
                                │
                                ▼
                       list[SkillStats]
```

## Claude Code

### 数据存储位置

```
~/.claude/projects/{编码后的 cwd}/{session-uuid}.jsonl
```

每个 `.jsonl` 是一次 Claude Code session，按事件流写入，一行一个 JSON 对象。

### Claude 怎么记录斜杠命令

用户键入 `/skill-name` 时，Claude 在 user message 的 content 文本里嵌入一个
类 XML 标签：

```json
{
  "type": "user",
  "cwd": "/Users/quincy/project",
  "timestamp": "2026-06-02T10:30:00.000Z",
  "message": {
    "content": "<command-name>/gstack-office-hours</command-name>\n<command-message>...</command-message>\n..."
  }
}
```

标签作为纯文本嵌在 `message.content` 里。Claude 可能在标签前后塞别的内容
（比如命令参数）。**一条 user message 理论上可能含多个 `<command-name>` 标签**，
但实践中极少见。

### 提取算法

代码在 `aifd/providers/claude.py:_extract_skills_from_file`。

对每个候选的 `.jsonl`：

1. 逐行迭代，对每行做 `json.loads`。
2. 过滤 `event["type"] == "user"`。这一步至关重要——它跳过 assistant 回复、
   系统提示、hook 输出等可能含有 `<command-name>` 字符串但**不是**真实
   用户调用的内容（比如文档引用、代码注释里的字面值）。
3. 从 `message.content` 拿文本。content 可能是字符串，也可能是结构化 block
   列表，`_extract_user_text` helper 两种都能处理。
4. 跑 `CLAUDE_COMMAND_RE.finditer(text)` 拿到该文本里所有 marker。
5. 对每个 match 归一化 skill 名，emit 一个 `SkillInvocation`。

regex 定义在 `aifd/providers/_utils.py`：

```python
CLAUDE_COMMAND_RE = re.compile(r"<command-name>([^<]+)</command-name>")
```

简单、无意外。`[^<]+` 非贪婪，对重叠或格式异常的标签都鲁棒。

### scope 过滤

带 `--cwd` 时，provider 走跟 session list 一样的两阶段策略：

1. **阶段 1** —— 用 Claude 的"路径转目录名"编码（`/` → `-`）快速过滤候选目录。
2. **阶段 2** —— 读每个 jsonl 内部权威的 `cwd` 字段（从第 3 行左右开始的每个
   事件都有），只对 cwd 匹配的文件 emit 调用记录。

阶段 2 是必须的——阶段 1 的编码是 lossy 的，含连字符的路径（比如
`/Users/foo/some-project`）跟 `/Users/foo/some/project` 编码后撞名，靠阶段 2
读取 jsonl 内真实 cwd 兜底校验。

### 为什么不会把文档字符串当成真调用

任何 assistant 输出粘贴进来的内容——包括复制的 skill 源文档里字面写着的
`<command-name>`——都属于 `type == "assistant"` 事件，不属于 user。
**type 过滤就是全部防线**。

本项目自己的 session 实测：原始 `grep '<command-name>'` 全文扫到 159 个命中，
provider 提取出 114 个。这 45 个差异正好是我们要过滤掉的噪声（assistant 回声
的 skill 文档、测试 fixture 字面字符串、代码里引用的 regex 字面值）。

## Codex

### 数据存储位置

```
~/.codex/state_5.sqlite              # 主路径
~/.codex/sessions/YYYY/MM/DD/        # 事件流（fallback 数据源）
~/.codex/archived_sessions/          # 事件流（fallback 数据源）
```

SQLite 数据库是权威的元数据存储。`sessions/` 和 `archived_sessions/` 下的
`rollout-*.jsonl` 含完整事件流，但 Codex 自己每次写入时都会在 SQLite 建索引。

### Codex 怎么记录斜杠命令

Codex 把用户的第一条消息原样存进 `threads.first_user_message` 字段。用户调用
skill 时，该字段的开头是个带 `$` 前缀的 Markdown 链接：

```
[$office-hours](/path/to/skill.md) 我的实际问题
```

skill 名字就在 `[$...]` 里——无前导斜杠、无 `gstack-` 前缀（因为 Codex 自己的
skill UI 不会加 namespace 前缀）。

本机实测：**113 个 thread 里 64 个**（57%）以 `[$` 开头，证明 skill 调用是
Codex 里多数 thread 的起手方式。

### 提取——SQLite 主路径

代码在 `aifd/providers/codex.py:_query_skill_sqlite`。

```sql
SELECT id, rollout_path, cwd, first_user_message, created_at_ms
FROM threads
WHERE first_user_message LIKE '[$%'
```

`LIKE '[$%'` 在 SQL 层就完成了重活——不以这个 marker 开头的行根本不进 Python，
即便机器上有上千个 thread，查询仍是亚毫秒级。

带 `--cwd` 时 SQL 加一段 `AND cwd = ?`。`(archived, cwd, created_at_ms DESC, id DESC)`
复合索引让它变成 index-only scan。

返回的每行用 regex 二次确认 marker 形态、抽出 skill 名：

```python
CODEX_SKILL_RE = re.compile(r"^\[\$([^\]]+)\]")
```

行首锚 `^` 关键——强制 marker 必须在最开头，所以一条 user message 如果只是
正文中提到 `[$something]` 字样，会被正确忽略。

### 提取——jsonl 兜底路径

代码在 `aifd/providers/codex.py:_jsonl_skill_fallback`。

只在 `state_5.sqlite` 不存在（老版 Codex）或 SQL 查询失败时触发。算法：

1. 递归遍历 `sessions/` 和 `archived_sessions/`。
2. 对每个 `rollout-*.jsonl`：
   - 第 1 行永远是 `session_meta` 事件，带 cwd 和 id。
   - 扫后续行找首个 `event_msg.payload.user_message`。
3. 同一套 regex 应用到该 user message。
4. 用 meta 行的 cwd 做 scope 匹配。

**短路语义**：SQLite 路径如果返回了任何行，就**绝对不能**再走 jsonl 扫描——
那会双倍计数。`list_skill_invocations` 入口强制这点：

```python
if db_path is not None:
    yielded_any = False
    try:
        for inv in self._query_skill_sqlite(db_path, scope):
            yielded_any = True
            yield inv
        return
    except sqlite3.Error:
        if yielded_any:
            return
yield from self._jsonl_skill_fallback(scope)
```

`tests/test_codex_skill.py` 里的 `test_sqlite_short_circuits_jsonl_for_skills`
测试锁死这个行为。

## 跨工具归一化

### 问题

两家 provider 看到的同一个 skill 名字不同：

| 工具 | 用户键入的 | 我们捕获的原始字符串 |
|---|---|---|
| Claude | `/gstack-office-hours` | `/gstack-office-hours` |
| Codex | `[$office-hours](...)` | `office-hours` |

如果直接用原始名，跨工具 `office-hours total = claude + codex` 永远算错——
它们会变成两行独立统计。

### 归一化规则

`aifd/providers/_utils.py` 的 `normalize_skill_name`：

1. 剥前导 `/`。
2. 剥前导 `gstack-`（如果有）。

结果：两种形态都归并到 `office-hours`，跨工具聚合就对了。

### 显示上的取舍

剥 `gstack-` 会丢用户在意的信息。用户看到表里写 `office-hours`，认不出这就是
自己键入的 `/gstack-office-hours` 命令。

解法：`SkillInvocation` 上独立跟踪一个 `is_gstack` 布尔字段。聚合器对一个
skill 的所有调用做 OR 合并（任一来源是 gstack 就把整个 stat 标记为 gstack）。
渲染时只在 table 显示中回填前缀：

```python
display = f"gstack-{s.skill_name}" if s.is_gstack else s.skill_name
```

JSON 输出保留归一化的 `skill_name` 字段（让下游程序确定性 filter），同时新增
`"is_gstack": bool` 字段给关心 namespace 的程序用。

检测靠 `is_gstack_name` helper：

```python
def is_gstack_name(raw: str) -> bool:
    name = raw.strip()
    if name.startswith("/"):
        name = name[1:]
    return name.startswith("gstack-")
```

## 失败模式与防御

| 失败场景 | 处理方式 | 对应测试 |
|---|---|---|
| Claude jsonl 没有 `<command-name>` marker | 静默跳过（不算错误）| `test_session_without_skills_silent_skip` |
| Claude jsonl 单行 JSON 损坏 | 跳过该行，继续读后续 | 沿用 session list 路径同一套 |
| Codex SQLite 查询中途出错 | warning 后 fall through 到 jsonl 兜底 | `_query_skill_sqlite` 的 try/except |
| Codex thread `first_user_message` 不匹配 `[$...]` | 静默跳过 | `test_sqlite_ignores_non_skill_threads` |
| 未来第三方 provider 没实现 `list_skill_invocations` | 继承 Protocol 默认实现，返回 `()` | `test_inherited_default_returns_empty` |
| SQLite 和 jsonl 两路径都产数据 | SQLite 短路 jsonl | `test_sqlite_short_circuits_jsonl_for_skills` |

错误处理哲学跟 v0.1 session list 一致：**单个坏文件或坏行绝不能让整体 list 崩**。
warning 写到 stderr，默认 silent，`-v` 出 INFO，`-vv` 出 DEBUG。

## 安装清单（v0.2.1 `aifd ai claude/codex skill list`）

跟「调用历史」无关，这是「文件系统里装了哪些 skill 可用」的清单。两条独立的
代码路径（`list_installed_skills`），不复用上面 `list_skill_invocations` 的
任何逻辑。

### Claude 的 skill 来源

两个 root 都要扫：

| Root | 内容 | source 字段 |
|---|---|---|
| `~/.claude/skills/{name}/SKILL.md` | 用户主动 `claude skills install` 的 | `user` |
| `~/.claude/plugins/cache/{marketplace}/{plugin}/{version}/skills/{name}/SKILL.md` | 通过 plugin 间接装的 | `plugin` |

`ClaudeProvider._scan_user_skills_root` 直接 `iterdir` 主目录。
`ClaudeProvider._scan_plugin_skills` 用 `rglob('SKILL.md')` + 路径含
`/skills/` 过滤，对未来 Anthropic 改 plugin 布局向后兼容。

plugin 名字从路径 `parts` 反推：`SKILL.md` 之前的 `/skills/` 段往上数两层
就是 plugin 名（见 `_claude_plugin_name_from_path`）。

### Codex 的 skill 来源

主目录直接扫，但要识别两个特殊条目：

| 路径 | 处理 |
|---|---|
| `~/.codex/skills/{name}/SKILL.md` | 列出，`source=user` |
| `~/.codex/skills/.system/{name}/SKILL.md` | 列出，`source=system`（Codex 自带）|
| `~/.codex/skills/codex-primary-runtime/` | 无 SKILL.md，silent skip（runtime sentinel）|

`.system/` 是子目录，遇到名字 `.system` 时换成 `_scan_system_skills` 走进去。
其他没 SKILL.md 的目录通过 `_read_skill` 返 None 自然跳过。

### Frontmatter 解析

SKILL.md 用 YAML frontmatter（`---` ... `---`）。我们**手写** parser，
只取三个标量字段（`name` / `description` / `version`），不引 PyYAML。

`parse_skill_frontmatter` 在 `_utils.py`：

- 第一行必须是 `---`，否则返回 `{}`
- 找到第二个 `---` 为止
- 单行 `key: value` 取右值（去掉引号）
- 多行 `key: |` block 把缩进段全取来 join 成一行
- 列表 / 嵌套 map（如 `allowed-tools:`）忽略 — aifd 不展示

为什么不引 PyYAML：v0.1 设计文档明确"刻意不依赖"。手写 ~70 行覆盖
我们关心的所有字段形态，加 8 个单元测试锁住。

### 同名 skill 多源不 dedup

按 D6 决策，同名 skill 在 user 和 plugin 两源各出现一次时**两行都列**，靠
`Source` 列区分。理由：dedup 会隐藏"装了两个同名 skill"的信号，违反信息
忠实。Table 按 `(source, name)` 排序，相同 source 自然相邻。

### 失败模式

| 失败 | 处理 |
|---|---|
| 主目录不存在 | silent skip 整个 source |
| plugin cache 不存在 | silent skip plugin 部分 |
| 目录无 SKILL.md | silent skip 该目录 |
| SKILL.md 不可读 | silent skip + debug log |
| frontmatter 缺 `name` | 用目录名兜底 |
| frontmatter 缺 `description` | 显示 `—` |
| frontmatter 含 list/map 字段 | parser 跳过该字段，不爆 |
| symlink 指向已删 target | `is_dir()` OSError → silent skip |
| 第三方 provider 不实现 `list_installed_skills` | Protocol 默认返 `()` |

跟 v0.2 一致的哲学：**单个坏文件绝不能让整体 list 崩**。

## 怎么加一个新的 provider

未来某天哪个 provider 也有了 skill 概念（比如 v0.3 的 Cursor），在该 provider
类上实现 `list_skill_invocations(scope: Path | None) -> Iterable[SkillInvocation]`
即可。要做三件事：

1. **检测** —— 找到该工具记录斜杠命令 marker 的位置。可能在结构化字段里
   （Codex 那种），也可能嵌在文本里（Claude 那种）。
2. **归一化** —— 把捕获到的原始字符串过一遍 `normalize_skill_name`，同时把
   同样的原始字符串过一遍 `is_gstack_name` 得出 `is_gstack` 标记。
3. **scope 过滤** —— 兑现 `scope: Path | None` 参数（None 全局，Path 限当前 cwd）。

完事。aggregator、render、CLI 都只认 `SkillInvocation` 形态——其他模块完全
不需要知道是哪家 provider 贡献的数据。

## 模块速查

| 模块 | 职责 |
|---|---|
| `aifd/providers/_utils.py` | 共享 regex、归一化、gstack 检测 |
| `aifd/providers/claude.py` | Claude jsonl 扫描 + `<command-name>` 提取 |
| `aifd/providers/codex.py` | Codex SQLite + jsonl 兜底提取 |
| `aifd/providers/base.py` | Provider Protocol，含 `list_skill_invocations` 默认实现 |
| `aifd/models.py` | `SkillInvocation` 和 `SkillStats` dataclass |
| `aifd/aggregation.py` | 把调用记录聚合成 stats |
| `aifd/render.py` | Table 和 JSON 渲染，含 prefix 回填逻辑 |
| `aifd/cli/ai/skill.py` | `aifd ai skill list` 命令 |
