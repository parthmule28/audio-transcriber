"""Deterministic planning of overlapping audio chunks."""

from typing import NamedTuple, Sequence

from audio_transcriber import constants


class ChunkSpan(NamedTuple):
    index: int
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def plan_chunks(
    duration: float,
    quiet_midpoints: Sequence[float] = (),
    *,
    target: int = constants.TARGET_CHUNK_SECONDS,
    overlap: int = constants.OVERLAP_SECONDS,
    search_window: float = 1.5,
) -> list[ChunkSpan]:
    """Plan gap-free spans, snapping chunk ends near quiet points.

    Each following span starts ``overlap`` seconds before the preceding end.
    Snapping ends rather than independent starts keeps coverage continuous.
    """
    if target <= 0 or overlap < 0 or overlap >= target:
        raise ValueError("target must be positive and overlap must be in [0, target)")
    if search_window < 0:
        raise ValueError("search_window must be non-negative")
    if duration <= target + overlap:
        return [ChunkSpan(0, 0.0, duration)]

    stride = target - overlap
    spans: list[ChunkSpan] = []
    start = 0.0
    while start < duration:
        end = min(start + target, duration)
        if end < duration:
            nearby = (
                point
                for point in quiet_midpoints
                if start < point <= duration and abs(point - end) <= search_window
            )
            snapped = min(nearby, key=lambda point: (abs(point - end), point), default=end)
            min_advance = max(0.05, stride * 0.01)
            earliest_end = min(end, start + overlap + min_advance)
            end = min(max(snapped, earliest_end), end)

        spans.append(ChunkSpan(len(spans), start, end))
        if end >= duration:
            break
        start = end - overlap

    return spans
