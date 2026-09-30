"""OpenRouter API key setup dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from audio_transcriber import constants
from audio_transcriber.credentials import CredentialStore
from audio_transcriber.errors import CredentialStoreUnavailable


class KeyDialog(QDialog):
    """Collect an API key and persist it using the secure credential store."""

    ZDR_WARNING_TEXT = constants.ZDR_WARNING

    def __init__(self, store: CredentialStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self.was_forgotten = False
        self.setWindowTitle("OpenRouter API key")

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("OpenRouter API key:", self))
        self._key_edit = QLineEdit(self)
        self._key_edit.setObjectName("api_key_edit")
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self._key_edit)

        warning = QTextEdit(self)
        warning.setObjectName("zdr_warning")
        warning.setReadOnly(True)
        warning.setAcceptRichText(False)
        warning.setPlainText(self.ZDR_WARNING_TEXT)
        warning.setMinimumHeight(72)
        layout.addWidget(warning)

        layout.addWidget(
            QLabel(
                "Transcription charges are billed to the OpenRouter account that owns this API key.",
                self,
            )
        )

        self._error_label = QLabel(self)
        self._error_label.setObjectName("error_label")
        self._error_label.setWordWrap(True)
        self._error_label.hide()
        layout.addWidget(self._error_label)

        buttons = QHBoxLayout()
        buttons.addStretch()
        forget_button = QPushButton("Forget key", self)
        forget_button.clicked.connect(self.forget_key)
        buttons.addWidget(forget_button)
        save_button = QPushButton("Save", self)
        save_button.setDefault(True)
        save_button.clicked.connect(self.save)
        buttons.addWidget(save_button)
        layout.addLayout(buttons)

    def key(self) -> str:
        """Return the entered key for the caller, or an empty string if blank."""
        return self._key_edit.text()

    def save(self) -> None:
        """Save a non-blank key and accept the dialog on success."""
        self._clear_error()
        key = self.key()
        if not key.strip():
            return

        try:
            self._store.save(key)
        except CredentialStoreUnavailable as error:
            self._show_error(error.user_message)
            return

        self.accept()

    def forget_key(self) -> None:
        """Delete the credential and clear the field after successful deletion."""
        self._clear_error()
        try:
            self._store.forget()
        except CredentialStoreUnavailable as error:
            self._show_error(error.user_message)
            return

        self._key_edit.clear()
        self.was_forgotten = True

    def _clear_error(self) -> None:
        self._error_label.clear()
        self._error_label.hide()

    def _show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.show()
