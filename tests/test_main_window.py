from __future__ import annotations

import sys
import threading
import types
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
)

from audio_transcriber import constants
from audio_transcriber.errors import CancelledError, TranscriberError
from audio_transcriber.openrouter_client import Usage
from audio_transcriber.pipeline import ChunkOutcome, TranscriptionReport
from audio_transcriber.ui.main_window import MainWindow
from audio_transcriber.ui.settings import AppSettings


class FakeStore:
    def __init__(self, key: str | None = "test-api-key"):
        self.key = key

    def load(self) -> str | None:
        return self.key

    def save(self, key: str) -> None:
        self.key = key

    def forget(self) -> None:
        self.key = None


class FakeClient:
    def __init__(self, models: list[str] | None = None):
        self.models = models if models is not None else [constants.ALLOWED_MODELS[0]]

    def list_available_models(self) -> list[str]:
        return list(self.models)


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings("AudioTranscriber", "AudioTranscriber").clear()
    yield
    QSettings("AudioTranscriber", "AudioTranscriber").clear()


def _window(qtbot, **kwargs) -> MainWindow:
    window = MainWindow(store=FakeStore(), client=FakeClient(), **kwargs)
    qtbot.addWidget(window)
    window.show()
    _wait_for_discovery(qtbot, window)
    return window


def _wait_for_discovery(qtbot, window: MainWindow) -> None:
    qtbot.waitUntil(lambda: not getattr(window, "_model_loading", True), timeout=5000)


def _choose_file(window: MainWindow, monkeypatch, path: Path) -> None:
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(path), ""))
    window.select_file()


def _acknowledge(window: MainWindow) -> None:
    window.zdr_acknowledgement.setChecked(True)


def _response(text: str) -> ChunkOutcome:
    return ChunkOutcome(0, text, Usage(1.0, 2, 1, 1, 0.002), "generation-id")


class CompletingPipeline:
    def __init__(self, callbacks):
        self.callbacks = callbacks
        self.thread_id = None
        self.language = "not run"

    def run(self, source, *, language=None):
        self.thread_id = threading.get_ident()
        self.language = language
        self.callbacks.on_analyzing()
        self.callbacks.on_planned(3)
        outcomes = {}
        for index, text in enumerate(("first", "second", "third")):
            outcome = ChunkOutcome(index, text, Usage(1.0, 2, 1, 1, 0.002), "generation-id")
            outcomes[index] = outcome
            self.callbacks.on_chunk_finished(outcome)
        report = TranscriptionReport(outcomes, {}, 3)
        self.callbacks.on_finished(report)
        return report

    def cancel(self):
        pass

    def retry_failed(self):
        raise AssertionError("A complete report has no failed chunks to retry")


@pytest.fixture
def completing_pipeline_factory():
    pipelines = []
    created = threading.Event()

    def factory(*, model, callbacks):
        assert model == constants.ALLOWED_MODELS[0]
        pipeline = CompletingPipeline(callbacks)
        pipelines.append(pipeline)
        created.set()
        return pipeline

    factory.pipelines = pipelines
    factory.created = created
    return factory


class BlockingPipeline:
    def __init__(self, callbacks):
        self.callbacks = callbacks
        self.started = threading.Event()
        self.cancelled = threading.Event()
        self.retry_thread_id = None

    def run(self, source, *, language=None):
        self.callbacks.on_planned(2)
        self.callbacks.on_chunk_finished(_response("partial transcript"))
        self.started.set()
        self.cancelled.wait(5)
        report = TranscriptionReport(
            {0: _response("partial transcript")},
            {1: CancelledError()},
            2,
            cancelled=True,
        )
        self.callbacks.on_cancelled(report)
        return report

    def cancel(self):
        self.cancelled.set()

    def retry_failed(self):
        self.retry_thread_id = threading.get_ident()
        report = TranscriptionReport(
            {0: _response("partial transcript"), 1: _response("retried")}, {}, 2
        )
        self.callbacks.on_finished(report)
        return report


