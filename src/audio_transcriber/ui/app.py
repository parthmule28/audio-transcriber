"""Application bootstrap shared by the desktop entry point and tests."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication


def build_application(argv: list[str]) -> QApplication:
    """Create or retrieve the Qt application with stable application metadata."""
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    if os.environ.get("AUDIO_TRANSCRIBER_HEADLESS") == "1":
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    application = QApplication.instance()
    if application is None:
        application = QApplication(argv)
    application.setApplicationName("Windows Audio Transcriber")
    application.setOrganizationName("AudioTranscriber")
    return application


__all__ = ["build_application"]
