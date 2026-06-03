"""Aggregation logic — turn flat SkillInvocation events into SkillStats rows.

Lives outside cli/ so v0.3 `aifd ai stats` can reuse it without coupling
to a specific command's flag layout. Pure function, no IO.

Pipeline:

    list[SkillInvocation]  ──>  group by skill_name  ──>  list[SkillStats]
                                       │
                                       ├── count_claude  = sum(p == 'claude')
                                       ├── count_codex   = sum(p == 'codex')
                                       ├── total         = len()
                                       ├── unique_cwd    = len({cwd for inv})
                                       └── last_used     = max(ts where ts != None)
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime

from aifd.models import SkillInvocation, SkillStats


def aggregate_skill_stats(
    invocations: Iterable[SkillInvocation],
) -> list[SkillStats]:
    """Group SkillInvocation events by skill_name and compute per-skill stats.

    Returns the list sorted by total descending, then skill_name ascending
    for stable tie-breaking.
    """
    buckets: dict[str, list[SkillInvocation]] = defaultdict(list)
    for inv in invocations:
        buckets[inv.skill_name].append(inv)

    stats: list[SkillStats] = []
    for skill_name, group in buckets.items():
        count_claude = sum(1 for i in group if i.provider == "claude")
        count_codex = sum(1 for i in group if i.provider == "codex")
        total = len(group)
        # str(cwd) so different Path instances pointing to the same path
        # collapse correctly across providers.
        unique_cwd_count = len({str(i.cwd) for i in group if str(i.cwd)})
        timestamps = [i.ts for i in group if i.ts is not None]
        last_used: datetime | None = max(timestamps) if timestamps else None

        # is_gstack: any invocation originally carried the gstack- prefix.
        # The OR aggregation matches user expectation — if you ever called
        # this skill as `/gstack-foo` in any tool, it shows as a gstack skill.
        is_gstack = any(i.is_gstack for i in group)

        stats.append(
            SkillStats(
                skill_name=skill_name,
                count_claude=count_claude,
                count_codex=count_codex,
                total=total,
                unique_cwd_count=unique_cwd_count,
                last_used=last_used,
                is_gstack=is_gstack,
            )
        )

    stats.sort(key=lambda s: (-s.total, s.skill_name))
    return stats
