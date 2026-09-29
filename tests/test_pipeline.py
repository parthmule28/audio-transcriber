import shutil
import threading
from pathlib import Path

import pytest

from audio_transcriber import constants
from audio_transcriber.audio import MediaInfo
from audio_transcriber.errors import (
    AudioPreparationError,
    CancelledError,
    NoAudioStreamError,
    ProviderError,
    RateLimitError,
    RequestTimeoutError,
    TranscriberError,
)
from audio_transcriber.openrouter_client import TranscriptionResponse, Usage
from audio_transcriber.pipeline import (
    ChunkOutcome,
    PipelineCallbacks,
    TranscriptionPipeline,
    TranscriptionReport,
)


class FakeWorkspace:
    def __init__(self, root: Path):
        self._root = root
        self.path = root / "fake-workspace"
        self.cleanup_calls = 0
        self.files_at_cleanup = None

    def chunk_path(self, index: int) -> Path:
        self.path.mkdir(parents=True, exist_ok=True)
        return self.path / f"chunk_{index:04d}.wav"

    def cleanup(self) -> None:
        self.cleanup_calls += 1
        self.files_at_cleanup = list(self.path.glob("*.wav"))
        shutil.rmtree(self.path, ignore_errors=True)


class FakeClient:
    def __init__(self, handler=None):
        self.handler = handler or (lambda index, attempt, path: response(f"chunk {index}"))
        self.calls = []
        self.close_calls = 0
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def transcribe(self, wav_path: Path, model: str, language: str | None = None):
        index = int(wav_path.stem.removeprefix("chunk_"))
        with self._lock:
            self.calls.append((index, model, language))
            attempt = sum(call[0] == index for call in self.calls)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            return self.handler(index, attempt, wav_path)
        finally:
            with self._lock:
                self.active -= 1

    def close(self):
        with self._lock:
            self.close_calls += 1


def response(text: str, *, cost: float | None = 0.001, seconds: float | None = 1.0):
    return TranscriptionResponse(text, Usage(seconds, 1, 1, 0, cost), "generation")


class RecordingCallbacks(PipelineCallbacks):
    def __init__(self):
        self.events = []
        self._lock = threading.Lock()

    def _record(self, event):
        with self._lock:
            self.events.append(event)

    def on_analyzing(self):
        self._record(("analyzing",))

    def on_planned(self, total: int):
        self._record(("planned", total))

    def on_chunk_started(self, index: int, total: int):
        self._record(("started", index, total))

    def on_chunk_finished(self, outcome: ChunkOutcome):
        self._record(("finished_chunk", outcome.index))

    def on_chunk_failed(self, index: int, error):
        self._record(("failed_chunk", index, type(error)))

    def on_finished(self, report: TranscriptionReport):
        self._record(("finished", report.is_complete))

    def on_cancelled(self, report: TranscriptionReport):
        self._record(("cancelled", report.cancelled))


@pytest.fixture
def tmp_media(tmp_path):
    """A synthetic local media marker; media operations are replaced below."""
    source = tmp_path / "synthetic.wav"
    source.write_bytes(b"synthetic fake WAV media")
    return source


@pytest.fixture
def fake_workspace(tmp_path):
    return FakeWorkspace(tmp_path)


@pytest.fixture
def fake_media(monkeypatch):
    state = {"duration": 20.0, "quiet": [], "probes": [], "extractions": []}

    def probe(source, *, ffprobe=None):
        state["probes"].append((source, ffprobe))
        return MediaInfo(state["duration"], True, "wav", "pcm_s16le", 44100, 1)

    def detect_quiet_midpoints(source, *, noise_db, min_duration, ffmpeg=None):
        state["quiet_args"] = (source, noise_db, min_duration, ffmpeg)
        return list(state["quiet"])

    def extract_chunk(source, start, duration, out_path, *, ffmpeg=None):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"synthetic fake chunk")
        state["extractions"].append((start, duration, out_path, ffmpeg))
        return out_path

    monkeypatch.setattr("audio_transcriber.pipeline.probe", probe)
    monkeypatch.setattr("audio_transcriber.pipeline.detect_quiet_midpoints", detect_quiet_midpoints)
    monkeypatch.setattr("audio_transcriber.pipeline.extract_chunk", extract_chunk)
    return state


def run_one_shot(client, media, **kwargs) -> TranscriptionReport:
    pipeline = TranscriptionPipeline(
        client,
        model="approved-model",
        sleep_fn=kwargs.pop("sleep_fn", lambda delay: None),
        **kwargs,
    )
    return pipeline.run(media)


