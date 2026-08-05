"""Split document text into overlapping chunks for the per-session doc store.

Sizing is character-based rather than token-exact: it's cheap, dependency-free,
and close enough since the Voyage budget here is generous relative to a single
uploaded document. Overlap keeps a sentence that straddles a boundary
retrievable from both sides.
"""

from __future__ import annotations

import re

# Rough chars-per-token for English prose; turns the token-ish knobs below into
# character windows without importing a tokenizer.
_CHARS_PER_TOKEN = 4

CHUNK_TOKENS = 300
CHUNK_OVERLAP_TOKENS = 50


def chunk_text(text: str) -> list[str]:
    """Return a list of overlapping text chunks, split on paragraph/sentence
    boundaries where possible so chunks don't start mid-sentence."""
    size = CHUNK_TOKENS * _CHARS_PER_TOKEN
    overlap = CHUNK_OVERLAP_TOKENS * _CHARS_PER_TOKEN

    units = _split_units(text)

    chunks, buf = [], ""
    for unit in units:
        if len(buf) + len(unit) + 1 <= size:
            buf = f"{buf}\n{unit}".strip()
        else:
            if buf:
                chunks.append(buf)
            # Start the next chunk with a tail of the previous one (overlap).
            tail = buf[-overlap:] if overlap and buf else ""
            buf = f"{tail}\n{unit}".strip() if tail else unit
    if buf:
        chunks.append(buf)

    # A single huge paragraph can still exceed size; hard-split those.
    out = []
    for c in chunks:
        if len(c) <= size:
            out.append(c)
        else:
            out.extend(c[i:i + size] for i in range(0, len(c), size - overlap or size))
    return [c.strip() for c in out if c.strip()]


def _split_units(text: str) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if paras:
        return paras
    # No paragraph breaks: fall back to sentences.
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
