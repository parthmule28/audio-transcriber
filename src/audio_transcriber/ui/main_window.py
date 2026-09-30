"""Main window and worker-thread wiring for audio transcription."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from audio_transcriber import constants
from audio_transcriber.credentials import CredentialStore
from audio_transcriber.errors import NoApprovedModelAvailable, TranscriberError
from audio_transcriber.openrouter_client import OpenRouterClient
from audio_transcriber.pipeline import (
    ChunkOutcome,
    PipelineCallbacks,
    TranscriptionPipeline,
    TranscriptionReport,
)
from audio_transcriber.ui.key_dialog import KeyDialog
from audio_transcriber.ui.settings import AppSettings


PipelineFactory = Callable[..., TranscriptionPipeline]


class _WorkerCallbacks(PipelineCallbacks):
    """Translate pipeline callbacks into thread-safe Qt signal emissions."""

    def __init__(self, worker: PipelineWorker) -> None:
        self._worker = worker

    def on_analyzing(self) -> None:
        self._worker._cancel_if_requested()
        self._worker.analyzing.emit()

    def on_planned(self, total: int) -> None:
        self._worker.planned.emit(total)

    def on_chunk_finished(self, outcome: ChunkOutcome) -> None:
        self._worker.chunk_finished.emit(outcome.index)

    def on_chunk_started(self, index: int, total: int) -> None:
        self._worker._cancel_if_requested()

    def on_chunk_failed(self, index: int, error: TranscriberError) -> None:
        message = getattr(error, "user_message", "The chunk could not be transcribed.")
        self._worker.chunk_failed.emit(index, str(message))

    def on_finished(self, report: TranscriptionReport) -> None:
        self._worker._remember_terminal(report)

    def on_cancelled(self, report: TranscriptionReport) -> None:
        self._worker._remember_terminal(report)


class PipelineWorker(QObject):
    """Run a pipeline in a QThread without touching any widget."""

    analyzing = Signal()
    planned = Signal(int)
    chunk_finished = Signal(int)
    chunk_failed = Signal(int, str)
    finished = Signal(object)
    cancelled = Signal(object)

    def __init__(
        self,
        source: Path,
        model: str,
        language: str | None,
        *,
        pipeline_factory: PipelineFactory | None = None,
        api_key: str | None = None,
    ) -> None:
        super().__init__()
        self.source = Path(source)
        self.model = model
        self.language = language
        self._pipeline_factory = pipeline_factory
        self._api_key = api_key
        self._pipeline: TranscriptionPipeline | None = None
        self._pipeline_client_closed = False
        self._callbacks = _WorkerCallbacks(self)
        self._home_thread = QThread.currentThread()
        self._thread: QThread | None = None
        self._threads: list[QThread] = []
        self._operation = "run"
        self._terminal_emitted = False
        self._cancel_requested = False
        self._pending_terminal: object | None = None

    def start(self) -> None:
        """Start a fresh transcription on a dedicated thread."""
        if self._pipeline is not None:
            return
        self._launch("run")

    @Slot()
    def cancel(self) -> None:
        """Request best-effort cancellation of the current operation."""
        self._cancel_requested = True
        self._cancel_if_requested()

    def _cancel_if_requested(self) -> None:
        if not self._cancel_requested or self._pipeline is None:
            return
        try:
            self._pipeline.cancel()
        except Exception:
            # The pipeline's cancellation event remains the source of truth.
            pass

    @Slot()
    def retry_failed(self) -> None:
        """Retry failed chunks from the previous report on a worker thread."""
        if self._pipeline is None:
            return
        self._cancel_requested = False
        self._launch("retry")

    def wait_for_threads(self) -> None:
        """Join finished operations before their owning window is destroyed."""
        threads, self._threads = self._threads, []
        for thread in threads:
            if thread.isRunning():
                thread.wait()
            thread.deleteLater()

    def close_pipeline_client(self) -> None:
        """Close the pipeline's client when no retry can reuse it."""
        if self._pipeline_client_closed:
            return
        client = getattr(self._pipeline, "client", None)
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
            self._pipeline_client_closed = True

    def _launch(self, operation: str) -> None:
        if self._thread is not None and self._thread.isRunning():
            return
        thread = QThread()
        thread.started.connect(self._execute)
        # Retain completed thread wrappers until this worker is released. The
        # Python wrapper must outlive QThread::finished, not just _execute().
        self._threads.append(thread)
        self._thread = thread
        self._operation = operation
        if operation == "retry":
            self._pipeline_client_closed = False
        self._terminal_emitted = False
        self._cancel_requested = False
        self._pending_terminal = None
        self.moveToThread(thread)
        thread.start()

    def _create_pipeline(self) -> TranscriptionPipeline:
        if self._pipeline_factory is not None:
            return self._pipeline_factory(model=self.model, callbacks=self._callbacks)
        if not self._api_key:
            raise RuntimeError("The secure API credential is unavailable.")
        client = OpenRouterClient(self._api_key)
        return TranscriptionPipeline(client, model=self.model, callbacks=self._callbacks)

    @Slot()
    def _execute(self) -> None:
        thread = self._thread
        result: object | None = None
        try:
            if self._operation == "retry":
                if self._pipeline is None:
                    raise RuntimeError("There is no completed pipeline to retry.")
                report = self._pipeline.retry_failed()
            else:
                self._pipeline = self._create_pipeline()
                report = self._pipeline.run(self.source, language=self.language)
            result = (
                self._pending_terminal
                if self._pending_terminal is not None
                else report
            )
            if isinstance(report, TranscriptionReport) and (
                report.is_complete or report.cancelled
            ):
                self.close_pipeline_client()
        except Exception as error:
            result = (
                self._pending_terminal
                if self._pending_terminal is not None
                else error
            )
            self.close_pipeline_client()
        finally:
            # A completed worker can be moved back to the GUI thread and reused
            # for retry_failed() without keeping a thread alive while idle.
            self._thread = None
            self.moveToThread(self._home_thread)
            if thread is not None:
                thread.quit()
            if result is not None:
                self._emit_terminal(result)

    def _remember_terminal(self, result: object) -> None:
        self._pending_terminal = result

    def _emit_terminal(self, result: object) -> None:
        if self._terminal_emitted:
            return
        self._terminal_emitted = True
        if getattr(result, "cancelled", False):
            self.cancelled.emit(result)
        else:
            self.finished.emit(result)


