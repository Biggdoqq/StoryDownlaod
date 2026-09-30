"""
safe_thread.py — Global thread life-cycle manager for PyQt6
Prevents 'QThread: Destroyed while thread is still running' warnings
by holding strong references to running QThreads until they complete.
"""

from PyQt6.QtCore import QThread
from typing import TypeVar

T = TypeVar("T", bound=QThread)

_ACTIVE_THREADS = set()


def retain_thread(thread: T) -> T:
    """
    Retain a QThread instance in memory until its finished signal is emitted.
    This guarantees Python GC and Qt parent destruction will not destroy the
    QThread while its native thread is still running.
    """
    if thread is None:
        return None
    _ACTIVE_THREADS.add(thread)

    def _on_finished():
        _ACTIVE_THREADS.discard(thread)

    try:
        thread.finished.connect(_on_finished)
    except Exception:
        pass

    return thread
