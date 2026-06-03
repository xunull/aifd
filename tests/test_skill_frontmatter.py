"""Tests for parse_skill_frontmatter (T1 — handwritten YAML parser)."""

from __future__ import annotations

from aifd.providers._utils import parse_skill_frontmatter


def test_simple_inline_scalars() -> None:
    text = """---
name: foo
description: A short description
version: 1.2.3
---

Body.
"""
    out = parse_skill_frontmatter(text)
    assert out == {"name": "foo", "description": "A short description", "version": "1.2.3"}


def test_quoted_values_stripped() -> None:
    text = '---\nname: "quoted-name"\ndescription: \'single-quoted\'\n---\n'
    out = parse_skill_frontmatter(text)
    assert out["name"] == "quoted-name"
    assert out["description"] == "single-quoted"


def test_multiline_block_value() -> None:
    text = """---
name: foo
description: |
  First line of description
  continues here
  and here
---
"""
    out = parse_skill_frontmatter(text)
    assert (
        out["description"]
        == "First line of description continues here and here"
    )


def test_no_frontmatter_returns_empty() -> None:
    assert parse_skill_frontmatter("just body, no frontmatter\n") == {}
    assert parse_skill_frontmatter("") == {}


def test_unclosed_frontmatter_returns_empty() -> None:
    text = "---\nname: foo\ndescription: no closing\nactual body\n"
    assert parse_skill_frontmatter(text) == {}


def test_ignores_unknown_keys() -> None:
    text = """---
name: foo
unrelated: junk
allowed-tools:
  - Bash
  - Read
description: real description
---
"""
    out = parse_skill_frontmatter(text)
    # 'unrelated' and 'allowed-tools' are not in the scalar key set
    assert "unrelated" not in out
    assert "allowed-tools" not in out
    assert out["name"] == "foo"
    assert out["description"] == "real description"


def test_key_with_no_value_skipped() -> None:
    """key: with no inline value and no |/> block is treated as a list/map
    that we don't parse — must skip without crashing."""
    text = """---
name: foo
description:
  - item1
  - item2
version: 1.0
---
"""
    out = parse_skill_frontmatter(text)
    assert out["name"] == "foo"
    assert out["version"] == "1.0"
    assert "description" not in out


def test_comment_lines_ignored() -> None:
    text = """---
# this is a comment
name: foo
# another comment
description: real
---
"""
    out = parse_skill_frontmatter(text)
    assert out == {"name": "foo", "description": "real"}
