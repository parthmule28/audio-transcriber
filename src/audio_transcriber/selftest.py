"""Headless diagnostics for the packaged application."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple
from collections.abc import Callable

from .audio import resolve_binary


class SelfTestResult(NamedTuple):
    checks: list[tuple[str, bool, str]]

    @property
    def ok(self) -> bool:
        return all(ok for _, ok, _ in self.checks)


def _probe(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def _log_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "self-test.log"
    return Path.cwd() / "self-test.log"


def run_self_test(
    probe_fn: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    binary_probe: Callable[[str], str | Path] | None = None,
) -> SelfTestResult:
    """Run local runtime checks only; no network or credential APIs are used."""
    checks: list[tuple[str, bool, str]] = []
    checks.append(("python-version", sys.version_info >= (3, 11), sys.version.split()[0]))

    try:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtWidgets import QApplication
        import shiboken6

        app = QApplication.instance()
        if app is None:
            app = QApplication([])
            shiboken6.delete(app)
        checks.append(("qt-initialised", True, "Qt QApplication initialised (offscreen)"))
    except Exception as exc:
        checks.append(("qt-initialised", False, f"{type(exc).__name__}: {exc}"))

    runner = probe_fn or _probe
    resolver = binary_probe or resolve_binary
    for name in ("ffmpeg", "ffprobe"):
        try:
            binary = resolver(name)
            result = runner([str(binary), "-version"], timeout=20)
            ok = result.returncode == 0
            detail = (result.stdout or result.stderr or f"exit code {result.returncode}").splitlines()[0]
            checks.append((name, ok, detail))
        except Exception as exc:
            checks.append((name, False, f"{type(exc).__name__}: {exc}"))

    lines = [f"{name}: {'PASS' if ok else 'FAIL'} — {detail}" for name, ok, detail in checks]
    summary = "\n".join(lines) + "\n"
    print(summary, end="")
    try:
        _log_path().write_text(summary, encoding="utf-8")
    except OSError as exc:
        # Logging failure is a failed diagnostic: packaged callers need this artifact.
        checks.append(("self-test-log", False, f"{type(exc).__name__}: {exc}"))
        line = f"self-test-log: FAIL — {type(exc).__name__}: {exc}\n"
        print(line, end="")
    return SelfTestResult(checks)