class MainWindow(QMainWindow):
    """Select a local audio file and transcribe it with an approved model."""

    def __init__(
        self,
        store: CredentialStore | None = None,
        client: OpenRouterClient | None = None,
        pipeline_factory: PipelineFactory | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Windows Audio Transcriber")
        self.resize(760, 600)

        self._store = store
        self._client = client
        self._owns_client = client is None
        self._injected_pipeline_factory = pipeline_factory
        self._settings = AppSettings()
        self._api_key: str | None = None
        self._selected_file: Path | None = None
        self._available_models: list[str] = []
        self._worker: PipelineWorker | None = None
        self._last_report: TranscriptionReport | None = None
        self._completed_chunks: set[int] = set()
        self._total_chunks = 0
        self._running = False
        self._close_when_finished = False
        self._startup_cancelled = False
        self._credential_error: str | None = None

        self._build_widgets()
        self.zdr_acknowledgement.setChecked(self._settings.zdr_acknowledged)
        self.zdr_acknowledgement.toggled.connect(self._acknowledgement_changed)
        self.browse_button.clicked.connect(self.select_file)
        self.transcribe_button.clicked.connect(self._start_transcription)
        self.cancel_button.clicked.connect(self._cancel_transcription)
        self.retry_button.clicked.connect(self._retry_failed)
        self.copy_button.clicked.connect(self.copy_transcript)
        self.save_button.clicked.connect(self.save_transcript)
        self.model_combo.currentIndexChanged.connect(self._update_controls)
        self.file_edit.textChanged.connect(self._update_controls)

        if not self._load_credentials():
            self._update_controls()
            return
        if self._client is None:
            self._client = OpenRouterClient(self._api_key or "")
        self.refresh_models()
        self._update_controls()

    def _build_widgets(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.zdr_warning_label = QLabel(constants.ZDR_WARNING, central)
        self.zdr_warning_label.setObjectName("zdr_warning_label")
        self.zdr_warning_label.setWordWrap(True)
        self.zdr_warning_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.zdr_warning_label)

        self.zdr_acknowledgement = QCheckBox(
            "I confirm ZDR is enforced on this API key/account.", central
        )
        self.zdr_acknowledgement.setObjectName("zdr_acknowledgement")
        layout.addWidget(self.zdr_acknowledgement)

        file_row = QHBoxLayout()
        self.browse_button = QPushButton("Browse…", central)
        self.browse_button.setObjectName("browse_button")
        self.file_edit = QLineEdit(central)
        self.file_edit.setObjectName("file_edit")
        self.file_edit.setReadOnly(True)
        self.file_edit.setPlaceholderText("Choose an audio file")
        file_row.addWidget(self.browse_button)
        file_row.addWidget(self.file_edit, 1)
        layout.addLayout(file_row)

        options_row = QHBoxLayout()
        options_row.addWidget(QLabel("Approved model:", central))
        self.model_combo = QComboBox(central)
        self.model_combo.setObjectName("model_combo")
        options_row.addWidget(self.model_combo, 1)
        options_row.addWidget(QLabel("Language:", central))
        self.language_combo = QComboBox(central)
        self.language_combo.setObjectName("language_combo")
        self.language_combo.addItems(constants.LANGUAGES)
        options_row.addWidget(self.language_combo, 1)
        layout.addLayout(options_row)

        action_row = QHBoxLayout()
        self.transcribe_button = QPushButton("Transcribe", central)
        self.transcribe_button.setObjectName("transcribe_button")
        self.cancel_button = QPushButton("Cancel", central)
        self.cancel_button.setObjectName("cancel_button")
        self.retry_button = QPushButton("Retry failed chunks", central)
        self.retry_button.setObjectName("retry_button")
        self.copy_button = QPushButton("Copy", central)
        self.copy_button.setObjectName("copy_button")
        self.save_button = QPushButton("Save As", central)
        self.save_button.setObjectName("save_button")
        action_row.addWidget(self.transcribe_button)
        action_row.addWidget(self.cancel_button)
        action_row.addWidget(self.retry_button)
        action_row.addStretch(1)
        action_row.addWidget(self.copy_button)
        action_row.addWidget(self.save_button)
        layout.addLayout(action_row)

        self.progress_bar = QProgressBar(central)
        self.progress_bar.setObjectName("progress_bar")
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Choose an audio file to begin.", central)
        self.status_label.setObjectName("status_label")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.cost_label = QLabel("Cost will be shown after transcription.", central)
        self.cost_label.setObjectName("cost_label")
        layout.addWidget(self.cost_label)

        self.transcript_edit = QPlainTextEdit(central)
        self.transcript_edit.setObjectName("transcript_edit")
        self.transcript_edit.setReadOnly(True)
        layout.addWidget(self.transcript_edit, 1)

        self.cancel_button.setEnabled(False)
        self.retry_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.save_button.setEnabled(False)

    def _load_credentials(self) -> bool:
        if self._store is None:
            try:
                self._store = CredentialStore()
            except Exception as error:
                self._credential_error = self._safe_message(
                    error, "Secure credential storage is unavailable."
                )
                self.status_label.setText(self._credential_error)
                return False

        try:
            key = self._store.load()
        except Exception as error:
            self.status_label.setText(
                self._safe_message(error, "The saved API credential could not be read safely.")
            )
            return False

        if not key:
            dialog = KeyDialog(self._store, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                self._startup_cancelled = True
                self.close()
                return False
            try:
                key = self._store.load()
            except Exception as error:
                self.status_label.setText(
                    self._safe_message(error, "The saved API credential could not be read safely.")
                )
                return False

        if not key:
            self._startup_cancelled = True
            self.close()
            return False
        self._api_key = key
        return True

    def available_models(self) -> list[str]:
        """Return only allowlisted models available to the current key."""
        return list(self._available_models)

    def select_file(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Choose audio file",
            "",
            "Audio files (*.wav *.mp3 *.m4a *.mp4 *.mov *.flac *.ogg);;All files (*.*)",
        )
        if not selected:
            return
        self._selected_file = Path(selected)
        self.file_edit.setText(str(self._selected_file))
        if self.available_models():
            self.status_label.setText("Ready when ZDR acknowledgement is confirmed.")
        self._update_controls()

    def refresh_models(self) -> None:
        """Discover available models and never substitute a default model."""
        self._available_models.clear()
        self.model_combo.clear()
        if self._client is None:
            self.status_label.setText("Approved transcription models could not be checked.")
            self._update_controls()
            return
        try:
            discovered = self._client.list_available_models()
        except Exception as error:
            self.status_label.setText(
                self._safe_message(error, "The approved transcription models could not be fetched.")
            )
            self._update_controls()
            return

        allowed = set(constants.ALLOWED_MODELS)
        for model in discovered:
            if model in allowed and model not in self._available_models:
                self._available_models.append(model)
        self.model_combo.addItems(self._available_models)

        if not self._available_models:
            error = NoApprovedModelAvailable()
            message = error.user_message.replace("Neither approved", "No approved", 1)
            self.status_label.setText(message)
        else:
            self.status_label.setText("Choose an audio file to begin.")
        self._update_controls()

    def _start_transcription(self) -> None:
        model = self.model_combo.currentText()
        if (
            self._running
            or not self._settings.zdr_acknowledged
            or self._selected_file is None
            or model not in self._available_models
        ):
            self._update_controls()
            return

        if self._worker is not None:
            self._worker.close_pipeline_client()
        self._running = True
        self._last_report = None
        self._completed_chunks.clear()
        self._total_chunks = 0
        self.transcript_edit.clear()
        self.cost_label.clear()
        self.copy_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.retry_button.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self.status_label.setText("Analyzing audio…")
        language = self.language_combo.currentText()
        if language == constants.LANGUAGES[0]:
            language = None

        factory = self._injected_pipeline_factory
        key = self._api_key
        worker = PipelineWorker(
            self._selected_file,
            model,
            language,
            pipeline_factory=factory,
            api_key=key,
        )
        worker.analyzing.connect(self._on_analyzing)
        worker.planned.connect(self._on_planned)
        worker.chunk_finished.connect(self._on_chunk_finished)
        worker.chunk_failed.connect(self._on_chunk_failed)
        worker.finished.connect(self._on_finished)
        worker.cancelled.connect(self._on_cancelled)
        self._worker = worker
        worker.start()
        self._update_controls()

    def _cancel_transcription(self) -> None:
        if self._worker is not None:
            self.status_label.setText("Cancelling…")
            self._worker.cancel()

    def _retry_failed(self) -> None:
        if self._worker is None or self._last_report is None or not self._last_report.failures:
            return
        self._running = True
        self._completed_chunks = set(self._last_report.results)
        self._total_chunks = self._last_report.total_chunks
        self.progress_bar.setRange(0, max(1, self._total_chunks))
        self.progress_bar.setValue(len(self._completed_chunks))
        self.status_label.setText("Retrying failed chunks; another charge may apply.")
        self._worker.retry_failed()
        self._update_controls()

    def _on_analyzing(self) -> None:
        self.status_label.setText("Analyzing audio…")

    def _on_planned(self, total: int) -> None:
        self._total_chunks = max(0, total)
        self._completed_chunks.clear()
        self.progress_bar.setRange(0, max(1, self._total_chunks))
        self.progress_bar.setValue(0)
        if total:
            self.status_label.setText(f"Transcribing {total} chunk(s)…")

    def _on_chunk_finished(self, index: int) -> None:
        self._mark_chunk_complete(index)
        self.status_label.setText(f"Transcribed chunk {index + 1} of {self._total_chunks}.")

    def _on_chunk_failed(self, index: int, message: str) -> None:
        self._mark_chunk_complete(index)
        self.status_label.setText(
            f"Chunk {index + 1} failed: {self._redact(message)}"
        )

    def _mark_chunk_complete(self, index: int) -> None:
        self._completed_chunks.add(index)
        if self._total_chunks:
            self.progress_bar.setValue(min(len(self._completed_chunks), self._total_chunks))

    @Slot(object)
    def _on_finished(self, result: object) -> None:
        self._wait_for_worker_threads()
        if isinstance(result, TranscriptionReport):
            self._show_report(result, cancelled=False)
        else:
            self._show_worker_error(result)

    @Slot(object)
    def _on_cancelled(self, result: object) -> None:
        self._wait_for_worker_threads()
        if isinstance(result, TranscriptionReport):
            self._show_report(result, cancelled=True)
        else:
            self._show_worker_error(result)

    def _show_report(self, report: TranscriptionReport, *, cancelled: bool) -> None:
        self._last_report = report
        self.transcript_edit.setPlainText(report.transcript())
        self.cost_label.setText(report.cost_note())
        self._total_chunks = report.total_chunks
        self.progress_bar.setRange(0, max(1, report.total_chunks))
        self.progress_bar.setValue(report.total_chunks)
        if cancelled or report.cancelled:
            self.status_label.setText(
                "Transcription cancelled. In-flight requests may still have been billed."
            )
        elif not report.is_complete:
            count = len(report.failures)
            self.status_label.setText(
                f"Transcription finished with {count} failed chunk(s); the text is partial."
            )
        else:
            self.status_label.setText("Transcription complete.")
        self._running = False
        self.retry_button.setEnabled(bool(report.failures))
        self.copy_button.setEnabled(True)
        self.save_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self._update_controls()
        self._close_after_worker_if_requested()

    def _show_worker_error(self, error: object) -> None:
        self.status_label.setText(
            self._safe_message(error, "The transcription could not be completed.")
        )
        self.progress_bar.setRange(0, max(1, self._total_chunks))
        self.progress_bar.setValue(
            min(len(self._completed_chunks), self.progress_bar.maximum())
        )
        self._running = False
        self.cancel_button.setEnabled(False)
        self.retry_button.setEnabled(
            self._last_report is not None and bool(self._last_report.failures)
        )
        self._update_controls()
        self._close_after_worker_if_requested()

    def _wait_for_worker_threads(self) -> None:
        if self._worker is not None:
            self._worker.wait_for_threads()

    def _close_after_worker_if_requested(self) -> None:
        if self._close_when_finished:
            QTimer.singleShot(0, self.close)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt virtual method name
        if self._running:
            self._close_when_finished = True
            self._cancel_transcription()
            event.ignore()
            return
        self._wait_for_worker_threads()
        if self._worker is not None:
            self._worker.close_pipeline_client()
        if self._owns_client and self._client is not None:
            close = getattr(self._client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        super().closeEvent(event)

    def copy_transcript(self) -> None:
        QApplication.clipboard().setText(self.transcript_edit.toPlainText())

    def save_transcript(self) -> None:
        destination, _ = QFileDialog.getSaveFileName(
            self,
            "Save transcript",
            "transcript.txt",
            "Text files (*.txt);;All files (*.*)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not destination:
            return
        path = Path(destination)
        if path.exists():
            answer = QMessageBox.question(
                self,
                "Confirm overwrite",
                "This file already exists. Replace it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            path.write_text(self.transcript_edit.toPlainText(), encoding="utf-8")
        except OSError:
            self.status_label.setText("The transcript could not be saved.")
            return
        self.status_label.setText("Transcript saved.")

    def _acknowledgement_changed(self, acknowledged: bool) -> None:
        self._settings.zdr_acknowledged = acknowledged
        self._update_controls()

    def _update_controls(self, *_args) -> None:
        available = self.model_combo.currentText() in self._available_models
        has_file = self._selected_file is not None and bool(self.file_edit.text())
        acknowledged = self._settings.zdr_acknowledged
        self.transcribe_button.setEnabled(
            not self._running and has_file and available and acknowledged
        )
        self.browse_button.setEnabled(not self._running)
        self.file_edit.setEnabled(True)
        self.model_combo.setEnabled(not self._running and bool(self._available_models))
        self.language_combo.setEnabled(not self._running)
        self.cancel_button.setEnabled(self._running)
        self.retry_button.setEnabled(
            not self._running and self._last_report is not None and bool(self._last_report.failures)
        )

    def _safe_message(self, error: object, fallback: str) -> str:
        if isinstance(error, TranscriberError):
            message = error.user_message
        else:
            message = fallback
        return self._redact(message)

    def _redact(self, message: str) -> str:
        if self._api_key:
            return message.replace(self._api_key, "[redacted]")
        return message


__all__ = ["MainWindow", "PipelineWorker"]