class PartialPipeline:
    def __init__(self, callbacks):
        self.callbacks = callbacks

    def run(self, source, *, language=None):
        self.callbacks.on_planned(2)
        outcome = _response("partial result")
        failure = TranscriberError()
        self.callbacks.on_chunk_finished(outcome)
        self.callbacks.on_chunk_failed(1, failure)
        report = TranscriptionReport({0: outcome}, {1: failure}, 2)
        self.callbacks.on_finished(report)
        return report

    def cancel(self):
        pass

    def retry_failed(self):
        raise AssertionError("This partial-pipeline fixture has no retry behavior")


@pytest.fixture
def blocking_pipeline_factory():
    pipelines = []
    created = threading.Event()

    def factory(*, model, callbacks):
        pipeline = BlockingPipeline(callbacks)
        pipelines.append(pipeline)
        created.set()
        return pipeline

    factory.pipelines = pipelines
    factory.created = created
    return factory


@pytest.fixture
def partial_pipeline_factory():
    def factory(*, model, callbacks):
        return PartialPipeline(callbacks)

    return factory


@pytest.fixture
def repeat_pipeline_factory():
    pipelines = []

    def factory(*, model, callbacks):
        pipeline_type = CompletingPipeline if not pipelines else BlockingPipeline
        pipeline = pipeline_type(callbacks)
        pipelines.append(pipeline)
        return pipeline

    factory.pipelines = pipelines
    return factory


def test_zdr_disclaimer_is_visible_verbatim_and_stays_read_only(qtbot):
    window = _window(qtbot)

    labels = [label.text() for label in window.findChildren(QLabel)]

    assert constants.ZDR_WARNING in labels
    assert window.zdr_warning_label.isVisible()
    assert window.zdr_warning_label.isEnabled()
    assert window.file_edit.objectName() == "file_edit"
    assert window.file_edit.isReadOnly()
    assert window.transcript_edit.objectName() == "transcript_edit"
    assert window.transcript_edit.isReadOnly()


def test_transcription_is_blocked_until_acknowledgement_and_file(qtbot, monkeypatch, tmp_path):
    starts = []
    window = _window(qtbot, pipeline_factory=lambda **kwargs: starts.append(kwargs))
    audio = tmp_path / "recording.wav"
    audio.write_bytes(b"audio")
    _choose_file(window, monkeypatch, audio)

    assert not window.transcribe_button.isEnabled()
    window._start_transcription()
    assert starts == []

    _acknowledge(window)
    assert window.transcribe_button.isEnabled()
    assert AppSettings().zdr_acknowledged is True
    window.file_edit.clear()
    assert not window.transcribe_button.isEnabled()
    window._start_transcription()
    assert starts == []


def test_model_combo_contains_only_available_allowlisted_models(qtbot):
    client = FakeClient(["unapproved/model", "openai/whisper-large-v3"])
    window = MainWindow(store=FakeStore(), client=client)
    qtbot.addWidget(window)
    _wait_for_discovery(qtbot, window)

    assert window.available_models() == ["openai/whisper-large-v3"]
    assert [window.model_combo.itemText(i) for i in range(window.model_combo.count())] == [
        "openai/whisper-large-v3"
    ]


def test_no_approved_model_disables_transcription_without_a_fallback(qtbot):
    window = MainWindow(store=FakeStore(), client=FakeClient([]))
    qtbot.addWidget(window)
    _wait_for_discovery(qtbot, window)

    assert window.available_models() == []
    assert window.model_combo.count() == 0
    assert not window.transcribe_button.isEnabled()
    assert "no approved" in window.status_label.text().lower()
    window.show()
    assert window.zdr_warning_label.isVisible()


def test_model_discovery_runs_in_background_while_the_window_remains_responsive(qtbot):
    entered = threading.Event()
    release = threading.Event()
    timer_fired = threading.Event()
    discovery_thread_ids = []

    class BlockingDiscoveryClient(FakeClient):
        def list_available_models(self):
            discovery_thread_ids.append(threading.get_ident())
            entered.set()
            release.wait(timeout=5)
            return list(self.models)

    gui_thread_id = threading.get_ident()
    window = MainWindow(store=FakeStore(), client=BlockingDiscoveryClient())
    qtbot.addWidget(window)
    window.show()
    QTimer.singleShot(10, timer_fired.set)

    try:
        qtbot.waitUntil(entered.is_set, timeout=2000)
        qtbot.waitUntil(timer_fired.is_set, timeout=1000)
        assert window._model_loading
        assert "checking" in window.status_label.text().lower()
        assert discovery_thread_ids and discovery_thread_ids[0] != gui_thread_id
    finally:
        release.set()
    _wait_for_discovery(qtbot, window)
    assert window.available_models() == [constants.ALLOWED_MODELS[0]]