def test_report_total_cost_is_none_when_any_chunk_omits_cost(
    tmp_media, fake_media, fake_workspace
):
    client = FakeClient(lambda index, attempt, path: response("text", cost=None))
    report = run_one_shot(client, tmp_media, workspace=fake_workspace)
    assert report.total_cost() is None
    assert "unavailable" in report.cost_note().lower()


def test_report_total_cost_sums_when_all_chunks_report(tmp_media, fake_media, fake_workspace):
    client = FakeClient(lambda index, attempt, path: response("text", cost=0.003))
    assert run_one_shot(client, tmp_media, workspace=fake_workspace).total_cost() == pytest.approx(0.003)


def test_report_total_cost_sums_all_completed_chunks(tmp_media, fake_media, fake_workspace):
    fake_media["duration"] = 70.0
    client = FakeClient(
        lambda index, attempt, path: response("text", cost=(index + 1) / 1000)
    )
    report = run_one_shot(client, tmp_media, workspace=fake_workspace)
    assert report.total_cost() == pytest.approx(0.006)


def test_report_total_cost_is_none_when_an_outcome_has_no_usage(
    tmp_media, fake_media, fake_workspace
):
    client = FakeClient(lambda index, attempt, path: TranscriptionResponse("text", None, None))
    assert run_one_shot(client, tmp_media, workspace=fake_workspace).total_cost() is None


def test_report_usage_totals_are_all_or_nothing(tmp_media, fake_media, fake_workspace):
    client = FakeClient(lambda index, attempt, path: response("text", seconds=None))
    report = run_one_shot(client, tmp_media, workspace=fake_workspace)
    assert report.total_seconds() is None


def test_run_uses_fixed_chunk_plan_and_extracts_only_in_workers(
    tmp_media, fake_media, fake_workspace
):
    fake_media["duration"] = 100.0
    fake_media["quiet"] = [30.0]
    callbacks = RecordingCallbacks()
    client = FakeClient()
    report = run_one_shot(client, tmp_media, workspace=fake_workspace, callbacks=callbacks)
    assert report.total_chunks == 4
    assert sorted((start, duration) for start, duration, *_ in fake_media["extractions"]) == [
        (0.0, 30.0), (30.0, 30.0), (58.0, 30.0), (87.0, 13.0)
    ]
    assert fake_media["quiet_args"][1:3] == (-35.0, 0.4)
    assert callbacks.events[0] == ("analyzing",)
    assert callbacks.events[1] == ("planned", 4)
    assert callbacks.events[-1] == ("finished", True)
    assert fake_workspace.files_at_cleanup == []


def test_no_audio_stream_propagates_and_workspace_is_cleaned(
    tmp_media, fake_media, fake_workspace, monkeypatch
):
    monkeypatch.setattr(
        "audio_transcriber.pipeline.probe",
        lambda source, *, ffprobe=None: (_ for _ in ()).throw(NoAudioStreamError()),
    )
    with pytest.raises(NoAudioStreamError):
        run_one_shot(FakeClient(), tmp_media, workspace=fake_workspace)
    assert fake_workspace.cleanup_calls == 1


def test_pipeline_never_exceeds_three_concurrent_requests(
    tmp_media, fake_media, fake_workspace
):
    fake_media["duration"] = 100.0
    three_started = threading.Event()

    def handler(index, attempt, path):
        if client.active == constants.MAX_CONCURRENT_REQUESTS:
            three_started.set()
        assert three_started.wait(timeout=2)
        return response(f"chunk {index}")

    client = FakeClient(handler)
    report = run_one_shot(client, tmp_media, workspace=fake_workspace)
    assert report.is_complete
    assert client.max_active == 3


def test_rate_limit_is_retried_with_retry_after_then_succeeds(
    tmp_media, fake_media, fake_workspace
):
    attempts = 0
    sleeps = []

    def handler(index, attempt, path):
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise RateLimitError("limited", retry_after=0)
        return response("recovered")

    report = run_one_shot(
        FakeClient(handler), tmp_media, workspace=fake_workspace,
        sleep_fn=sleeps.append,
    )
    assert report.is_complete
    assert attempts == 3
    assert sleeps == [0, 0]


def test_rate_limit_without_retry_after_uses_bounded_exponential_delays(
    tmp_media, fake_media, fake_workspace
):
    sleeps = []

    def handler(index, attempt, path):
        if attempt < 4:
            raise RateLimitError("limited")
        return response("recovered")

    report = run_one_shot(
        FakeClient(handler), tmp_media, workspace=fake_workspace,
        sleep_fn=sleeps.append,
    )
    assert report.is_complete
    assert sleeps == [2.0, 4.0, 8.0]


