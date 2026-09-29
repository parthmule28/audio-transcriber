"""Secure storage for the OpenRouter API key."""

from __future__ import annotations

from typing import Protocol

from .errors import CredentialStoreUnavailable

SERVICE_NAME = "AudioTranscriber"
ACCOUNT_NAME = "openrouter_api_key"


class KeyringBackend(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...

    def set_password(self, service: str, username: str, password: str) -> None: ...

    def delete_password(self, service: str, username: str) -> None: ...


def _is_windows_backend(backend: KeyringBackend) -> bool:
    return type(backend).__module__.startswith("keyring.backends.Windows")


class CredentialStore:
    def __init__(
        self,
        backend: KeyringBackend | None = None,
        require_windows_backend: bool = True,
    ) -> None:
        if backend is None:
            try:
                import keyring

                backend = keyring.get_keyring()
            except Exception:
                raise self._unavailable() from None
        self._backend = backend
        self._require_windows_backend = require_windows_backend
        self._check_backend()

    @staticmethod
    def _unavailable() -> CredentialStoreUnavailable:
        return CredentialStoreUnavailable(
            "The app only stores keys in Windows Credential Manager."
        )

    def _check_backend(self) -> None:
        if self._require_windows_backend and not _is_windows_backend(self._backend):
            raise self._unavailable()

    @property
    def backend_name(self) -> str:
        return type(self._backend).__name__

    def load(self) -> str | None:
        self._check_backend()
        try:
            return self._backend.get_password(SERVICE_NAME, ACCOUNT_NAME)
        except Exception:
            raise self._unavailable() from None

    def save(self, key: str) -> None:
        if not key or not key.strip():
            raise ValueError("API key must not be empty or whitespace.")
        self._check_backend()
        try:
            self._backend.set_password(SERVICE_NAME, ACCOUNT_NAME, key)
        except Exception:
            raise self._unavailable() from None

    def forget(self) -> None:
        self._check_backend()
        try:
            self._backend.delete_password(SERVICE_NAME, ACCOUNT_NAME)
        except Exception as exc:
            # keyring uses PasswordDeleteError for a missing entry.
            try:
                from keyring.errors import PasswordDeleteError
            except ImportError:
                PasswordDeleteError = ()
            if PasswordDeleteError and isinstance(exc, PasswordDeleteError):
                return
            raise self._unavailable() from None
