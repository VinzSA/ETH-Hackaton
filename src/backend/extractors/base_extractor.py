"""
Base extractor: shared Claude call + SourceRef builder.
All specialized extractors inherit from this.
"""
import json
import os
import re
from typing import Any

import anthropic

from src.schema.preop_brief import SourceRef

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _client


def claude_extract(
    system_prompt: str,
    text: str,
    document_id: str,
    max_tokens: int = 2048,
    model: str = "claude-haiku-4-5-20251001",
) -> dict | list | None:
    """
    Call Claude with a structured extraction prompt.
    Returns parsed JSON or None on failure.
    Text is truncated to 8000 chars to keep latency low.
    """
    client = _get_client()
    truncated = text[:8000]
    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": truncated}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)
    except (json.JSONDecodeError, anthropic.APIError, IndexError):
        return None


def make_source_ref(
    document_id: str,
    document_type: str,
    text: str,
    entity_text: str,
    page: int = 1,
    global_char_offset: int = 0,
) -> SourceRef:
    """Build a SourceRef by locating entity_text inside text.

    Snippets are sentence-bounded so the UI can show the exact source line
    behind every fact instead of a truncated 50-char window.
    """
    idx = text.find(entity_text)
    if idx == -1:
        char_start = global_char_offset
        char_end = global_char_offset + len(entity_text)
        snippet = entity_text.strip()
    else:
        char_start = global_char_offset + idx
        char_end = char_start + len(entity_text)
        snippet = _sentence_around(text, idx, idx + len(entity_text))

    return SourceRef(
        document_id=document_id,
        document_type=document_type,
        page=page,
        char_start=char_start,
        char_end=char_end,
        snippet=snippet,
    )


_SENTENCE_END = re.compile(r"[.!?\n]")


def _sentence_around(text: str, start: int, end: int, max_chars: int = 320) -> str:
    """Return the sentence containing [start:end], capped at max_chars."""
    s_start = start
    while s_start > 0 and not _SENTENCE_END.match(text[s_start - 1]):
        s_start -= 1
    while s_start < start and text[s_start] in " \t\n":
        s_start += 1

    s_end = end
    while s_end < len(text) and not _SENTENCE_END.match(text[s_end]):
        s_end += 1
    if s_end < len(text):
        s_end += 1

    snippet = text[s_start:s_end].strip()
    if len(snippet) > max_chars:
        keep = max_chars - 1
        head = max(0, (start - s_start) - keep // 2)
        snippet = snippet[head : head + keep] + "…"
    return snippet
