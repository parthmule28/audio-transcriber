# Task 10 Report: Main Window and Worker-Thread Wiring

## Outcome

Implemented the main Qt window, a `QObject` pipeline worker that runs on a
`QThread`, Qt application bootstrap, and the CLI entry point. The main window
keeps the ZDR warning visible verbatim, persists acknowledgement, gates
transcription on acknowledgement/file/available approved model, and never
falls back to a model. Progress, partial/cancelled reports, retry, reported
cost, clipboard copy, and UTF-8 Save As are wired to pipeline results.

The worker forwards pipeline callbacks through Qt signals without accessing
widgets. It creates a fresh `OpenRouterClient` for each new transcription,
reuses that pipeline for failed-chunk retries, and handles thread cleanup before
the window is destroyed. `--self-test` is dispatched before importing or
starting the GUI path.

## Files changed

- `src/audio_transcriber/ui/main_window.py` — `PipelineWorker`, `MainWindow`,
  model discovery and gating, worker-thread progress/results/cancellation,
  retry, cost display, copy/save, and safe error messages.
- `src/audio_transcriber/ui/app.py` — `build_application(argv)` with high-DPI
  setup, application metadata, and opt-in offscreen mode.
- `src/audio_transcriber/__main__.py` — separates lazy `--self-test` dispatch
  from application creation and window display.
- `tests/test_main_window.py` — pytest-qt/offscreen behavior and integration
  tests for the main window, worker, and entry points.

The pre-existing untracked `src/audio_transcriber.egg-info/` files were left
untouched and were not included in the commit.

## TDD and verification

The initial test-first run failed during collection as expected before the main
window existed:

```text
$ source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_main_window.py -v
ERROR collecting tests/test_main_window.py
ModuleNotFoundError: No module named 'audio_transcriber.ui.main_window'
1 error in 0.16s
exit code: 2
```

Additional failing regression checks exposed and drove fixes for window-close
cancellation, stale Copy/Save controls during a new run, and an indeterminate
progress bar left active after worker startup errors. A worker integration run
also exposed premature `QThread` wrapper destruction; the worker now retains
and joins operation threads before releasing them. The failing regression
checks were rerun after their fixes.

Final targeted suite:

```text
$ source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_main_window.py -v
============================= 20 passed in 0.49s ==============================
```

Final full suite:

```text
$ source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest -v
============================= 151 passed in 1.29s =============================
```

Additional checks:

```text
$ source .venv/bin/activate && python -m compileall -q src/audio_transcriber tests
exit code: 0; no output

$ source .venv/bin/activate && AUDIO_TRANSCRIBER_HEADLESS=1 timeout 10 python -c "import sys; from audio_transcriber.__main__ import main; sys.argv=['x']; print('import ok')"
import ok
exit code: 0

$ git diff --cached --check
exit code: 0; no output
```

The tests ran with Python 3.13.5, pytest 9.1.1, PySide6 6.11.2, and pytest-qt
4.5.0. The GUI tests use Qt's offscreen platform and injected stores, clients,
and pipelines; they make no OpenRouter network requests.

## Commit

- `b012a2aee375d0f8e3caceea0abd86b346604f36` — `feat: add main window with progress, partial results, and ZDR gate`

This report is versioned separately from the implementation commit.

## Self-review findings

- Checked the exact ZDR warning text stays present independently of model
  discovery results and that the acknowledgement checkbox persists through
  `AppSettings`.
- Confirmed that model discovery is filtered through `constants.ALLOWED_MODELS`,
  the model combo remains empty when none are available, and transcription's
  start method independently enforces the file/model/acknowledgement gates.
- Confirmed language auto-detect becomes `None`, the pipeline runs off the GUI
  thread, progress reaches the planned total, and finished/partial/cancelled
  reports update transcript, status, retry availability, and cost.
- Confirmed saved API-key values are not used in window text, status messages,
  or logging; errors use safe user messages or generic fallbacks.
- Confirmed clipboard and Save As actions use only the current transcript,
  UTF-8 output, and an explicit overwrite confirmation.
- Confirmed the self-test branch returns before application/window creation.

## Concerns

- `src/audio_transcriber/selftest.py` is not present yet; it is the subject of
  Task 11. The dispatch was tested with an injected `selftest` module, so the
  real `--self-test` command depends on that subsequent task.
- This environment is Linux. Native Windows credential-manager behavior,
  platform dialogs, and a packaged Windows GUI run were not exercised here.
