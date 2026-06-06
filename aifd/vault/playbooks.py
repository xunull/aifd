"""Rotation playbooks — the "what to do next" library for each category.

vault watch's differentiator vs Sentry: every finding maps to a concrete
vendor dashboard + step-by-step instructions. Detection → action in one
click instead of "now go figure out how to rotate this."

i18n locked: en + zh shipped in v0.7 (per /plan-eng-review TODO 3 → C).
Add a third locale by adding a key to each PLAYBOOK entry's `instruction`
dict; lookups fall back to en.
"""

from __future__ import annotations

from typing import Final, TypedDict


class PlaybookText(TypedDict):
    vendor_dashboard: str
    instruction: dict[str, str]  # locale → markdown-friendly text
    severity: str  # critical | high | medium | low


_GENERIC_FALLBACK: Final[PlaybookText] = {
    "vendor_dashboard": "",
    "instruction": {
        "en": (
            "1. Find where this credential is configured (search env files, "
            "CI secrets, k8s secrets, cloud secret managers)\n"
            "2. Rotate it at the issuing vendor's console\n"
            "3. Update every consumer\n"
            "4. Audit usage logs for unexpected activity since first_seen"
        ),
        "zh": (
            "1. 找到这个凭证配置的位置（搜 env 文件、CI secrets、k8s secrets、"
            "云端 secret manager）\n"
            "2. 在发行方的控制台 rotate\n"
            "3. 更新每个使用方\n"
            "4. 审计 first_seen 之后的使用日志是否有异常"
        ),
    },
    "severity": "high",
}


