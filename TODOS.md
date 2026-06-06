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

### `aifd ai question list` 过滤 flag 套装 (C1, 推迟自 v0.3 CEO plan)
**What**：加 `--recommended-only` / `--against-rec` / `--unanswered` 三个过滤 flag。
**Why**：v0.3 baseline 出来后，自然下一个查询模式是「我哪些时候反对推荐选择？」（产品偏好显形）和「我哪些问题被中断没回答？」。
**Pros**：用户实际跑 `aifd ai question list` 几次后必然想要；实现极简（~30min/CC ~5min）；和 footer 的 hit rate 形成完整闭环。
**Cons**：v0.3 baseline 还没真实使用过——等用户报告"我想看反推荐"再加，避免过早抽象。
**Context**：CEO plan D4 时被推迟。当时判断："等用户信号"。CLI 形态确定后估计 1h CC 就能加。
**Depends on / blocked by**：v0.3 (`aifd ai question list`) 发布并被使用 1-2 周后评估。

### `aifd ai question list --with-options` 完整选项展示 (C2)
**What**：加 `--with-options` flag，Table 中显示问题的全部 options（默认只显 Q + your choice）。
**Why**：有时只看「我选了 A」不够——需要看 B/C/D 是什么才能理解当时的决策上下文。
**Pros**：完整复盘语境；多行单元格 rich Table 已支持。
**Cons**：默认 Table 会变得很宽；用户其实可以 `--json | jq '.options'` 绕过。
**Context**：CEO plan D4 时被推迟。`--json` 模式已含完整 options，所以这只是 Table mode 的便利性增强。
**Depends on / blocked by**：v0.3 发布后用户反馈"jq 不够便利"。

### `aifd ai question stats` 统计子命令 (C4)
**What**：独立 stats 视图：按 cwd 分布、按 ts 分布、top 高频问题模式、recommended hit rate by project / by month。
**Why**：v0.3 footer 是 hit rate 的轻量预览；stats 是完整版（"我在哪些项目里更倾向反推荐"、"哪些问题模式反复出现该 plan-tune"）。
**Pros**：天然下一个分析层；CEO plan 0C 描绘的 12 个月愿景里"AI 决策日志"系统的关键一环。
**Cons**：~2h human / ~25min CC，是独立 v0.3+ PR scope；要决定时间粒度（月/周）和 cwd 聚合方式。
**Context**：CEO plan D4 时被推迟。数据已经在 v0.3 emit 出来，schema 都对，只是新增分析层。
**Depends on / blocked by**：v0.3 发布。

### Codex question retro 支持（让 aifd ai question list 对 Codex 用户也有用）

**What**：让 `aifd ai question list` 在 Codex 数据上也能列出"AI 问过什么、我选了什么"。当前 `CodexProvider.list_question_answers()` 直接返回 `()`——纯 Codex 用户跑这个命令永远是空表。

**Why**：实证数据：扫 115 个 Codex jsonl，**0 个含结构化 AskUserQuestion 工具调用**。原因是 Codex CLI 没把"问用户"做成 first-class tool，AI 想问问题直接在 `agent_message` 里写自由文本，user 在 `user_message` 里写文本答。是 OpenAI SDK 层级的产品决策、不是数据缺失。所以 v0.3 选择"精度优先、Codex 返回空"——但**对 Codex 重度用户来说这功能就废了**，得有路径补上。

**几个潜在解法（按精度 / 维护成本排序）**：

1. **`(P3, L)` 启发式扫 `agent_message` 文本** — 拉 Codex jsonl 里所有 `agent_message`，扫含 `?` / `？` 句末的句子，再过滤代码注释 / 短句 / 已知非问句模板。问题：精度低（代码里 `// why isn't this null?` 也会被抓），需要 `--noisy` opt-in flag + `source: "heuristic"` 字段区分。

