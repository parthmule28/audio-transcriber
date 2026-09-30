import pytest

from audio_transcriber.chunking import ChunkSpan, plan_chunks


def test_short_recording_is_a_single_chunk():
    spans = plan_chunks(20.0)
    assert [(s.start, s.end) for s in spans] == [(0.0, 20.0)]
    assert spans[0] == ChunkSpan(0, 0.0, 20.0)
    assert spans[0].duration == 20.0


def test_recording_shorter_than_overlap_window_is_one_chunk():
    spans = plan_chunks(1.5, overlap=2)
    assert len(spans) == 1 and spans[0].end == 1.5


def test_nominal_spans_use_target_duration_and_overlap():
    spans = plan_chunks(100.0)
    assert [(s.start, s.end) for s in spans] == [
        (0.0, 30.0), (29.0, 59.0), (58.0, 88.0), (87.0, 100.0)
    ]


def test_exact_multiple_of_stride_produces_no_empty_trailing_chunk():
    spans = plan_chunks(116.0)
    assert [(s.start, s.end) for s in spans] == [
        (0.0, 30.0), (29.0, 59.0), (58.0, 88.0), (87.0, 116.0)
    ]
    assert all(s.end > s.start for s in spans)
    assert all(s.duration <= 30.0 + 1e-9 for s in spans)
    assert spans[-1].end == pytest.approx(116.0)


@pytest.mark.parametrize("duration", [30.0, 30.5, 31.0, 31.5, 58.0, 59.0, 300.0, 900.0])
def test_spans_are_always_well_formed(duration):
    spans = plan_chunks(duration)
    assert spans[0].start == 0.0
    assert spans[-1].end == pytest.approx(duration)
    for i, span in enumerate(spans):
        assert 0.0 <= span.start < span.end <= duration
        # The pinned single-chunk rule allows 30 < duration <= 31 seconds.
        assert span.duration <= (duration if duration <= 31.0 else 30.0) + 1e-9
        assert span.index == i
    for a, b in zip(spans, spans[1:]):
        assert b.start <= a.end
        assert a.end - b.start == pytest.approx(1.0, abs=1e-6)


def test_boundary_snaps_to_nearest_quiet_point_within_window():
    spans = plan_chunks(100.0, [29.25, 58.0])
    assert spans[0].end == pytest.approx(29.25)
    assert spans[1].start == pytest.approx(28.25)
    assert spans[1].end == pytest.approx(58.0)


def test_boundary_outside_window_is_left_alone():
    spans = plan_chunks(60.0, [30.6, 56.4])
    assert [s.start for s in spans] == [0.0, 29.0, 58.0]


def test_equal_distance_quiet_points_choose_earlier_one():
    spans = plan_chunks(60.0, [31.0, 29.0])
    assert spans[1].start == 28.0


def test_snapping_preserves_strictly_increasing_starts():
    spans = plan_chunks(8.0, [2.0], target=3, overlap=2)
    assert all(a.start < b.start for a, b in zip(spans, spans[1:]))
    assert [s.index for s in spans] == list(range(len(spans)))


def test_snapping_does_not_push_a_start_past_the_end():
    duration = 31.2
    spans = plan_chunks(duration, [duration - 1.4])
    assert spans[0].start == 0.0
    assert spans[0].end == pytest.approx(duration - 1.4)
    assert len(spans) == 2
    assert all(span.start < duration for span in spans)
    assert spans[-1].end == duration


def test_opposing_quiet_point_snaps_never_leave_a_gap():
    spans = plan_chunks(100.0, [27.5, 59.5])

    assert spans[0].start == 0.0
    assert spans[-1].end == pytest.approx(100.0)
    assert all(0.0 <= span.start < span.end <= 100.0 for span in spans)
    assert all(span.duration <= 31.0 for span in spans)
    for previous, following in zip(spans, spans[1:]):
        assert following.start < previous.end
        assert previous.end - following.start == pytest.approx(1.0, abs=1e-6)
