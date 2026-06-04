# AskUserQuestion 抓取机制

`aifd ai question list` 是如何从 Claude Code 的 jsonl 事件流里提取
「AI 问过我哪些问题、我都选了什么」的。本文回答 v0.3 实施时遇到的
真问题：为什么只支持 Claude、问题与答案怎么配对、被中断的问题怎么算、
多个 question 在同一次调用里怎么拆。

## 范围

只覆盖 Claude Code。Codex 的对话事件 (`agent_message`) 是自由文本，没有
结构化的 "向用户提问" 事件——v0.3 走精度路线：宁可少而准，不要多而噪。
覆盖率扩展（Codex agent_message 启发式、brainstorm 类纯文本句末 `?`）
列在 `TODOS.md` 里等用户信号。

## Claude jsonl 里 AUQ 长什么样

Claude Code 把 `AskUserQuestion` 工具调用记录为 **assistant 类型事件**
里的 `tool_use` 块。形态：

```json
{
  "type": "assistant",
  "cwd": "/Users/quincy/proj",
  "timestamp": "2026-06-03T11:00:00.000Z",
  "sessionId": "...",
  "message": {
    "content": [
      {
        "type": "tool_use",
        "id": "toolu_011WtyXSuSDERNZ1T9rgeH59",
        "name": "AskUserQuestion",
        "input": {
          "questions": [
            {
              "question": "提问的风格倾向哪一种？",
              "options": [
                { "label": "A) 苏格拉底式追问 (推荐)" },
                { "label": "B) 批判挑战" }
              ]
            }
          ]
        }
      }
    ]
  }
}
```

关键观察：
- **强结构、零 heuristic**——`questions[].question` 和 `options[].label`
  都是命名字段，不需要 NLP。
- **一次调用可有 1-4 个 question**。aifd 按 question 拆，每个生成
  独立一行 `QuestionAnswer`，因为决策足迹的语义是"我被问了 X，我选了 Y"，
  不是"我被一次问了一坨"。
- **`(recommended)` 后缀** 在 option label 末尾标推荐项。aifd 解析
  英文 `recommended` + 中日韩常见同义词 (`推荐` `推奨` `권장` 等)。
  细节见 `aifd/providers/_utils.py` 的 `_RECOMMENDED_WORDS`。

### MCP 宿主变体

某些 MCP 宿主用 `mcp__<host>__AskUserQuestion` 作为工具名。aifd 用
正则 `^(AskUserQuestion|mcp__.*__AskUserQuestion)$` 匹配。在 100 个
样本 jsonl 中 263 次 AUQ 调用，100% 匹配。

## 答案怎么配对

用户的回答是后续一个 **user 类型事件**里的 `tool_result` 块，
通过 `tool_use_id` 跟先前的 `tool_use` 关联：

```json
{
  "type": "user",
  "message": {
    "content": [
      {
        "type": "tool_result",
        "tool_use_id": "toolu_011WtyXSuSDERNZ1T9rgeH59",
        "content": "Your questions have been answered: \"Q1\"=\"A1\", \"Q2\"=\"B2\". You can now continue ..."
      }
    ]
  }
}
```

注意 `content` 文本的形态：每个被问的 question 都列在双引号里，
等号后跟着用户选的 label，**逗号分隔多个 Q/A 对**。aifd 用
`_AUQ_QA_PAIR_RE = re.compile(r'"([^"]+)"="([^"]+)"')` 抓所有对，
然后按 question 文本（经过 `normalize_title` 折叠空白后）查找对应 chosen。

为什么要按 question 文本查而不是按顺序？因为 schema 没保证 answer 文本
里的顺序跟 `input.questions[]` 的顺序一致，按 question 文本是安全的。

### multiSelect 答案

multiSelect 题的回答是逗号连接，例如 `"提问的风格"="结构性盲点追问, 批判挑战"`。
aifd 保留字面文本不拆分——这跟 footer 的 `recommended hit rate`
计算逻辑结合：算 match 时按 `,` 拆开看是否含 recommended，
但显示时不拆。

### "Other" 自定义答案

用户走"Other"路径手填内容时，answer 文本里会出现 `Other: <user text>` 段落。
aifd 用 `_AUQ_OTHER_NOTES_RE` 抓出来，存到 `QuestionAnswer.notes`，
Table 渲染时显示为 `Your Choice (Other: <notes>)`。

## 孤儿 question（无答案）

实测 ~4.2% 的 AUQ 调用没有匹配的 `tool_result`（用户主动中断 / session
被压缩）。aifd **依然 emit 这些行**，`chosen_option = None`，
Table 显示 `—`。这不是 bug，是有用的 retro 信号：
"我被问了什么但没回答。"

如果完全 silent 跳过，用户回头复盘时会以为这个问题没被问过。

## 空 questions 数组

理论上 schema 允许 `questions: []`（实际看到过的 host MCP bug）。aifd 的
处理：**silent skip + `--verbose` 模式记 INFO**。Table 上不出现噪点，
但 debug 时能看到。这是 D5 决策。

## cwd 范围过滤

两阶段配对，复用 `list_sessions` 的策略：

1. **方向阶段**（Phase 1）：用 cwd 的目录名编码（`/` → `-`）做粗筛。
2. **权威阶段**（Phase 2）：读 jsonl 内的 `cwd` 字段作权威匹配。
   编码是有损的（路径含 `-` 会跟嵌套路径冲撞），所以最终判定永远
   走 jsonl 内的字段。

## 数据流总图

```
                  user 跑 `aifd ai question list`
                                │
                                ▼
            run_provider_query (cli/_runner.py)
                                │
                                ▼
        ┌────────────────────────────────────┐
        │ ClaudeProvider.list_question_answers│
        │                                    │
        │  walk jsonl files                  │
        │    │                               │
        │    ▼                               │
        │  _collect_assistant_asks(event)    │
        │    → asks[tool_use_id] = (qs, ts)  │
        │                                    │
        │  _collect_user_answers(event)      │
        │    → answers[tool_use_id]          │
        │       = ({normalized_q: chosen},   │
        │           notes)                   │
        │                                    │
        │  for tid, (qs, ts) in asks:        │
        │    chosen_map = answers.get(tid)   │
        │    for q in qs:                    │
        │      yield QuestionAnswer(...)     │
        └────────────────────────────────────┘
                                │
                                ▼
                  list[QuestionAnswer]
                                │
                                ▼
                  sort by ts desc + limit
                                │
                                ▼
              render_question_answers
                ├── Table + summary footer
                └── JSON (full record)
```

## 何时扩展到 Codex / brainstorm 纯文本

只有当用户报告"我在 brainstorm 里被问的问题也想看"或类似具体痛点时，
才考虑加：

- **Codex agent_message 启发式**：扫 `agent_message` 文本句末 `?`，
  问号前 < 200 字符，过滤代码注释/明显非问句。会产生 noise，需配
  `--noisy` opt-in 旗。
- **Claude brainstorm 纯文本**：同上策略。

实施时建议先加 `--noisy` 旗位、单独 provider 类 (`ClaudeNoisyProvider`)、
单独 dataclass 字段 (`source: "auq" | "heuristic"`)，**不要污染**
现有 AUQ 主流体验。
