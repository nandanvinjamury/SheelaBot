"""Markdown chunking for RAG.

Splits notes by `## section` headers. The pre-section text (between
frontmatter and the first `##`) becomes an "_intro" chunk. YAML frontmatter
is prepended to the first chunk so its terms (names, ratings, tags) are
searchable. Over-long chunks are truncated to stay under the embedding
model's input limit.
"""
from __future__ import annotations

import re

import yaml

from sheela.vault.contract import parse_frontmatter

SECTION_SPLIT_RE = re.compile(r"^(?=## )", re.MULTILINE)
INTRO_TITLE = "_intro"
MAX_CHUNK_CHARS = 6000


def chunk_by_sections(
    content: str, *, max_chars: int = MAX_CHUNK_CHARS
) -> list[dict[str, str]]:
    fm, body = parse_frontmatter(content)

    sections: list[dict[str, str]] = []
    for part in SECTION_SPLIT_RE.split(body):
        stripped = part.strip()
        if not stripped:
            continue
        first_line = stripped.split("\n", 1)[0]
        if first_line.startswith("## "):
            title = first_line[3:].strip() or INTRO_TITLE
        else:
            title = INTRO_TITLE
        sections.append({"title": title, "content": stripped})

    if not sections:
        # File with only frontmatter or empty body — still want a single chunk
        # so frontmatter searches work.
        sections.append({"title": INTRO_TITLE, "content": body.strip()})

    if fm:
        try:
            fm_yaml = yaml.safe_dump(fm, sort_keys=False).strip()
        except yaml.YAMLError:
            fm_yaml = ""
        if fm_yaml:
            sections[0]["content"] = (
                f"---\n{fm_yaml}\n---\n\n{sections[0]['content']}"
            ).strip()

    for s in sections:
        if len(s["content"]) > max_chars:
            s["content"] = s["content"][:max_chars] + "\n[... truncated]"

    return sections