def test_rate_limit_budget_exhausted_stops_with_partial_report(
    tmp_media, fake_media, fake_workspace
):
    client = FakeClient(lambda index, attempt, path: (_ for _ in ()).throw(
        RateLimitError("limited", retry_after=0)
    ))
    report = run_one_shot(client, tmp_media, workspace=fake_workspace)
    assert report.failures
    assert report.cancelled is False
    assert isinstance(report.failures[0], RateLimitError)
    assert len(client.calls) == constants.MAX_RATE_LIMIT_RETRIES + 1


@pytest.mark.parametrize(
    "error",
    [
        RequestTimeoutError("timeout"),
        ProviderError("bad gateway", status_code=502),
        ProviderError("unavailable", status_code=503),
    ],
)
def test_timeout_and_provider_errors_are_not_retried(
    tmp_media, fake_media, fake_workspace, error
):
    client = FakeClient(lambda index, attempt, path: (_ for _ in ()).throw(error))
    report = run_one_shot(client, tmp_media, workspace=fake_workspace, sleep_fn=lambda _: None)
    assert len(client.calls) == 1
    assert type(report.failures[0]) is type(error)


def test_unexpected_chunk_errors_become_safe_partial_failures(
    tmp_media, fake_media, fake_workspace
):
    client = FakeClient(
        lambda index, attempt, path: (_ for _ in ()).throw(
            RuntimeError("private audio transcript or key")
        )
    )
    report = run_one_shot(client, tmp_media, workspace=fake_workspace)
    error = report.failures[0]
    assert type(error) is TranscriberError
    assert "private audio transcript or key" not in str(error)
    assert report.is_complete is False


def test_results_are_assembled_in_index_order_not_completion_order(
    tmp_media, fake_media, fake_workspace
):
    fake_media["duration"] = 70.0
    second_finished = threading.Event()
    first_finished = threading.Event()
    completion_order = []

    def handler(index, attempt, path):
        if index == 2:
            completion_order.append(index)
            second_finished.set()
            return response("third")
        if index == 1:
            assert second_finished.wait(timeout=2)
            completion_order.append(index)
            first_finished.set()
            return response("second")
        assert first_finished.wait(timeout=2)
        completion_order.append(index)
        return response("first")

    client = FakeClient(handler)
    report = run_one_shot(client, tmp_media, workspace=fake_workspace)
    assert completion_order == [2, 1, 0]
    assert report.transcript() == "first second third"


@pytest.fixture
def cancelled_pipeline(tmp_media, fake_media, fake_workspace):
    fake_media["duration"] = 130.0
    release_in_flight = threading.Event()
    interrupted = threading.Event()
    entered = {index: threading.Event() for index in (1, 2, 3)}
    first_finished = threading.Event()
    callbacks = RecordingCallbacks()

    def handler(index, attempt, path):
        if index == 0:
            return response("first")
        if index in entered:
            entered[index].set()
            release_in_flight.wait(timeout=3)
            if interrupted.is_set():
                raise RuntimeError("request interrupted by client close")
        return response(f"chunk {index}")

    class ReusableClient(FakeClient):
        def __init__(self):
            super().__init__(handler)
            self.closed = False
            self.reopen_calls = 0
            self.interrupted = interrupted

        def transcribe(self, wav_path, model, language=None):
            if self.closed:
                raise RuntimeError("client is closed")
            return super().transcribe(wav_path, model, language)

        def close(self):
            self.closed = True
            interrupted.set()
            release_in_flight.set()
            super().close()

        def reopen(self):
            self.closed = False
            interrupted.clear()
            self.reopen_calls += 1

    def on_chunk_finished(outcome):
        RecordingCallbacks.on_chunk_finished(callbacks, outcome)
        if outcome.index == 0:
            first_finished.set()

    callbacks.on_chunk_finished = on_chunk_finished
    client = ReusableClient()
    pipeline = TranscriptionPipeline(
        client, model="approved-model", callbacks=callbacks,
        workspace=fake_workspace, sleep_fn=lambda delay: None,
    )
    result = {}

    def run_pipeline():
        try:
            result["report"] = pipeline.run(tmp_media)
        except Exception as error:
            result["error"] = error

    thread = threading.Thread(target=run_pipeline)
    thread.start()
    assert first_finished.wait(timeout=2)
    assert all(event.wait(timeout=2) for event in entered.values())
    pipeline.cancel()
    release_in_flight.set()
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert "error" not in result
    return {
        "report": result["report"],
        "pipeline": pipeline,
        "client": client,
        "callbacks": callbacks,
        "workspace": fake_workspace,
        "initial_call_count": len(client.calls),
    }