2. **`(P3, M)` LLM 离线抽** — 用 GPT-4o-mini / Claude Haiku 等便宜小模型，把 `agent_message` 段 + 紧跟的 `user_message` 一起喂进去，问"这段里 AI 问了用户什么？user 怎么答的？"返回结构化 JSON。精度高、需 API key + 跑批量、$ 成本。

3. **`(P3, M)` 看 Codex 上游有没有结构化提案** — 检查 OpenAI Codex CLI / Responses API 后续版本有没有引入"interactive_input" / "user_choice" 这类事件。如果 OpenAI 哪天补齐，aifd 端直接解析即可。值得季度性检查。

4. **`(P3, S)` 用 Codex 的 `[$skill]` marker 做半结构化锚点** — 已经发现 Codex 用 `[$skill-name]` 作 skill 调用 marker（v0.2 的 skill list 在用）。如果某些 skill (gstack 系) 在 Codex prompt 模板里加了显式的"D1 — ..." numbered question marker，可以靠这个 marker 抽。覆盖率不高（只 gstack 类 skill），但**精度 100%**。

**Pros**：让 Codex 用户也能跨工具用同一个 retro 命令；补齐 aifd "跨工具一致体验"的承诺。

**Cons**：以上 4 条都不是 boring solution——启发式 noisy、LLM 要 API key、等上游遥不可期、marker 路径覆盖率窄。属于 v0.4+ 真正想清楚再做的题。

**Effort**：人类 L (~2 天) → CC M (~30-60min)。LLM 解法额外要 $（每 1000 message ~$0.10 with mini 模型）。

**Priority**：P3。Claude 用户主线先扎实；等 Codex 用户报告"我跑 question list 是空我心碎" 再启动。

**Context**：v0.3 CEO plan D2=A 时选了精度优先，文档化在 [docs/question-extraction.md](./docs/question-extraction.md) "何时扩展" 章节。讨论详见 `~/.gstack/projects/aifd/ceo-plans/2026-06-03-question-extraction.md`。

**Depends on / blocked by**：建议先看 OpenAI Codex CLI 季度更新有没有引入结构化提问事件。如果没有，再选 1 / 4 启动（避开 LLM 解法的成本）。

### `aifd vault prices update` 自动同步 vendor 价格表

**What**：新增一个脚本（`scripts/update_prices.py`）或子命令（`aifd vault prices update`），定期从 vendor pricing page 拉真实价格，更新 `aifd/vault/prices.py`。最低限度自动化 Anthropic（已验证 WebFetch 能跑通 `platform.claude.com/docs/en/about-claude/pricing`），OpenAI 留 fallback（Cloudflare 拦 WebFetch）。

**Why**：现在 prices.py 的 OpenAI 部分是估算，Anthropic 部分是 2026-06-04 手动 verify 的——会过期。每次 vendor 调价都得人工跑一遍 WebFetch + diff + 改 prices.py + 重测——容易拖到不更新。自动化后 weekly cron 或 release 前 hook 跑一次就行。

**Pros**：价格表新鲜度提升；减少手动同步成本；用户报告"显示价过期"的频率降低；CI 加一步 prices verify 即可阻止过期 release。

**Cons**：vendor page 改版会让 scraper 坏；Cloudflare 不一定永远能绕过；要写 schema validation 避免 vendor 偷偷加新字段崩到我们；某些 cloud-tier-specific 价（Bedrock / Vertex）跟 first-party 不同，要决定 aifd 跟哪一条。

**实现路径**（按复杂度）：

