# vault scan 检测原理

`aifd vault scan` 是如何在你的 AI 历史 jsonl 里找出 API key、token、PII 泄露的。本文回答 v0.4 实施时所有的设计决策：为什么 regex + entropy 两层、为什么默认 confidence 7、为什么 secret 永远不会出现在输出 / 日志 / 内存里超过 scan loop 生命周期、为什么实测 287K 高熵命中要被压制。

## 范围

只扫 jsonl 文件——provider 历史的标准格式。默认 root：
- `~/.claude/projects/`（递归，所有 `*.jsonl`）
- `~/.codex/sessions/`（递归）
- `~/.codex/archived_sessions/`（不递归）

可以 `--root` 加额外路径（文件或目录），`--no-default-roots` 只扫指定路径。

**不做**的事：
- 不解析 JSON 结构（直接行级 regex / entropy）—— 因为 jsonl 里 secret 可能在任何字段（用户问 AI 时 paste 的 `.env`、AI 生成的 code 示例、debug log fragment 等等），按 JSON path 走会漏掉一大半
- 不修改任何文件（read-only）
- 不发任何网络请求
- 不存完整 secret 值到结果数据类 / 日志 / 文件——只存 redacted snippet

## 总数据流

```
                    user 跑 aifd vault scan
                            │
                            ▼
              cli/vault/scan.py: list[Path] roots
                            │
                            ▼
                vault/scan.py: scan_paths(roots)
                            │
              对每个 root: rglob *.jsonl 找文件
                            │
                            ▼
                  scan_file(path) 逐文件
                            │
              逐行（line by line, 1-indexed）
                            │
                            ▼
                  _scan_line(path, line_no, line)
                            │
                  ┌─────────┴─────────┐
                  ▼                   ▼
       regex 层 (10 个 detector)    Shannon 熵层
       confidence 7-10              confidence 4-6
                  │                   │
                  │            过滤 hash patterns
                  │            (sha256/sha1/md5)
                  │                   │
                  └─────────┬─────────┘
                            ▼
                  dedupe per line (category, value)
                            │
                            ▼
                  yield SensitiveMatch(...)
                  (snippet_redacted only, never full)
                            │
                            ▼
              render.render_scan_matches
              过滤 by --min-confidence
                            │
                        ┌───┴───┐
                        ▼       ▼
                    Table     JSON
                  (colored)  (redacted)
```

## 两层检测

### 层 1：regex detector（confidence 7-10）

匹已知 vendor 给 secret 的格式。优先级最高、误判率最低。

`aifd/vault/scan.py:_DETECTORS` 当前 10 个：

| Category | Regex | Confidence | 命中什么 |
|---|---|---:|---|
| `anthropic_key` | `sk-ant-[A-Za-z0-9_\-]{20,}` | 10 | Claude API key |
| `openai_key` | `sk-(?:proj-)?[A-Za-z0-9_\-]{20,}` | 10 | OpenAI key (project / standard) |
| `github_pat` | `ghp_[A-Za-z0-9]{30,}` | 10 | GitHub classic PAT |
| `github_fine_grained_pat` | `github_pat_[A-Za-z0-9_]{40,}` | 10 | GitHub fine-grained PAT |
| `github_app_token` | `ghs_[A-Za-z0-9]{30,}` | 10 | GitHub App token |
| `aws_access_key` | `\bAKIA[0-9A-Z]{16}\b` | 9 | AWS access key ID |
| `slack_token` | `xox[baprs]-[A-Za-z0-9-]{10,}` | 9 | Slack bot / user / app token |
| `jwt` | `\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b` | 8 | 标准 JWT (3-segment base64url) |
| `bearer_token` | `(?i)bearer\s+([A-Za-z0-9_\-\.]{20,})` | 7 | HTTP Authorization header 形式 |
| `email` | `\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b` | 7 | 邮箱（PII）|

#### 为什么 confidence 不全是 10

