"""Concurrent orchestration for preparing and transcribing audio chunks."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
import threading
import time
from typing import Callable, NamedTuple
import warnings

from . import constants
from .audio import detect_quiet_midpoints, extract_chunk, probe
from .chunking import ChunkSpan, plan_chunks
from .errors import CancelledError, RateLimitError, TranscriberError
from .openrouter_client import OpenRouterClient, TranscriptionResponse, Usage
from .transcript import TranscriptAssembler
from .workdir import AudioWorkspace


class ChunkOutcome(NamedTuple):
    index: int
    text: str
    usage: Usage | None
    generation_id: str | None


class PipelineCallbacks:
    """Optional lifecycle notifications; override only the events you use."""

    def on_analyzing(self) -> None:
        pass

    def on_planned(self, total: int) -> None:
        pass

    def on_chunk_started(self, index: int, total: int) -> None:
        pass

    def on_chunk_finished(self, outcome: ChunkOutcome) -> None:
        pass

    def on_chunk_failed(self, index: int, error: TranscriberError) -> None:
        pass

    def on_finished(self, report: TranscriptionReport) -> None:
        pass

    def on_cancelled(self, report: TranscriptionReport) -> None:
        pass


@dataclass
class TranscriptionReport:
    results: dict[int, ChunkOutcome]
    failures: dict[int, TranscriberError]
    total_chunks: int
    cancelled: bool = False

    @property
    def is_complete(self) -> bool:
        return (
            not self.cancelled
            and not self.failures
            and set(self.results) == set(range(self.total_chunks))
        )

    def transcript(self) -> str:
        assembler = TranscriptAssembler()
        for index in sorted(self.results):
            assembler.add(index, self.results[index].text)
        return assembler.text()

    def total_cost(self) -> float | None:
        if not self.is_complete or not self.results:
            return None
        costs = [outcome.usage.cost for outcome in self.results.values() if outcome.usage]
        if len(costs) != len(self.results) or any(cost is None for cost in costs):
            return None
        return sum(cost for cost in costs if cost is not None)

    def total_seconds(self) -> float | None:
        if not self.is_complete or not self.results:
            return None
        seconds = [outcome.usage.seconds for outcome in self.results.values() if outcome.usage]
        if len(seconds) != len(self.results) or any(value is None for value in seconds):
            return None
        return sum(value for value in seconds if value is not None)

    def cost_note(self) -> str:
        total = self.total_cost()
        if total is None:
            return "Cost unavailable: OpenRouter did not report a cost for every chunk."
        return f"Total cost reported by OpenRouter: ${total:.4f}"


class TranscriptionPipeline:
    def __init__(
        self,
        client: OpenRouterClient,
        *,
        model: str,
        callbacks: PipelineCallbacks | None = None,
        ffmpeg: Path | None = None,
        ffprobe: Path | None = None,
        workspace: AudioWorkspace | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        self.client = client
        self.model = model
        self.callbacks = callbacks if callbacks is not None else PipelineCallbacks()
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.sleep_fn = sleep_fn

        self._cancel_event = threading.Event()
        self._workspace_template = workspace
        self._workspace_root = getattr(workspace, "_root", None)
        self._workspace_used = False
        self._spans: tuple[ChunkSpan, ...] = ()
        self._source: Path | None = None
        self._language: str | None = None
        self._last_report: TranscriptionReport | None = None

    def cancel(self) -> None:
        """Stop new work without taking ownership of the injected client's lifecycle."""
        self._cancel_event.set()

    def run(self, source: Path, *, language: str | None = None) -> TranscriptionReport:
        self._cancel_event.clear()
        self._last_report = None
        self._spans = ()
        self._source = Path(source)
        self._language = language
        workspace = self._next_workspace()
        report: TranscriptionReport
        try:
            self.callbacks.on_analyzing()
            media = probe(self._source, ffprobe=self.ffprobe)
            quiet = detect_quiet_midpoints(
                self._source,
                noise_db=constants.SILENCE_NOISE_DB,
                min_duration=constants.SILENCE_MIN_DURATION,
                ffmpeg=self.ffmpeg,
            )
            self._spans = tuple(plan_chunks(media.duration, quiet))
            self.callbacks.on_planned(len(self._spans))
            report = self._transcribe_spans(
                self._spans,
                workspace=workspace,
                total_chunks=len(self._spans),
            )
        finally:
            workspace.cleanup()

        self._last_report = report
        self._publish(report)
        return report

    def retry_failed(self) -> TranscriptionReport:
        previous = self._last_report
        if previous is None or self._source is None:
            raise RuntimeError("run() must complete before failed chunks can be retried")

        failed_spans = tuple(span for span in self._spans if span.index in previous.failures)
        if not failed_spans:
            report = TranscriptionReport(
                dict(previous.results), dict(previous.failures), previous.total_chunks,
                previous.cancelled,
            )
            self._last_report = report
            return report

        warnings.warn(
            "Retrying failed chunks may incur another charge.",
            UserWarning,
            stacklevel=2,
        )
        self._cancel_event.clear()
        workspace = self._next_workspace()
        try:
            report = self._transcribe_spans(
                failed_spans,
                workspace=workspace,
                total_chunks=previous.total_chunks,
                results=dict(previous.results),
                failures=dict(previous.failures),
            )
        finally:
            workspace.cleanup()

        self._last_report = report
        self._publish(report)
        return report

    def _next_workspace(self) -> AudioWorkspace:
        if self._workspace_template is not None and not self._workspace_used:
            self._workspace_used = True
            return self._workspace_template
        return AudioWorkspace(root=self._workspace_root)

    def _transcribe_spans(
        self,
        spans: tuple[ChunkSpan, ...],
        *,
        workspace: AudioWorkspace,
        total_chunks: int,
        results: dict[int, ChunkOutcome] | None = None,
        failures: dict[int, TranscriberError] | None = None,
    ) -> TranscriptionReport:
        outcomes = {} if results is None else results
        errors = {} if failures is None else failures
        pending: dict[Future, ChunkSpan] = {}
        remaining = iter(spans)

        with ThreadPoolExecutor(max_workers=constants.MAX_CONCURRENT_REQUESTS) as executor:
            while len(pending) < constants.MAX_CONCURRENT_REQUESTS and not self._cancel_event.is_set():
                try:
                    span = next(remaining)
                except StopIteration:
                    break
                pending[executor.submit(self._transcribe_one, span, total_chunks, workspace)] = span

            while pending:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    span = pending.pop(future)
                    outcome, error = future.result()
                    if outcome is not None:
                        outcomes[span.index] = outcome
                        errors.pop(span.index, None)
                        self.callbacks.on_chunk_finished(outcome)
                    elif error is not None:
                        errors[span.index] = error
                        self.callbacks.on_chunk_failed(span.index, error)

                while (
                    len(pending) < constants.MAX_CONCURRENT_REQUESTS
                    and not self._cancel_event.is_set()
                ):
                    try:
                        span = next(remaining)
                    except StopIteration:
                        break
                    pending[executor.submit(self._transcribe_one, span, total_chunks, workspace)] = span

        cancelled = self._cancel_event.is_set()
        if cancelled:
            for span in spans:
                if span.index not in outcomes and span.index not in errors:
                    error = CancelledError()
                    errors[span.index] = error
                    self.callbacks.on_chunk_failed(span.index, error)

        return TranscriptionReport(
            outcomes,
            errors,
            total_chunks,
            cancelled=cancelled,
        )

    def _transcribe_one(
        self,
        span: ChunkSpan,
        total_chunks: int,
        workspace: AudioWorkspace,
    ) -> tuple[ChunkOutcome | None, TranscriberError | None]:
        if self._cancel_event.is_set():
            return None, None

        self.callbacks.on_chunk_started(span.index, total_chunks)
        chunk_path: Path | None = None
        try:
            chunk_path = workspace.chunk_path(span.index)
            audio_path = extract_chunk(
                self._source,
                span.start,
                span.duration,
                chunk_path,
                ffmpeg=self.ffmpeg,
            )
            if self._cancel_event.is_set():
                return None, None
            response = self._transcribe_with_rate_limit_retry(audio_path)
            return ChunkOutcome(
                span.index,
                response.text,
                response.usage,
                response.generation_id,
            ), None
        except TranscriberError as error:
            return None, error
        except Exception:
            if self._cancel_event.is_set():
                return None, CancelledError()
            return None, TranscriberError("The chunk could not be transcribed.")
        finally:
            if chunk_path is not None:
                try:
                    chunk_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _transcribe_with_rate_limit_retry(self, audio_path: Path) -> TranscriptionResponse:
        retry = 0
        while True:
            if self._cancel_event.is_set():
                raise CancelledError()
            try:
                return self.client.transcribe(audio_path, self.model, self._language)
            except RateLimitError as error:
                if retry >= constants.MAX_RATE_LIMIT_RETRIES:
                    raise
                delay = (
                    error.retry_after
                    if error.retry_after is not None
                    else constants.RETRY_BASE_DELAY_SECONDS * (2 ** retry)
                )
                delay = max(0.0, delay)
                if self._cancel_event.is_set():
                    raise CancelledError() from None
                if self.sleep_fn is time.sleep:
                    cancelled = self._cancel_event.wait(delay)
                else:
                    self.sleep_fn(delay)
                    cancelled = self._cancel_event.is_set()
                if cancelled:
                    raise CancelledError() from None
                retry += 1

    def _publish(self, report: TranscriptionReport) -> None:
        if report.cancelled:
            self.callbacks.on_cancelled(report)
        else:
            self.callbacks.on_finished(report)


__all__ = [
    "ChunkOutcome",
    "PipelineCallbacks",
    "TranscriptionPipeline",
    "TranscriptionReport",
]