1. **`(P2, S)` 简单 script + 手动跑**：`scripts/update_prices.py` 跑 WebFetch（已验证 Anthropic 可行）+ 输出 diff，人审完手动 commit。CI 在 release.yml 加一步 "verify prices 不超过 90 天"，过期就 fail release。30min CC。
2. **`(P2, M)` 子命令 `aifd vault prices update`**：跟 (1) 同样 logic 但 expose 成 CLI，方便用户本地跑 + 覆盖单个 model 价格。需要 `--dry-run` / `--apply` flag、diff 显示 / `--write-to PATH`。1h CC。
3. **`(P3, L)` GitHub Actions 周期任务**：weekly cron 调 update_prices.py、检测 diff、自动开 PR @ xunull review + merge。完整自动化但要小心 vendor page 偷偷改字段 schema 让脚本错乱。需 alerting on parse 失败。2h CC + ops setup。
4. **`(P3, M)` OpenAI 绕过 Cloudflare 路径调查**：试 `gh api`、SDK 源码、OpenAI cookbook GitHub mirror 等替代源。如果都 fail，转人工 PR。30min 调查 + variable 实施成本。

**Effort**：human M (~6h 完整) → CC S/M (~1.5h 路径 2)。

**Priority**：P2。Anthropic 价格估计能稳一段（最近一次降价 Opus 4.5+），但 OpenAI 永远在动且 unverified。Build 后用户首次报告 "价不对" 就启动。

**Context**：v0.4 实施时 prices.py 半自动 verify 已实证可行——Anthropic WebFetch 拉 `platform.claude.com` 成功获取了 11 个 model 的真实价格，但 OpenAI 同方法 403。当时手动 update 了 Anthropic 部分。完整设计讨论在 conversation 2026-06-04（commit `2026-06-04 update Anthropic prices to verified`）。

**Depends on / blocked by**：建议在 v0.4 公开发布并收 vendor pricing 调价反馈后启动。如果 v0.5 选 `vault export`，这条 prices update 可以同 release。

### `aifd vault export` 全量备份 (P2, 推迟自 v0.4 CEO plan)

**What**：单命令 `aifd vault export --output path.zip` 把所有 provider 的 history 打成一个 archive（含 `manifest.json` 列出每个 session 的 cwd / size / sha256，方便审计）。可选 `--encrypt --key /path/to/keyfile` (age / GPG)。

**Why**：解锁 3 个 use case：(a) 换机器 (b) 防 Claude/Codex 哪天 silently 清理或换格式 (c) 给未来 AI 学习当 dataset。是 vault 方向的关键中间件——sync 离不开 export。

**Pros**：补齐 "AI 数据归我" 故事；价值清晰；实现不复杂；为 P4 sync 铺底。

**Cons**：单点价值不够——只 export 不能 import 是半截。等用户主动报告"想备份"再做。

**Context**：v0.4 CEO plan D2 时被推迟。aifd 路径已经知道（claude root + codex root），P1 P3 出来后基础设施完备。

**Effort**：人类 M (~4h) → CC S (~45min)。

**Priority**：P2（v0.4 出来一周内有人报告"想备份"就启动）。

**Depends on / blocked by**：v0.4 (vault scan + cost) 出 + 有用户反馈"想备份"。

### `aifd vault sync` 多机同步 (P4, 推迟自 v0.4 CEO plan)

**What**：工作机 / 笔记本 / 服务器多台机器之间的 AI 历史合并到统一视图。3 种实现路径：(1) export-then-import 双向同步（最简）(2) git-based 推私有 repo (3) syncthing 风格 daemon（最完整）。

**Why**：用户 AI 历史不再被绑在单机。换机器、跨设备工作不丢历史。是 vault 方向的终态目标。

**Pros**：真正"AI 数据主权"完成态；解锁跨设备工作流；用户长期会越来越需要。

**Cons**：~2h+ CC scope；多机合并 / 冲突解决 / 加密 sync 设计复杂；需要 P2 export 先做；维护成本高。

**Context**：v0.4 CEO plan D2 时被推迟。建议 P2 出来后单独 plan。简单路径（export+import）优先于完整路径（daemon）。

**Effort**：人类 XL (~2 天) → CC L (~2h)（简单版）/ L+（完整版）。

**Priority**：P3（v0.6+ 候选）。

**Depends on / blocked by**：P2 vault export 完成 + 用户跨机使用规模到一定程度。