- **`sk-ant-` / `sk-` / `ghp_` 等 vendor-specific 前缀**：这些前缀**就是为了让人 grep 找泄露**而设计的（Anthropic / OpenAI / GitHub 文档明说）。前缀 + 长度限制 → 假阳性接近 0
- **AWS `AKIA*` 16 字符**：标准格式，但稍弱（其他系统也用 AKIA 起头的 16 字符 ID）→ 9
- **JWT `eyJ.*.*`**：base64url + 3 段结构很特殊，但仍可能命中 base64-encoded 长 string 巧合 → 8
- **`bearer XXX`**：依赖前面的 `bearer` 关键词，但后面字符集很宽 → 7
- **email**：是 PII 但不是 credential，且大量 noise（`user@example.com` 示例）→ 7

confidence 决定**默认是否显示**——`--min-confidence 7` 是默认，9-10 你看到的全是高风险。

### 层 2：Shannon 熵检测（confidence 4-6）

兜底未知 token 格式（自有内网系统、临时 hex 串、未来 vendor 用别的前缀等）。

```python
_ENTROPY_RE = re.compile(r"[A-Za-z0-9+/=_\-]{40,200}")
_ENTROPY_THRESHOLD = 4.5  # Shannon bits per char
```

参数选择：

| 参数 | 值 | 为什么 |
|---|---:|---|
| `_ENTROPY_MIN_LENGTH` | 40 | < 40 字符的随机串普遍是 UUID 段 / commit hash / 短 nonce，noise 太多 |
| `_ENTROPY_MAX_LENGTH` | 200 | > 200 多半是 binary blob / base64 文件内容 / certificate 内嵌，不是 secret |
| `_ENTROPY_THRESHOLD` | 4.5 bits/char | 26 字符纯字母 = 4.7、64 字符 alphanum = 5.6；4.5 排除了 `aaaaaaaa` `123456789` 这种低熵 |
| 字符集 | `[A-Za-z0-9+/=_\-]` | 覆盖 base64 / base64url / hex / 大多数 token 字符；排除空格 / 标点（自然语言） |

Shannon 熵公式：

```python
def shannon_entropy(s: str) -> float:
    freq = {ch: s.count(ch) for ch in set(s)}
    n = len(s)
    return -sum((c/n) * math.log2(c/n) for c in freq.values())
```

每字符比特数。0 = 单字符重复，log₂(unique chars) max。

#### Confidence 评分按熵分档

```python
confidence = 4 if ent < 5.0 else (5 if ent < 5.5 else 6)
```

- **4 (4.5 ≤ 熵 < 5.0)**：可能是 hash / 长 ID / 普通 base64 文本
- **5 (5.0 ≤ 熵 < 5.5)**：更随机，可能是 token
- **6 (5.5+)**：高度随机，比较像 secret

熵越高越像 secret，但都低于 regex 层的 7，**默认不显示**。

#### 已知 hash 跳过

```python
_ENTROPY_SKIP_RE = re.compile(
    r"^(?:[0-9a-f]{32}|[0-9a-f]{40}|[0-9a-f]{64})$"
)
```

刚好 md5 (32) / sha1 (40) / sha256 (64) 的纯 hex 字符串直接跳——这些是 hash 不是 secret，aifd 历史里满天飞（commit hash、checksum 等）。

实证：你这台机器没 skip 这条会**多 ~50K 个 noise 命中**。

## SensitiveMatch 数据类

`aifd/models.py`：

```python
@dataclass(frozen=True)
class SensitiveMatch:
    file: Path                  # jsonl 路径
    line: int                   # 1-indexed 行号
    category: str               # detector id
    snippet_redacted: str       # 永不含完整值
    confidence: int             # 1-10
    full_length: int            # 完整 token 的字符数（帮判断真假）
```

**关键安全设计**：`snippet_redacted` 是**唯一**含 secret 子串的字段，且已被 redacted。完整 secret value 从 `_scan_line` 的局部变量 → 立即 `redact(full)` → 进 `SensitiveMatch.snippet_redacted` → emit 出去后 GC 回收。完整 secret value **不在任何持久化结构里**。

## redact 函数

