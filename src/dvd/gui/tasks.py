"""Run slow engine calls (probe, preview, build) off the UI thread."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(str, float)


class _Task(QRunnable):
    def __init__(self, fn: Callable[..., Any], with_progress: bool) -> None:
        super().__init__()
        self.fn, self.with_progress = fn, with_progress
        self.signals = _Signals()

    def run(self) -> None:
        try:
            if self.with_progress:
                result = self.fn(lambda stage, f: self.signals.progress.emit(stage, f))
            else:
                result = self.fn()
        except Exception as exc:  # reported to the UI, which shows the message
            traceback.print_exc()
            self.signals.failed.emit(str(exc) or exc.__class__.__name__)
        else:
            self.signals.done.emit(result)


_running: set[_Task] = set()


def run(
    fn: Callable[..., Any],
    on_done: Callable[[Any], None],
    on_failed: Callable[[str], None],
    on_progress: Callable[[str, float], None] | None = None,
) -> None:
    task = _Task(fn, on_progress is not None)
    task.setAutoDelete(False)
    _running.add(task)
    task.signals.done.connect(on_done)
    task.signals.failed.connect(on_failed)
    if on_progress:
        task.signals.progress.connect(on_progress)
    for sig in (task.signals.done, task.signals.failed):
        sig.connect(lambda *_: _running.discard(task))
    QThreadPool.globalInstance().start(task)
