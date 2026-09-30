"""Command-line entry point for the desktop app and headless self-test."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    """Run the self-test directly or launch the Qt desktop application."""
    raw_argv = list(sys.argv if argv is None else argv)
    if raw_argv and not raw_argv[0].startswith("-"):
        program = raw_argv[0]
        arguments = raw_argv[1:]
    else:
        program = sys.argv[0] if sys.argv else "audio-transcriber"
        arguments = raw_argv

    if "--self-test" in arguments:
        from audio_transcriber import selftest

        return selftest.run_self_test()

    from audio_transcriber.ui.app import build_application
    from audio_transcriber.ui.main_window import MainWindow

    application = build_application([program, *arguments])
    window = MainWindow()
    if getattr(window, "_startup_cancelled", False):
        return 0
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
