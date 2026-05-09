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
    """Build a SourceRef by locating entity_text inside text."""
    idx = text.find(entity_text)
    if idx == -1:
        # Fuzzy: use first 50 chars of entity as snippet
        char_start = global_char_offset
        char_end = global_char_offset + len(entity_text)
        snippet = entity_text[:50]
    else:
        char_start = global_char_offset + idx
        char_end = char_start + len(entity_text)
        start_snip = max(0, idx - 25)
        snippet = text[start_snip : idx + len(entity_text) + 25][:50]

    return SourceRef(
        document_id=document_id,
        document_type=document_type,
        page=page,
        char_start=char_start,
        char_end=char_end,
        snippet=snippet,
    )