def test_pipeline_runs_off_gui_thread_and_updates_progress_transcript_and_cost(
    qtbot, monkeypatch, tmp_path, completing_pipeline_factory
):
    window = _window(qtbot, pipeline_factory=completing_pipeline_factory)
    audio = tmp_path / "recording.wav"
    audio.write_bytes(b"audio")
    _choose_file(window, monkeypatch, audio)
    _acknowledge(window)

    gui_thread = threading.get_ident()
    window._start_transcription()
    qtbot.waitUntil(completing_pipeline_factory.created.is_set, timeout=5000)
    qtbot.waitUntil(lambda: window.progress_bar.value() == 3, timeout=5000)
    qtbot.waitUntil(lambda: bool(window.transcript_edit.toPlainText()), timeout=5000)

    assert completing_pipeline_factory.pipelines[0].thread_id != gui_thread
    assert completing_pipeline_factory.pipelines[0].language is None
    assert window.transcript_edit.toPlainText() == "first second third"
    assert window.cost_label.text() == "Total cost reported by OpenRouter: $0.0060"
    assert window.copy_button.isEnabled()
    assert window.save_button.isEnabled()


def test_language_combo_passes_the_selected_iso_code_to_the_pipeline(
    qtbot, monkeypatch, tmp_path, completing_pipeline_factory
):
    window = _window(qtbot, pipeline_factory=completing_pipeline_factory)
    audio = tmp_path / "recording.wav"
    audio.write_bytes(b"audio")
    _choose_file(window, monkeypatch, audio)
    _acknowledge(window)

    index = window.language_combo.findText("Japanese")
    assert index >= 0
    window.language_combo.setCurrentIndex(index)
    assert window.language_combo.currentData() == "ja"
    window._start_transcription()
    qtbot.waitUntil(lambda: bool(window.transcript_edit.toPlainText()), timeout=5000)

    assert completing_pipeline_factory.pipelines[0].language == "ja"


def test_default_pipeline_factory_creates_a_fresh_client_per_run(
    qtbot, monkeypatch, tmp_path
):
    from audio_transcriber.ui import main_window

    clients = []

    class RunClient:
        def __init__(self, key):
            self.key = key
            self.close_calls = 0
            clients.append(self)

        def close(self):
            self.close_calls += 1

    def make_pipeline(client, *, model, callbacks):
        pipeline = CompletingPipeline(callbacks)
        pipeline.client = client
        return pipeline

    monkeypatch.setattr(main_window, "OpenRouterClient", RunClient)
    monkeypatch.setattr(main_window, "TranscriptionPipeline", make_pipeline)
    window = _window(qtbot)
    audio = tmp_path / "recording.wav"
    audio.write_bytes(b"audio")
    _choose_file(window, monkeypatch, audio)
    _acknowledge(window)

    window._start_transcription()
    qtbot.waitUntil(lambda: bool(window.transcript_edit.toPlainText()), timeout=5000)
    window._start_transcription()
    qtbot.waitUntil(lambda: len(clients) == 2, timeout=5000)
    qtbot.waitUntil(lambda: bool(window.transcript_edit.toPlainText()), timeout=5000)

    assert [client.key for client in clients] == ["test-api-key", "test-api-key"]
    assert all(client.close_calls == 1 for client in clients)