PLAYBOOKS: Final[dict[str, PlaybookText]] = {
    "openai_key": {
        "vendor_dashboard": "https://platform.openai.com/api-keys",
        "instruction": {
            "en": (
                "1. Revoke the leaked key at the dashboard\n"
                "2. Generate a new key\n"
                "3. Update OPENAI_API_KEY env wherever used (.env, CI secrets, "
                "k8s secrets, cloud secret managers)\n"
                "4. Audit recent usage for unexpected requests"
            ),
            "zh": (
                "1. 在 dashboard 撤销泄漏的 key\n"
                "2. 生成新 key\n"
                "3. 更新所有用到的地方的 OPENAI_API_KEY 环境变量（.env、CI secrets、"
                "k8s secrets、云端 secret manager）\n"
                "4. 审计最近的 usage，查看有没有异常请求"
            ),
        },
        "severity": "critical",
    },
    "anthropic_key": {
        "vendor_dashboard": "https://console.anthropic.com/settings/keys",
        "instruction": {
            "en": (
                "1. Revoke the leaked key in the Anthropic Console\n"
                "2. Generate a new key with the same scope\n"
                "3. Update ANTHROPIC_API_KEY env in every consumer\n"
                "4. Check Console > Usage for spike in token count or "
                "unexpected models"
            ),
            "zh": (
                "1. 在 Anthropic Console 撤销泄漏的 key\n"
                "2. 生成同 scope 的新 key\n"
                "3. 在所有使用方更新 ANTHROPIC_API_KEY 环境变量\n"
                "4. 检查 Console > Usage 是否有 token 暴涨或意外的模型调用"
            ),
        },
        "severity": "critical",
    },
    "github_pat": {
        "vendor_dashboard": "https://github.com/settings/tokens",
        "instruction": {
            "en": (
                "1. Delete the leaked token at github.com/settings/tokens\n"
                "2. Regenerate with the same minimum scope (avoid 'repo' "
                "broad scope if possible)\n"
                "3. Update GITHUB_TOKEN / GH_TOKEN env wherever used\n"
                "4. Check github.com/settings/security-log for activity since "
                "first_seen"
            ),
            "zh": (
                "1. 到 github.com/settings/tokens 删除泄漏的 token\n"
                "2. 用最小 scope 重新生成（尽量避免 'repo' 这种宽 scope）\n"
                "3. 更新所有用到 GITHUB_TOKEN / GH_TOKEN 的位置\n"
                "4. 到 github.com/settings/security-log 查 first_seen 之后的操作"
            ),
        },
        "severity": "critical",
    },
    "github_oauth": {
        "vendor_dashboard": "https://github.com/settings/applications",
        "instruction": {
            "en": (
                "1. Revoke the OAuth app authorization\n"
                "2. Reset the OAuth app's client secret\n"
                "3. Re-authorize the app from each user account that needs it\n"
                "4. Audit github.com/settings/security-log for unauthorized "
                "actions"
            ),
            "zh": (
                "1. 撤销 OAuth app 授权\n"
                "2. 在 OAuth app 重置 client secret\n"
                "3. 在每个需要的用户账户重新授权\n"
                "4. 到 github.com/settings/security-log 审计是否有未授权操作"
            ),
        },
        "severity": "high",
    },
    "aws_access_key": {
        "vendor_dashboard": "https://console.aws.amazon.com/iam/home#/users",
        "instruction": {
            "en": (
                "1. `aws iam delete-access-key --access-key-id AKIA...` "
                "(or via Console > IAM > Users > Security credentials)\n"
                "2. Create a new access key for the user/role\n"
                "3. Update AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY env in "
                "every consumer\n"
                "4. Check CloudTrail for unexpected API calls under this key"
            ),
            "zh": (
                "1. `aws iam delete-access-key --access-key-id AKIA...`"
                "（或在 Console > IAM > Users > Security credentials 操作）\n"
                "2. 给同一 user/role 新建 access key\n"
                "3. 在所有使用方更新 AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY\n"
                "4. 在 CloudTrail 查这个 key 有没有意外 API 调用"
            ),
        },
        "severity": "critical",
    },
    "aws_secret": {
        "vendor_dashboard": "https://console.aws.amazon.com/iam/home#/users",
        "instruction": {
            "en": (
                "AWS secret access key paired with an Access Key ID. Treat "
                "the pair as compromised:\n"
                "1. Delete the corresponding access key in IAM\n"
                "2. Create a new one\n"
                "3. Update both AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY "
                "everywhere\n"
                "4. Audit CloudTrail for activity since first_seen"
            ),
            "zh": (
                "AWS secret access key 与 Access Key ID 是一对，按整对泄漏处理：\n"
                "1. 在 IAM 删除对应的 access key\n"
                "2. 新建一对\n"
                "3. 在所有使用方更新 AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY\n"
                "4. 在 CloudTrail 审计 first_seen 之后的活动"
            ),
        },
        "severity": "critical",
    },
    "slack_token": {
        "vendor_dashboard": "https://api.slack.com/apps",
        "instruction": {
            "en": (
                "1. Open the Slack app at api.slack.com/apps\n"
                "2. OAuth & Permissions > revoke + regenerate tokens\n"
                "3. Update SLACK_BOT_TOKEN / SLACK_USER_TOKEN env in every "
                "consumer\n"
                "4. Audit workspace admin log for any unexpected actions"
            ),
            "zh": (
                "1. 在 api.slack.com/apps 打开对应 Slack app\n"
                "2. OAuth & Permissions > 撤销并重新生成 token\n"
                "3. 在所有使用方更新 SLACK_BOT_TOKEN / SLACK_USER_TOKEN\n"
                "4. 查 workspace admin 日志是否有意外操作"
            ),
        },
        "severity": "high",
    },
    "jwt": {
        "vendor_dashboard": "",
        "instruction": {
            "en": (
                "JWTs are server-issued. Rotation depends on your auth setup:\n"
                "1. Identify the signing key (HMAC secret / RS256 private key) "
                "and rotate it\n"
                "2. Invalidate all existing sessions / tokens\n"
                "3. Force all users to re-authenticate\n"
                "4. Investigate how the token leaked (logs, env vars, "
                "client-side bug)"
            ),
            "zh": (
                "JWT 是服务器签发的，rotate 步骤取决于你的鉴权架构：\n"
                "1. 找到签名 key（HMAC secret 或 RS256 私钥），rotate 它\n"
                "2. 让所有现有 session / token 失效\n"
                "3. 强制所有用户重新登录\n"
                "4. 排查 token 是怎么泄漏的（日志、env、前端 bug）"
            ),
        },
        "severity": "critical",
    },
    "gcp_service_account": {
        "vendor_dashboard": (
            "https://console.cloud.google.com/iam-admin/serviceaccounts"
        ),
        "instruction": {
            "en": (
                "1. In IAM & Admin > Service Accounts > the affected SA > "
                "Keys, delete the leaked key\n"
                "2. Create a replacement key\n"
                "3. Update GOOGLE_APPLICATION_CREDENTIALS path or the inline "
                "JSON env in every consumer\n"
                "4. Check Cloud Audit Logs filtered to this SA for activity "
                "since first_seen"
            ),
            "zh": (
                "1. 在 IAM & Admin > Service Accounts > 受影响的 SA > Keys，"
                "删除泄漏的 key\n"
                "2. 建一个新 key\n"
                "3. 在所有使用方更新 GOOGLE_APPLICATION_CREDENTIALS 路径或"
                "内联 JSON 环境变量\n"
                "4. 在 Cloud Audit Logs 用该 SA 筛选 first_seen 之后的活动"
            ),
        },
        "severity": "critical",
    },
    "email": {
        "vendor_dashboard": "",
        "instruction": {
            "en": (
                "PII (email address) detection — not a credential. Actions:\n"
                "1. If this is your own email, no rotation needed\n"
                "2. If a customer email leaked into a session log: review your "
                "PII handling policy and consider redacting the source jsonl\n"
                "3. Mute this finding (not a security incident) and continue"
            ),
            "zh": (
                "PII（邮箱）检测，不是凭证。操作：\n"
                "1. 如果是你自己的邮箱，无需 rotate\n"
                "2. 如果是客户邮箱泄漏到了 session log：审视你的 PII 处理"
                "策略，考虑把源 jsonl redact 掉\n"
                "3. mute 这条 finding（不是安全事件）继续工作"
            ),
        },
        "severity": "low",
    },
    "high_entropy": {
        "vendor_dashboard": "",
        "instruction": {
            "en": (
                "Entropy-only detection — could be a real secret OR a hash, "
                "UUID, embedding, etc.\n"
                "1. Look at the surrounding context in the jsonl line to "
                "judge: is this a credential?\n"
                "2. If yes, treat as the appropriate category (rotate per "
                "issuing vendor)\n"
                "3. If no, mute this fingerprint (it'll keep showing up "
                "otherwise)"
            ),
            "zh": (
                "仅熵检测，可能是真 secret 也可能是 hash / UUID / embedding：\n"
                "1. 看 jsonl 中的上下文判断是不是凭证\n"
                "2. 如果是，按对应类别处理（在签发方 rotate）\n"
                "3. 如果不是，mute 这个 fingerprint（否则会一直出现）"
            ),
        },
        "severity": "medium",
    },
}


def lookup(category: str) -> PlaybookText:
    """Return the playbook for a category, or the generic fallback.

    Never raises; falling back to generic means even unknown / future
    categories get a sensible "find it, rotate it, audit it" instruction.
    """
    return PLAYBOOKS.get(category, _GENERIC_FALLBACK)


def render_for_webhook(
    category: str, lang: str = "en",
) -> dict[str, str]:
    """Return a flat dict for embedding in webhook JSON payload.

    Format:
        {
          "vendor_dashboard": "https://...",
          "instruction": "...",
          "severity": "critical"
        }

    Falls back to "en" if the requested locale is missing.
    """
    pb = lookup(category)
    instr = pb["instruction"].get(lang) or pb["instruction"]["en"]
    return {
        "vendor_dashboard": pb["vendor_dashboard"],
        "instruction": instr,
        "severity": pb["severity"],
    }


def known_categories() -> list[str]:
    """For tests, docs, and the CLI `--list-playbooks` flag."""
    return sorted(PLAYBOOKS.keys())
