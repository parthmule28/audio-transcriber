import pytest

from audio_transcriber.credentials import CredentialStore
from audio_transcriber.errors import CredentialStoreUnavailable


class FakeBackend:
    def __init__(self, stored=None):
        self.stored = stored
        self.calls = []

    def get_password(self, service, username):
        self.calls.append(("get", service, username))
        return self.stored

    def set_password(self, service, username, password):
        self.calls.append(("set", service, username))
        self.stored = password

    def delete_password(self, service, username):
        self.calls.append(("delete", service, username))
        self.stored = None


def test_missing_key_returns_none():
    assert CredentialStore(FakeBackend(), require_windows_backend=False).load() is None


def test_save_then_load_round_trips():
    backend = FakeBackend()
    store = CredentialStore(backend, require_windows_backend=False)
    store.save("sk-or-v1-secret")
    assert store.load() == "sk-or-v1-secret"


def test_forget_deletes_the_credential():
    backend = FakeBackend(stored="sk-or-v1-secret")
    store = CredentialStore(backend, require_windows_backend=False)
    store.forget()
    assert store.load() is None


def test_rejects_empty_or_whitespace_key():
    with pytest.raises(ValueError):
        CredentialStore(FakeBackend(), require_windows_backend=False).save("   ")


def test_unavailable_backend_fails_closed_without_writing_anywhere(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(CredentialStoreUnavailable):
        CredentialStore(backend=None, require_windows_backend=True).save("sk-or-v1-secret")
    assert list(tmp_path.iterdir()) == []


def test_backend_exceptions_are_wrapped_without_echoing_key():
    class BrokenBackend(FakeBackend):
        def set_password(self, service, username, password):
            raise RuntimeError(password)

    key = "sk-or-v1-never-echo"
    with pytest.raises(CredentialStoreUnavailable) as error:
        CredentialStore(BrokenBackend(), require_windows_backend=False).save(key)
    assert key not in str(error.value)


def test_delete_backend_exception_is_wrapped_without_echoing_secret(monkeypatch):
    import sys
    import types

    secret = "sk-or-v1-delete-secret"
    keyring_module = types.ModuleType("keyring")
    errors_module = types.ModuleType("keyring.errors")

    class PasswordDeleteError(Exception):
        pass

    errors_module.PasswordDeleteError = PasswordDeleteError
    keyring_module.errors = errors_module
    monkeypatch.setitem(sys.modules, "keyring", keyring_module)
    monkeypatch.setitem(sys.modules, "keyring.errors", errors_module)

    class BrokenDeleteBackend(FakeBackend):
        def delete_password(self, service, username):
            raise RuntimeError(secret)

    store = CredentialStore(BrokenDeleteBackend(), require_windows_backend=False)
    with pytest.raises(CredentialStoreUnavailable) as error:
        store.forget()
    assert secret not in str(error.value)


def test_injected_non_windows_backend_is_rejected_by_default():
    with pytest.raises(CredentialStoreUnavailable):
        CredentialStore(FakeBackend())


def test_backend_check_is_repeated_before_each_operation():
    backend = FakeBackend()
    store = CredentialStore(backend, require_windows_backend=False)
    store._require_windows_backend = True
    with pytest.raises(CredentialStoreUnavailable):
        store.load()
    assert backend.calls == []
