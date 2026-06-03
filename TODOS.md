# TODOS

## v0.2

### Claude Desktop session provider
**What**：新增 `aifd/providers/claude_desktop.py`，读 `~/Library/Application Support/Claude/claude-code-sessions/{uuid}/{uuid}/local_*.json`。
**Why**：Claude Desktop（macOS GUI）有独立 session 体系，每个 session JSON 含 `title` / `titleSource` 字段（AI 自动总结），目前未覆盖。
**Pros**：补齐 macOS GUI 用户场景；title 字段稳定可读，零解析成本。
**Cons**：用户基数小（一台机器 ~4 个 session vs CLI ~25 个 project），ROI 中等；要新增一个 provider 模块和测试 fixture。
**Context**：JSON 字段 `sessionId` / `cliSessionId`（链接到 CLI 的 jsonl）/ `cwd` / `originCwd` / `title` / `titleSource` / `lastFocusedAt` / `model` / `isArchived`。和 ClaudeProvider 互补——后者读 jsonl，前者读 GUI 元数据；可能要思考是合并还是并列。
**Depends on / blocked by**：v0.1 发布。

### Cursor provider 支持
**What**：实现 `aifd/providers/cursor.py`，按当前 cwd 列出 Cursor composer session。
**Why**：补齐三大 AI 工具聚合的承诺；中文开发圈 Cursor 用户基数大。
**Pros**：完成 v0.1 隐含的「三家合一」价值主张；大幅扩展用户基数。
**Cons**：实现需要 workspace hash 反查 + globalStorage SQLite (`cursorDiskKV` 表) 查询，约 2 个工作日；Cursor 路径在 Linux/Windows 不同，CI 矩阵复杂化。
**Context**：实测 `cursorDiskKV` 约 4 万条 KV，key 形态 `composerData:{id}` / `bubbleId:{cid}:{bid}` / `agentKv:blob:{hash}`。`workspaceStorage/{hash}/workspace.json` 的 `folder` 字段是 `file:///path`。composerData 本身**不直接含 cwd**，需要从 workspace storage 找到 composerId 列表，再到 globalStorage 查 composerData 时间戳。具体 workspace ↔ composer 映射关系还需进一步实测确定。
**Depends on / blocked by**：v0.1 发布。

### `aifd ai session show <id>`
**What**：输出指定 session 的元信息 + 首尾消息 preview（Markdown 渲染）。
**Why**：list 看到 session 后，自然下一个需求是「这个 session 聊的是什么」。
**Pros**：自然延伸；不需要新依赖（rich.Markdown 已在）。
**Cons**：需要在 Provider 协议加 `get_session(id) -> SessionDetail`，影响 Protocol 接口；输出格式（terminal vs piping）需要新设计。
**Context**：session_id 在 Claude 是 jsonl 文件 stem (UUID)；Codex 是 rollout 文件名中的 UUID 段。Cursor 是 composerId。
**Depends on / blocked by**：v0.1 发布。

## v0.3

### session list 加 `--skill X` filter
**What**：在 `aifd ai session list` 上加 `--skill <name>` flag，只列以指定 skill 起手的 session。
**Why**：v0.2 出来后用户看到 skill stats，自然下一个问题是「以 plan-ceo-review 起手的所有 session 是哪些」。
**Pros**：自然下文；复用 v0.2 skill detection 逻辑，实现成本低（~1h）；让 skill stats 和 session list 形成闭环。
**Cons**：需要 v0.2 完成；要在 Session dataclass 加 `skill_invoked` 字段（不破坏 v0.1）。
**Context**：v0.2 `list_skill_invocations` 返回的 `SkillInvocation.cwd + session_id` 已能反查 session；只需要在 session list 阶段加 join。
**Depends on / blocked by**：v0.2 (skill list) 发布。

### skill timeline / 每月趋势
**What**：sparkline / ASCII bar chart 展示「每个 skill 近 N 月使用频次」。
**Why**：让用户看到 skill 是「正在用」还是「曾经用」的演变轨迹。
**Pros**：数据现成（jsonl timestamp + Codex created_at_ms 都有）；视觉冲击力强。
**Cons**：rendering 复杂度上升；要决定时间粒度（月 / 周 / 日）。
**Context**：可以用 unicode `▁▂▃▄▅▆▇█` 八阶 sparkline，单字符宽度。
**Depends on / blocked by**：v0.2 (skill list) 发布。

### `aifd ai stats` 综合仪表盘
**What**：unified `aifd ai stats` 命令，整合 skill stats + session 总览 + provider 分布 + timeline。
**Why**：v0.2 加完 skill list 后，用户自然会问"我整体 AI 使用情况怎样"，需要 dashboard 视角。
**Pros**：从「session 浏览器」升级到「AI 使用画像」工具；强化 aifd 价值主张。
**Cons**：scope 较大（~2 天 / CC ~50min）；需要谨慎不变成 over-engineered。
**Context**：CEO plan 0C-bis 里 cathedral approach 被推后，现在记下作为 v0.3 重头戏。
**Depends on / blocked by**：v0.2 (skill list + skill timeline) 发布。

### `--recursive` / `-r` 子目录扫描
**What**：给 `list` 加 `-r` flag，扫当前 cwd 及所有子目录。
**Why**：monorepo / 多子项目仓库下，在仓库根能一次看到所有子项目的 session。
**Pros**：现代 CLI 工具（rg、fd 等）的预期行为；用户高频需求。
**Cons**：Provider 协议加 `recursive: bool=False` 参数（破坏现有签名，需在 v0.2 之前评估好）；前缀匹配语义可能让用户惊讶（如 `/foo/bar/baz` 是否算 `/foo/bar` 下）。
**Context**：内部实现就是 `Path(session.cwd).is_relative_to(query_cwd)`，单行。难点在协议改动与默认行为不变（D 决策定的默认精确匹配）。
**Depends on / blocked by**：无硬依赖；建议与 Cursor provider 一同评估 Protocol 改动。

### 并行扫多 provider
**What**：用 `concurrent.futures.ThreadPoolExecutor` 并行调三家 `list_sessions`。
**Why**：Cursor SQLite 查询会让总 list 时延接近 sum(三家)；并行后总时延 ≈ max(三家)。
**Pros**：Cursor 加入后体验不退化。
**Cons**：增加线程复杂度；多 provider 错误聚合和 logging 排序变难调试。
**Context**：MVP 串行 100ms 内，问题不大；加 Cursor 后可能 300-500ms，触发用户感知卡。
**Depends on / blocked by**：Cursor provider 加入后实测确认 wall-clock 时延。