```python
def redact(value: str) -> str:
    if len(value) <= 8:
        return "…" * len(value)
    head_n = min(4, len(value) // 4)
    tail_n = min(4, len(value) // 4)
    return f"{value[:head_n]}…REDACTED…{value[-tail_n:]}"
```

- 短串（≤ 8 字符）：全 ellipses，零信息泄露
- 长串：head 4 + tail 4 + `…REDACTED…` —— 足够让人**认出**是哪个 token（`sk-pr…REDACTED…7890`），但不足以**复用**

为什么要保留 head + tail？因为你看输出时常需要"哦这是上周那个 sk-proj-... 的 key 已经 rotate 了" vs "这是另一个还没 rotate 的"——纯 ellipses 让所有 finding 长一样，无法人眼区分。

`full_length` 字段补充信息：16 字符的 token 多半是 hash 不是 secret，64 字符的更像 token，120+ 多半是 JWT。

## Per-line dedupe

```python
def _scan_line(path, line_no, line):
    seen: set[tuple[str, str]] = set()
    for category, pattern, conf in _DETECTORS:
        for m in pattern.finditer(line):
            full = m.group(1) if m.lastindex else m.group(0)
            key = (category, full)
            if key in seen:
                continue
            seen.add(key)
            ...
```

同一行里同一个 (category, full_value) 命中只 emit 一次。常见场景：用户在对话里 paste 一行含 token，那一行结构里其他位置又出现同样 token（HTTP header + URL + 命令行回显）。dedupe 之后该 row 只一个 finding，不是 5 个噪点。

但 **跨行**不 dedupe——同一个 token 在 session 多次出现是有意义的（追踪泄露范围）。

## 大行截断

```python
if len(raw) > 16384:
    raw = raw[:16384]
```

某些 jsonl 一行能上 MB（用户 paste 了一整个 .env 文件 / 一份 SQL dump）。regex 引擎在超长串上接近 O(n²)，会卡。截 16KB 是 trade-off：保证扫不卡 + 大多数 secret 出现在前 16KB 里。

代价：极端 case 漏检（secret 在 16KB 之后）。实测 jsonl 单行 > 16KB 占比 < 0.3%，acceptable。

## CLI 默认 `--min-confidence 7`

这是 v0.4 最重要的 UX 决策之一。实测你机器：

| Confidence 级别 | 命中数 | 价值 |
|---:|---:|---|
| 10 | 344 | 真信号（vendor-prefix key），全部应 rotate |
| 9 | ~5 | 真信号（AWS / Slack） |
| 8 | 4 | 真信号（JWT），多数是 GitHub Actions token 例子 |
| 7 | 938 | PII / bearer，多数是文档 email 噪点 |
| 6 | ~5K | 高熵 (5.5+)，少量真 token |
| 5 | ~40K | 中熵，绝大多数 hash / UUID |
| 4 | ~240K | 低熵 (4.5-5.0)，纯噪点 |

如果默认 `--min-confidence 4`，user 一上来看到 290K 行，**真信号被淹没**。`--min-confidence 7` 默认下看到 ~1300 行，仍多但能 grep / pipe 处理。

需要全扫时 `aifd vault scan --min-confidence 4`。

## Footer 显示

```
1286 findings: 938 email · 331 openai_key · 7 github_pat · 4 jwt · 
3 anthropic_key · 3 aws_access_key · 289446 low-confidence suppressed
```

按 category 倒序，明确告诉 user "低 confidence 被压制了多少"——decision-grade 信息。

## 实证：检测准确度

跑一遍我机器，跟人工验证对比：

| Category | 检出数 | 真泄露 | 噪点 | precision |
|---|---:|---:|---:|---:|
| openai_key | 331 | ~10 | ~321 (test fixture / 示例 / docs) | ~3% |
| github_pat | 7 | 1 | 6 (test fixture) | ~14% |
| anthropic_key | 3 | 0 | 3 (docs / 示例) | 0% |
| aws_access_key | 3 | 0 | 3 (AWS docs 示例) | 0% |
| jwt | 4 | 1 | 3 (GitHub Actions 示例 JWT) | 25% |
| email | 938 | ~150 真 | ~788 (docs / package metadata / 示例) | ~16% |

