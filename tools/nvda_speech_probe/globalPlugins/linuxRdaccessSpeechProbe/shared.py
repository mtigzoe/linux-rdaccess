"""Pure helpers for the opt-in Windows NVDA speech probe."""
from __future__ import annotations

MAX_TEXT_CHARS = 8192


def sequence_text(speech_sequence) -> tuple[str, int]:
    """Extract only spoken string items; speech commands are deliberately omitted."""
    parts = [item for item in speech_sequence if isinstance(item, str)]
    return "".join(parts)[:MAX_TEXT_CHARS], len(parts)


def build_event(speech_sequence, sequence: int) -> dict | None:
    text, segments = sequence_text(speech_sequence)
    if not text:
        return None
    return {"type": "speech", "text": text, "segments": segments, "sequence": sequence}
