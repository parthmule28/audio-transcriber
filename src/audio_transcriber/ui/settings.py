"""Application settings persisted through Qt's platform settings service."""

from PySide6.QtCore import QSettings


class AppSettings:
    """Persist the small amount of non-secret application state."""

    def __init__(self) -> None:
        self._settings = QSettings("AudioTranscriber", "AudioTranscriber")
        # Machine-wide settings must not silently override a user's choice.
        self._settings.setFallbacksEnabled(False)

    @property
    def zdr_acknowledged(self) -> bool:
        return self._settings.value("zdr_acknowledged", False, type=bool)

    @zdr_acknowledged.setter
    def zdr_acknowledged(self, acknowledged: bool) -> None:
        self._settings.setValue("zdr_acknowledged", bool(acknowledged))
        self._settings.sync()
