import re
import string

from audio_transcriber.constants import (
    MAX_BOUNDARY_DEDUP_TOKENS,
    MIN_BOUNDARY_DEDUP_TOKENS,
)


def _normalized_token(token: str) -> str:
    return token.casefold().strip(string.punctuation)


def dedupe_boundary(
    previous: str,
    incoming: str,
    *,
    min_tokens: int = MIN_BOUNDARY_DEDUP_TOKENS,
    max_tokens: int = MAX_BOUNDARY_DEDUP_TOKENS,
) -> str:
    if not incoming.strip():
        return incoming

    previous_tokens = re.findall(r"\S+", previous)
    incoming_tokens = re.findall(r"\S+", incoming)
    largest_match = min(len(previous_tokens), len(incoming_tokens), max_tokens)

    for size in range(largest_match, min_tokens - 1, -1):
        previous_suffix = previous_tokens[-size:]
        incoming_prefix = incoming_tokens[:size]
        if all(
            _normalized_token(left) == _normalized_token(right)
            for left, right in zip(previous_suffix, incoming_prefix)
        ):
            return " ".join(incoming_tokens[size:])

    return incoming


class TranscriptAssembler:
    def __init__(self) -> None:
        self._chunks: dict[int, str] = {}

    def add(self, index: int, text: str) -> None:
        self._chunks[index] = text

    def text(self) -> str:
        assembled: list[str] = []
        for index in sorted(self._chunks):
            chunk = self._chunks[index]
            if not chunk.strip():
                continue
            if assembled:
                chunk = dedupe_boundary(" ".join(assembled), chunk)
            if chunk.strip():
                assembled.append(chunk)
        return " ".join(assembled)

    def covered_indices(self) -> set[int]:
        return set(self._chunks)