整体 precision 看起来低，但**recall 接近 100%**：在 sample 验证里没漏过任何真 secret。这是 scan 工具应有 trade-off——**宁可多报让人 review，不漏报让你某天被 hack**。

误报来源：
- AI 写的代码 example 含 placeholder key (`sk-YOUR-KEY-HERE`)
- 文档里的示例 token
- aifd 自己 tests/test_vault_scan.py 写的 fixture key（被 Claude 读进 jsonl）
- package metadata 里的 author email

**实施侧不再降低 false positive**——降阈值会丢真信号。让 user 用 confidence 过滤 + 看 category 自行 prioritize。

## 准确性 caveats

| 局限 | 说明 |
|---|---|
| 仅扫 `*.jsonl` | sqlite (Codex `state_5.sqlite`) 不扫，需要先 dump 出来 |
| 不解析 JSON 结构 | 行级扫，可能漏 multi-line JSON 里的 secret（jsonl 一行一对象，影响极小）|
| > 16KB 行截断 | 极少数 case（< 0.3%）会漏后段 |
| 不识别加密 base64 | base64 加密块跟随机 token 熵指标接近，可能高 confidence 误报 |
| 不识别 vendor 新 key 格式 | 比如 OpenAI 哪天换 prefix，aifd regex 抓不到（熵层兜底，但 confidence 降到 4-6）|
| 不识别去 prefix 的 key 残段 | `proj-abc...xyz` 没 `sk-` 就走熵层 |
| 不识别加密文件 | `.gpg` / `.age` 加密的内容是高熵，会假阳性 |
| 不识别 image base64 | data URI inline 的图片是长高熵 base64，假阳性 |

## v0.5+ 演进点

| 候选 | 描述 |
|---|---|
| **`aifd vault redact --pattern X`** | 选择性把命中的 secret 替换为 `[REDACTED]`、备份原文件 |
| **`--rotate-help`** | 输出"哪些 key 该去哪个 vendor dashboard rotate"的 cheatsheet |
| **GitGuardian / TruffleHog detector 集成** | 借用业界已有的 100+ 个 detector 规则 |
| **`--exclude-fixture-paths`** | 默认跳过 `tests/` 路径下的 fixture key |
| **ML-based classifier** | LLM 判断"这看起来是真 token 还是 placeholder"，过滤 false positive |
| **sqlite 数据源** | 把 `~/.codex/state_5.sqlite` 也扫进来（dump → text → scan）|
| **首次扫 onboarding 引导** | 第一次跑时引导 user 一个个 category 决定要不要 rotate |
| **`.aifd-ignore` 文件** | 类似 .gitignore，让 user 标"这些命中我看过了不是真 secret，下次别报" |

## 相关文件

| 文件 | 作用 |
|---|---|
| `aifd/models.py:SensitiveMatch` | 数据类（永不存完整 secret）|
| `aifd/vault/scan.py:_DETECTORS` | regex detector 表 |
| `aifd/vault/scan.py:_ENTROPY_RE` + `shannon_entropy` | 熵层 |
| `aifd/vault/scan.py:_ENTROPY_SKIP_RE` | hash 模式跳过 |
| `aifd/vault/scan.py:redact` | head + tail 安全裁剪 |
| `aifd/vault/scan.py:_scan_line` | 行级扫描 + per-line dedupe |
| `aifd/vault/scan.py:scan_file` | 文件级 + 16KB 行截断 |
| `aifd/vault/scan.py:scan_paths` | root 列表遍历 |
| `aifd/render.py:render_scan_matches` | Table / JSON 渲染 + footer 统计 |
| `aifd/cli/vault/scan.py` | CLI 命令 + flag |
| `tests/test_vault_scan.py` | 15 个 detector / entropy / redact / dedupe / scan_paths 测试 |
| `tests/test_vault_cli.py` | 4 个 CLI 端到端测试（含 "完整 secret 不出现在 JSON 输出"的 regression）|