def test_copy_and_save_disable_when_a_new_run_clears_the_old_transcript(
    qtbot, monkeypatch, tmp_path, repeat_pipeline_factory
):
    window = _window(qtbot, pipeline_factory=repeat_pipeline_factory)
    audio = tmp_path / "recording.wav"
    audio.write_bytes(b"audio")
    _choose_file(window, monkeypatch, audio)
    _acknowledge(window)

    window._start_transcription()
    qtbot.waitUntil(lambda: len(repeat_pipeline_factory.pipelines) == 1, timeout=5000)
    qtbot.waitUntil(
        lambda: window.transcript_edit.toPlainText() == "first second third", timeout=5000
    )
    assert window.copy_button.isEnabled()
    assert window.save_button.isEnabled()

    try:
        window._start_transcription()
        qtbot.waitUntil(lambda: len(repeat_pipeline_factory.pipelines) == 2, timeout=5000)
        assert window.transcript_edit.toPlainText() == ""
        assert not window.copy_button.isEnabled()
        assert not window.save_button.isEnabled()
    finally:
        if window._worker is not None:
            window._worker.cancel()
            qtbot.waitUntil(lambda: not window._running, timeout=5000)
            window._worker.wait_for_threads()


def test_cancel_keeps_partial_transcript_and_enables_retry(
    qtbot, monkeypatch, tmp_path, blocking_pipeline_factory
):
    window = _window(qtbot, pipeline_factory=blocking_pipeline_factory)
    audio = tmp_path / "recording.wav"
    audio.write_bytes(b"audio")
    _choose_file(window, monkeypatch, audio)
    _acknowledge(window)

    window._start_transcription()
    qtbot.waitUntil(blocking_pipeline_factory.created.is_set, timeout=5000)
    pipeline = blocking_pipeline_factory.pipelines[0]
    qtbot.waitUntil(pipeline.started.is_set, timeout=5000)
    window.cancel_button.click()
    qtbot.waitUntil(lambda: window.retry_button.isEnabled(), timeout=5000)

    assert window.transcript_edit.toPlainText() == "partial transcript"
    assert window.progress_bar.value() == 1
    assert "may still have been billed" in window.status_label.text().lower()

    gui_thread = threading.get_ident()
    window.retry_button.click()
    qtbot.waitUntil(lambda: "retried" in window.transcript_edit.toPlainText(), timeout=5000)
    assert pipeline.retry_thread_id != gui_thread
    assert window.progress_bar.value() == 2
    assert not window.retry_button.isEnabled()


def test_cancelled_progress_counts_finished_chunks_not_cancelled_work(qtbot):
    window = _window(qtbot)
    report = TranscriptionReport(
        {0: _response("successful")},
        {1: TranscriberError(), 2: CancelledError()},
        3,
        cancelled=True,
    )

    window._show_report(report, cancelled=True)

    assert window.progress_bar.value() == 2


def test_partial_finished_report_shows_failure_count_and_keeps_transcript(
    qtbot, monkeypatch, tmp_path, partial_pipeline_factory
):
    window = _window(qtbot, pipeline_factory=partial_pipeline_factory)
    audio = tmp_path / "recording.wav"
    audio.write_bytes(b"audio")
    _choose_file(window, monkeypatch, audio)
    _acknowledge(window)

    window._start_transcription()
    qtbot.waitUntil(lambda: "partial" in window.status_label.text().lower(), timeout=5000)

    assert window.transcript_edit.toPlainText() == "partial result"
    assert window.progress_bar.value() == 2
    assert "1 failed" in window.status_label.text().lower()
    assert window.retry_button.isEnabled()
    assert window.copy_button.isEnabled()
    assert window.save_button.isEnabled()


def test_pipeline_start_error_stops_indeterminate_progress(qtbot, monkeypatch, tmp_path):
    def failed_factory(**kwargs):
        raise RuntimeError("sensitive details are not shown")

    window = _window(qtbot, pipeline_factory=failed_factory)
    audio = tmp_path / "recording.wav"
    audio.write_bytes(b"audio")
    _choose_file(window, monkeypatch, audio)
    _acknowledge(window)

    window._start_transcription()
    qtbot.waitUntil(
        lambda: window.status_label.text() == "The transcription could not be completed.",
        timeout=5000,
    )

    assert window.progress_bar.maximum() == 1
    assert window.progress_bar.value() == 0