def test_cancelled_run_marks_unstarted_spans_as_failed(cancelled_pipeline):
    report = cancelled_pipeline["report"]
    client = cancelled_pipeline["client"]
    assert report.cancelled is True
    assert set(report.results) == {0}
    assert set(report.failures) == {1, 2, 3, 4}
    assert all(isinstance(error, CancelledError) for error in report.failures.values())
    assert {call[0] for call in client.calls} == {0, 1, 2, 3}
    assert len(client.calls) == 4
    assert client.interrupted.is_set()
    assert client.close_calls == 1
    assert cancelled_pipeline["workspace"].cleanup_calls == 1
    assert not cancelled_pipeline["workspace"].path.exists()
    assert cancelled_pipeline["callbacks"].events[-1] == ("cancelled", True)


def test_cancelled_spans_retry_with_the_same_open_client(cancelled_pipeline):
    client = cancelled_pipeline["client"]
    with pytest.warns(UserWarning, match="may incur another charge"):
        retried = cancelled_pipeline["pipeline"].retry_failed()
    assert client.closed is False
    assert client.reopen_calls == 1
    assert set(call[0] for call in client.calls[cancelled_pipeline["initial_call_count"]:]) == {
        1, 2, 3, 4,
    }
    assert set(retried.results) == {0, 1, 2, 3, 4}
    assert retried.failures == {}


def test_successful_retry_clears_cancelled_state_and_publishes_finished(
    cancelled_pipeline,
):
    with pytest.warns(UserWarning, match="may incur another charge"):
        retried = cancelled_pipeline["pipeline"].retry_failed()
    assert retried.cancelled is False
    assert cancelled_pipeline["callbacks"].events[-1] == ("finished", True)
    assert ("cancelled", True) in cancelled_pipeline["callbacks"].events


def test_cancel_during_backoff_stops_before_another_request(
    tmp_media, fake_media, fake_workspace
):
    attempts = 0
    pipeline_box = []
    sleeps = []

    def handler(index, attempt, path):
        nonlocal attempts
        attempts += 1
        raise RateLimitError("limited", retry_after=10)

    def sleep(delay):
        sleeps.append(delay)
        pipeline_box[0].cancel()

    client = FakeClient(handler)
    pipeline = TranscriptionPipeline(
        client, model="approved-model", workspace=fake_workspace, sleep_fn=sleep,
    )
    pipeline_box.append(pipeline)
    report = pipeline.run(tmp_media)
    assert report.cancelled
    assert attempts == 1
    assert sleeps == [10]
    assert client.close_calls == 1


def test_retry_failed_resubmits_only_failed_indices_and_warns_about_cost(
    tmp_media, fake_media, fake_workspace
):
    fake_media["duration"] = 70.0

    def handler(index, attempt, path):
        if index == 1 and attempt == 1:
            raise AudioPreparationError("chunk extraction failed")
        return response(f"chunk {index}")

    client = FakeClient(handler)
    pipeline = TranscriptionPipeline(
        client, model="approved-model", workspace=fake_workspace,
        sleep_fn=lambda delay: None,
    )
    first_report = pipeline.run(tmp_media)
    assert set(first_report.results) == {0, 2}
    assert set(first_report.failures) == {1}
    with pytest.warns(UserWarning, match="may incur another charge"):
        retried = pipeline.retry_failed()
    assert {call[0] for call in client.calls[:3]} == {0, 1, 2}
    assert [call[0] for call in client.calls[3:]] == [1]
    assert set(retried.results) == {0, 1, 2}
    assert retried.failures == {}
    assert retried.is_complete


def test_failed_new_run_cannot_reuse_stale_retry_state(
    tmp_media, fake_media, fake_workspace, monkeypatch
):
    client = FakeClient(lambda index, attempt, path: (_ for _ in ()).throw(
        AudioPreparationError("chunk failed")
    ))
    pipeline = TranscriptionPipeline(
        client, model="approved-model", workspace=fake_workspace,
        sleep_fn=lambda delay: None,
    )
    pipeline.run(tmp_media)
    monkeypatch.setattr(
        "audio_transcriber.pipeline.probe",
        lambda source, *, ffprobe=None: (_ for _ in ()).throw(NoAudioStreamError()),
    )
    with pytest.raises(NoAudioStreamError):
        pipeline.run(tmp_media)
    with pytest.raises(RuntimeError, match=r"run\(\)"):
        pipeline.retry_failed()
