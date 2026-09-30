from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QPushButton, QTextEdit

from audio_transcriber import constants
from audio_transcriber.errors import CredentialStoreUnavailable
from audio_transcriber.ui.key_dialog import KeyDialog
from audio_transcriber.ui.settings import AppSettings


class FakeStore:
    def __init__(self, stored=None, save_error=None):
        self.stored = stored
        self.save_error = save_error
        self.forget_calls = 0

    def save(self, key):
        if self.save_error is not None:
            raise self.save_error
        self.stored = key

    def forget(self):
        self.forget_calls += 1
        self.stored = None


def _button(dialog, text):
    return next(button for button in dialog.findChildren(QPushButton) if button.text() == text)


def _key_field(dialog):
    return dialog.findChild(QLineEdit)


def test_zdr_warning_is_visible_verbatim(qtbot):
    dialog = KeyDialog(FakeStore())
    qtbot.addWidget(dialog)
    dialog.show()

    warnings = dialog.findChildren(QTextEdit)
    assert any(warning.toPlainText() == constants.ZDR_WARNING for warning in warnings)
    assert any(warning.isReadOnly() and warning.isVisible() for warning in warnings)
    assert KeyDialog.ZDR_WARNING_TEXT == constants.ZDR_WARNING


def test_save_persists_key_without_displaying_it(qtbot):
    store = FakeStore()
    dialog = KeyDialog(store)
    qtbot.addWidget(dialog)
    dialog.show()
    secret = "sk-or-v1-secret"

    field = _key_field(dialog)
    field.setText(secret)
    assert field.echoMode() == QLineEdit.EchoMode.Password

    _button(dialog, "Save").click()

    assert store.stored == secret
    assert dialog.key() == secret
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert secret not in dialog.windowTitle()


def test_blank_key_leaves_existing_key_untouched(qtbot):
    store = FakeStore(stored="sk-or-v1-existing")
    dialog = KeyDialog(store)
    qtbot.addWidget(dialog)
    dialog.show()

    _button(dialog, "Save").click()

    assert store.stored == "sk-or-v1-existing"
    assert dialog.key() == ""
    assert dialog.result() != QDialog.DialogCode.Accepted


def test_forget_clears_the_field_and_calls_store(qtbot):
    store = FakeStore(stored="sk-or-v1-existing")
    dialog = KeyDialog(store)
    qtbot.addWidget(dialog)
    dialog.show()
    field = _key_field(dialog)
    field.setText("temporary input")

    _button(dialog, "Forget key").click()

    assert store.forget_calls == 1
    assert store.stored is None
    assert field.text() == ""


def test_store_failure_shows_message_and_does_not_echo_key(qtbot):
    store = FakeStore(save_error=CredentialStoreUnavailable("safe storage unavailable"))
    dialog = KeyDialog(store)
    qtbot.addWidget(dialog)
    dialog.show()
    secret = "sk-or-v1-never-echo"
    _key_field(dialog).setText(secret)

    _button(dialog, "Save").click()

    error_label = dialog.findChild(QLabel, "error_label")
    assert error_label is not None
    assert error_label.isVisible()
    assert CredentialStoreUnavailable.user_message in error_label.text()
    assert secret not in error_label.text()
    assert dialog.result() != QDialog.DialogCode.Accepted


def test_app_settings_persist_zdr_acknowledgement(tmp_path):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(tmp_path))

    settings = AppSettings()
    assert settings.zdr_acknowledged is False
    settings.zdr_acknowledged = True

    assert AppSettings().zdr_acknowledged is True
