"""Vault file parsing helpers.

Parses YAML frontmatter from markdown notes, extracts H1 titles, and
infers note "type" from the relative path.

Type inference is prefix-tolerant: folders may be prefixed with `NN `
(e.g., `01 Daily/`, `03 People/`) for Obsidian sort ordering — both
`Daily/...` and `01 Daily/...` resolve to `daily`.
"""
from __future__ import annotations

import re
from typing import Any

import yaml

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
H1_RE = re.compile(r"^# +(.+?)\s*$", re.MULTILINE)
FOLDER_PREFIX_RE = re.compile(r"^\d+ +")


def parse_frontmatter(content: str) -> tuple[dict[str, Any] | None, str]:
    """Extract YAML frontmatter from a markdown string.

    Returns (frontmatter_dict_or_None, body). If the content doesn't start
    with a `---` block or the YAML is malformed, returns (None, content).
    """
    match = FRONTMATTER_RE.match(content)
    if match is None:
        return None, content
    try:
        parsed = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None, content
    if not isinstance(parsed, dict):
        return None, content
    return parsed, content[match.end():]


def extract_title(body: str, fallback: str) -> str:
    """First H1 header in the body, or `fallback` if there isn't one."""
    match = H1_RE.search(body)
    if match is None:
        return fallback
    return match.group(1).strip()


_TYPE_BY_FOLDER: dict[str, str] = {
    "Daily": "daily",
    "People": "person",
    "Recipes": "recipe",
    "Career": "project",
    "Exercise": "exercise",
    "Hobbies": "hobby",
    "Learning": "learning",
    "Travel": "travel",
    "Templates": "template",
    "Schedule": "schedule",
    "Money": "money",
    "Agent": "config",
}


def infer_type(relative_path: str) -> str:
    """Map a vault-relative path to a coarse note type.

    Strips an optional `NN ` Obsidian sort-order prefix from the top-level
    folder before matching.
    """
    rel = relative_path.replace("\\", "/")
    if "/" not in rel:
        return "misc"
    first = rel.split("/", 1)[0]
    bare = FOLDER_PREFIX_RE.sub("", first)
    return _TYPE_BY_FOLDER.get(bare, "misc")