### `aifd ai session list` 加 `question_count` 列
**What**：在 session list 表格加一列显示该 session 里被问过几个 AUQ。
**Why**：跨命令 augment——让 session 浏览能"看到这个 session 决策密度"。
**Pros**：用 v0.3 的 `list_question_answers` 数据直接 count；数据现成。
**Cons**：要在 SessionRow 拼装时反查，性能开销；列宽变窄影响 title 显示。
**Context**：CEO plan D4 时被推迟。属于 v0.3+ "AI 决策日志" 系统的视觉增强。
**Depends on / blocked by**：v0.3 发布 + Cursor provider 也支持后再考虑（保持跨工具一致）。

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

### `aifd vault scan --exclude REGEX` 用户自定义 FP 排除
**What**：CLI flag 允许用户传入正则，匹配的 match 在 emit 之前被丢弃；可重复。
**Why**：内置 `_SUPPRESSORS` 框架已经处理 escape_prefix（80% email FP）。当用户在自己数据上发现新的 FP 类时，希望不改代码就能本地配置过滤。
**Pros**：用户对自己数据的 noise pattern 比我们更了解；降低再次提 issue / PR 的门槛。
**Cons**：滥用会过度抑制真信号；UX 上需要 `--show-suppressed` 配套调试 flag 才能验证排除是否如预期。
**Context**：`_SUPPRESSORS` 是内部 frozen tuple；外加一个 `(name="user_regex", reason="--exclude pattern", check=lambda m,l,s,e: pat.search(m))` 类型条目；CLI 处接收 `--exclude PATTERN`（多次可重复）转成 list[Pattern]。
**Depends on / blocked by**：无；可在 v0.5 单独发布。

### `aifd vault scan --show-suppressed` 调试 flag
**What**：CLI flag 在输出末尾追加一段「被 suppressor 丢弃的 match」表，含 suppressor name + redacted snippet + file:line。
**Why**：用户配置 `--exclude` 或调 detector 时需要看到「我以为 X 命中了，为什么没出现在表里」。当前能力是 `-vv` DEBUG log；但 log 散乱、按时间序，不利于审计。
**Pros**：让 suppression layer 不再是黑盒；calibration 工具。
**Cons**：要把 suppressed match 保留到最终输出阶段（额外内存）；HTML / JSON 也需要承载这个 section。
**Context**：scan.py 现在 suppressed match 直接 `continue` 丢弃；要改成 yield 出 `(SensitiveMatch, suppressor_name)` 元组，render 层负责选择是否显示。
**Depends on / blocked by**：建议与 `--exclude` 一起做（两者形成 calibration 闭环）。

## v0.7.x 后续 (eng review 输出)

### `aifd vault watch webhooks digest` 周期汇总 webhook
**What**：cron-like digest（daily / weekly），不是 per-event 触发，而是周期汇总。webhook config 加 `on: [digest]` + `schedule: daily|weekly|cron-expr` 字段。
**Why**：让"我不想被每条 finding 点亮但想要总结"类用户能用。降低 noise 又保持可观测。
**Pros**：低噪审；适合周末 batch 复查的 user。
**Cons**：需要 BackgroundScheduler 或 APScheduler；aifd 当前没 cron-like 机制；retention 默认要调。
**Context**：design doc `quincy-main-design-20260605-211630.md` 提了 daily/weekly digest 作为 Approach B' 的一部分但被 eng review D7 推后。装实现需要 scheduler 线程或定时唤醒 sweeper。
**Depends on / blocked by**：v0.7 events DB ship。

### `aifd vault watch events vacuum` retention policy
**What**：自动删除 N 天前的 resolved findings，防止 events DB 无限增长。先做 CLI 手动版本，再加 sweeper 自动。
**Why**：personal use 三年后 DB 可能恶胀。手动 `vacuum --before YYYY-MM-DD` 让 user 清理可控。
**Pros**：防止 DB 老化；CLI 体验清晰。
**Cons**：sweeper 加一个 job；retention 默认期限要调参；resolved → vacuum 之间 user 可能想回看历史。
**Context**：design doc 没提 retention。eng review 中发现这是 omission。建议 v0.7.1 加 CLI 手动 vacuum，v0.8 加 sweeper 自动。
**Depends on / blocked by**：v0.7 events DB ship。


