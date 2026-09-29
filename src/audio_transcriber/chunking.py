"""Deterministic planning of overlapping audio chunks."""

from math import ceil, nextafter
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
    """Plan fixed-duration spans, optionally snapping starts to quiet points."""
    if duration <= target + overlap:
        return [ChunkSpan(0, 0.0, duration)]

    stride = target - overlap
    count = ceil((duration - target) / stride) + 1
    starts = [0.0]
    for i in range(1, count):
        nominal = float(i * stride)
        nearby = (point for point in quiet_midpoints if abs(point - nominal) <= search_window)
        snapped = min(nearby, key=lambda point: (abs(point - nominal), point), default=nominal)
        start = min(max(snapped, nextafter(starts[-1], float("inf"))),
                    nextafter(duration, float("-inf")))
        if start < duration - 0.05:
            starts.append(start)

    return [ChunkSpan(i, start, min(start + target, duration))
            for i, start in enumerate(starts)]