def test_closing_during_transcription_cancels_before_destroying_the_window(
    qtbot, monkeypatch, tmp_path, blocking_pipeline_factory
):
    window = _window(qtbot, pipeline_factory=blocking_pipeline_factory)
    audio = tmp_path / "recording.wav"
    audio.write_bytes(b"audio")
    _choose_file(window, monkeypatch, audio)
    _acknowledge(window)
    window._start_transcription()
    qtbot.waitUntil(blocking_pipeline_factory.created.is_set, timeout=5000)
    pipeline = blocking_pipeline_factory.pipelines[0]
    qtbot.waitUntil(pipeline.started.is_set, timeout=5000)

    try:
        window.close()
        assert window.isVisible()
        qtbot.waitUntil(lambda: not window.isVisible(), timeout=5000)
    finally:
        if window._worker is not None:
            window._worker.cancel()
            for thread in window._worker._threads:
                thread.wait(5000)


def test_api_key_is_never_shown_in_main_window(qtbot):
    secret = "sk-or-v1-private-key"
    window = MainWindow(store=FakeStore(secret), client=FakeClient())
    qtbot.addWidget(window)
    _wait_for_discovery(qtbot, window)

    displayed = [label.text() for label in window.findChildren(QLabel)]
    displayed.extend(edit.text() for edit in window.findChildren(QLineEdit))
    displayed.append(window.transcript_edit.toPlainText())

    assert all(secret not in value for value in displayed)


def _schedule_key_dialog_action(action: str, secret: str | None = None) -> None:
    def interact_with_dialog():
        dialog = QApplication.activeModalWidget()
        assert dialog is not None
        if action == "replace":
            field = dialog.findChild(QLineEdit, "api_key_edit")
            assert field is not None
            field.setText(secret or "")
            next(button for button in dialog.findChildren(QPushButton)
                 if button.text() == "Save").click()
        else:
            next(button for button in dialog.findChildren(QPushButton)
                 if button.text() == "Forget key").click()
            QTimer.singleShot(0, dialog.reject)

    QTimer.singleShot(0, interact_with_dialog)


def test_reachable_key_settings_replace_forget_reset_ack_and_rediscover(
    qtbot, monkeypatch
):
    from audio_transcriber.ui import main_window

    store = FakeStore("old-key")
    created_clients = []

    class KeyClient(FakeClient):
        def __init__(self, key):
            super().__init__([constants.ALLOWED_MODELS[1]])
            self.key = key
            created_clients.append(self)

    monkeypatch.setattr(main_window, "OpenRouterClient", KeyClient)
    window = MainWindow(store=store, client=FakeClient())
    qtbot.addWidget(window)
    _wait_for_discovery(qtbot, window)
    _acknowledge(window)
    replacement = "sk-or-v1-replacement-secret"

    _schedule_key_dialog_action("replace", replacement)
    window.key_settings_button.click()
    qtbot.waitUntil(lambda: not window._model_loading, timeout=5000)

    assert store.key == replacement
    assert window._api_key == replacement
    assert AppSettings().zdr_acknowledged is False
    assert not window.zdr_acknowledgement.isChecked()
    assert created_clients[-1].key == replacement
    assert window.available_models() == [constants.ALLOWED_MODELS[1]]
    displayed = [widget.text() for widget in window.findChildren(QLabel)]
    displayed.extend(widget.text() for widget in window.findChildren(QLineEdit))
    assert all(replacement not in value for value in displayed)

    _schedule_key_dialog_action("forget")
    window.key_settings_button.click()

    assert store.key is None
    assert window._api_key is None
    assert window.available_models() == []
    assert AppSettings().zdr_acknowledged is False


def test_copy_action_copies_only_the_current_transcript(qtbot):
    window = _window(qtbot)
    window.transcript_edit.setPlainText("current transcript")
    window.copy_button.setEnabled(True)

    window.copy_button.click()

    assert QApplication.clipboard().text() == "current transcript"


def test_save_as_writes_the_current_transcript_as_utf8(qtbot, monkeypatch, tmp_path):
    window = _window(qtbot)
    window.transcript_edit.setPlainText("café transcription")
    window.save_button.setEnabled(True)
    destination = tmp_path / "transcript.txt"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(destination), ""),
    )

    window.save_button.click()

    assert destination.read_bytes() == "café transcription".encode("utf-8")


def test_save_as_refuses_to_overwrite_without_confirmation(qtbot, monkeypatch, tmp_path):
    window = _window(qtbot)
    window.transcript_edit.setPlainText("new text")
    window.save_button.setEnabled(True)
    destination = tmp_path / "transcript.txt"
    destination.write_text("original", encoding="utf-8")
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(destination), ""),
    )
    prompts = []

    def decline_overwrite(*args, **kwargs):
        prompts.append(args)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", decline_overwrite)

    window.save_button.click()

    assert len(prompts) == 1
    assert destination.read_text(encoding="utf-8") == "original"