## v0.8.x 后续 (eng review 输出)

### `aifd config` set/get/list 子命令
**What**：`aifd config set llm.api_key SK_...` / `aifd config get llm.model` / `aifd config list` —— central config CLI helper。
**Why**：v0.8.0 ship 的是 "首次 reflect 引导生成 yaml" + "手动编辑"。set/get/list 让首次引导无 editor 也能完成。
**Pros**：onboarding 丝滑；user 不用记 yaml schema；config 错误时 helpful error；多 provider 切换更方便（`aifd config set llm.model zhipu/glm-4-plus`）。
**Cons**：~150 LOC + 5 测试；v0.8.0 不必须。
**Context**：design `aifd ai reflect` 首次 run 时生成 `~/.aifd/config.yaml` 模板 + 引导 export AIFD_LLM_API_KEY，但不能命令式写入。v0.8.0 充足，v0.8.1 加这个。
**Depends on / blocked by**：v0.8.0 ship + central config 模块稳定。

### Reflect daily / monthly / quarterly cadence
**What**：v0.8.0 只 ship `--week` + custom range。加 `--day`、`--month`、`--quarter` flag。
**Why review 推迟**：weekly + custom 是最小完整集；其他 cadence 是 prompt 变体 + period 计算。
**Pros**：quarterly reflection 是独特价值（v0.5 ai today 不做 quarterly）；daily 是低 friction 每天看一次。
**Cons**：4 cadence × 2 lang = 8 prompt template variation 要调优；当下需求不明。
**Context**：design 中作为 Open Question 列出。v0.8.0 用 1 周后 user feedback 决定优先级。
**Depends on / blocked by**：v0.8.0 ship + 1 周使用 feedback。

### 国内 LLM provider 实测验证（LiteLLM compat smoke）
**What**：实测 `zhipu/glm-4-plus`、`dashscope/qwen-plus`、`ark/<endpoint_id>`、`moonshot/moonshot-v1-32k` 在 LiteLLM 下的 `response_format=json_object` + tool_call 行为，记录 quirks 进 docs/ai-reflect.md「Multi-vendor」段落。
**Why**：v0.8.0 ship 时已切 LiteLLM 但只在 DeepSeek 上 live-tested。国内 provider 的 OpenAI-compat 程度各家不同，response_format 在某些 provider 上可能 fallback 到 prompt-based JSON instruct。
**Pros**：写文档前先实测，避免 user 选了 provider 跑不通；catch LiteLLM 跟某家 provider 之间 spec drift 的早期信号。
**Cons**：每家 ~$0.001/test 但要 4-5 家 API key；调试 quirks 可能 1-2 小时。
**Context**：v0.8 LiteLLM 切换的留尾。每家 provider 都加 1 个 `live_api` 测试用 `AIFD_LIVE_MODEL` env 切换。
**Depends on / blocked by**：v0.8.0 ship + 用户提供国内 provider key 给 maintainer。

### Streaming reflection output
**What**：LiteLLM 原生支持 `stream=True`；让 `aifd ai reflect` 边接 chunk 边渲染 essay。
**Why review 推迟**：streaming 引入 partial JSON parsing 的复杂度（`response_format=json_object` + stream 行为各 provider 不一），UX 决策也未明（rich.live 显示？rolling text？）。
**Pros**：长 essay 在慢 provider 上感知更快；user 不用盯空屏 6 秒。
**Cons**：partial JSON 处理 + cancel handling + 错误 mid-stream 的 fallback 都要重做；prompt_version 中途 fail 怎么办。
**Context**：v0.8 LiteLLM 切换打开了这道门。user 反馈如果说"reflect 等太久"再做。
**Depends on / blocked by**：v0.8.0 ship + user reports slow render。