def test_main_self_test_dispatch_does_not_start_the_gui(monkeypatch):
    from audio_transcriber import __main__ as entrypoint
    from audio_transcriber.ui import app as app_module
    from audio_transcriber.ui import main_window as window_module

    calls = []
    fake_selftest = types.SimpleNamespace(run_self_test=lambda: calls.append("self-test") or 7)
    monkeypatch.setitem(sys.modules, "audio_transcriber.selftest", fake_selftest)
    monkeypatch.setattr(app_module, "build_application", lambda argv: pytest.fail("GUI started"))
    monkeypatch.setattr(window_module, "MainWindow", lambda: pytest.fail("window constructed"))

    assert entrypoint.main(["audio-transcriber", "--self-test"]) == 7
    assert calls == ["self-test"]


def test_normal_startup_cleans_stale_workspaces_before_constructing_the_window(monkeypatch):
    from audio_transcriber import __main__ as entrypoint
    from audio_transcriber.ui import app as app_module
    from audio_transcriber.ui import main_window as window_module

    events = []

    class FakeApplication:
        def exec(self):
            events.append("exec")
            return 0

    class FakeWindow:
        def show(self):
            events.append("show")

    monkeypatch.setattr(entrypoint, "cleanup_stale_workspaces", lambda: events.append("cleanup"))
    monkeypatch.setattr(app_module, "build_application", lambda argv: FakeApplication())
    monkeypatch.setattr(window_module, "MainWindow", FakeWindow)

    assert entrypoint.main([]) == 0
    assert events == ["cleanup", "show", "exec"]


def test_startup_cancelled_when_no_saved_key_and_key_dialog_is_rejected(qtbot, monkeypatch):
    from audio_transcriber.ui import main_window

    class RejectedDialog:
        def __init__(self, store, parent):
            pass

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(main_window, "KeyDialog", RejectedDialog)
    window = MainWindow(store=FakeStore(None), client=FakeClient())
    qtbot.addWidget(window)

    assert window._startup_cancelled
    assert window.model_combo.count() == 0


def test_headless_application_sets_offscreen_only_when_requested(qtbot, monkeypatch):
    from audio_transcriber.ui.app import build_application

    monkeypatch.setenv("AUDIO_TRANSCRIBER_HEADLESS", "1")
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.delenv("QT_ENABLE_HIGHDPI_SCALING", raising=False)
    app = build_application(["audio-transcriber"])

    assert app.applicationName() == "Windows Audio Transcriber"
    assert app.organizationName() == "AudioTranscriber"
    assert __import__("os").environ["QT_QPA_PLATFORM"] == "offscreen"
    assert __import__("os").environ["QT_ENABLE_HIGHDPI_SCALING"] == "1"


def test_normal_application_preserves_platform_override(qtbot, monkeypatch):
    from audio_transcriber.ui.app import build_application

    monkeypatch.delenv("AUDIO_TRANSCRIBER_HEADLESS", raising=False)
    monkeypatch.setenv("QT_QPA_PLATFORM", "test-platform")

    build_application(["audio-transcriber"])

    assert __import__("os").environ["QT_QPA_PLATFORM"] == "test-platform"


def test_main_shows_window_and_returns_qt_event_loop_result(monkeypatch):
    from audio_transcriber import __main__ as entrypoint
    from audio_transcriber.ui import app as app_module
    from audio_transcriber.ui import main_window as window_module

    events = []

    class FakeApplication:
        def exec(self):
            events.append("exec")
            return 23

    class FakeWindow:
        def __init__(self):
            events.append("construct")

        def show(self):
            events.append("show")

    monkeypatch.setattr(app_module, "build_application", lambda argv: FakeApplication())
    monkeypatch.setattr(window_module, "MainWindow", FakeWindow)

    monkeypatch.setattr(entrypoint, "cleanup_stale_workspaces", lambda: None)
    assert entrypoint.main([]) == 23
    assert events == ["construct", "show", "exec"]
