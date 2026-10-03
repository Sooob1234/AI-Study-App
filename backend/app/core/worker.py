"""A small waiting line for slow jobs, worked off one at a time.

Speech recognition uses all processor cores for minutes. Jobs therefore
wait in a line and a single background worker takes them in turn, so the
rest of the app stays responsive however many files are uploaded.

The line lives in the app's memory: jobs still waiting when the app stops
are lost, and their sources are marked FAILED / INTERRUPTED at the next
start (see app/core/recovery.py), from where they can be retried.
"""

import logging
import os
import queue
import threading
from typing import Callable

logger = logging.getLogger(__name__)

# The most jobs that may wait at once. Beyond this, new jobs are refused.
MAX_WAITING_JOBS = 20

# For the automated checks: do each job at once instead of in the background.
_INLINE = os.getenv("RUN_JOBS_INLINE") == "1"

_jobs: "queue.Queue[tuple[Callable, tuple]]" = queue.Queue()
_start_lock = threading.Lock()
_worker: threading.Thread | None = None


class WorkerBusy(Exception):
    """Too many jobs are already waiting."""


def _run(job: Callable, args: tuple) -> None:
    try:
        job(*args)
    except Exception:
        # A job reports its own failure on its source; this is a last net
        # so that one bad job can never stop the worker.
        logger.exception("Background job %s%r failed", job.__name__, args)


def _work() -> None:
    while True:
        job, args = _jobs.get()
        try:
            _run(job, args)
        finally:
            _jobs.task_done()


def has_room() -> bool:
    return _INLINE or _jobs.qsize() < MAX_WAITING_JOBS


def submit(job: Callable, *args) -> None:
    """Put a job in the line. Raises WorkerBusy if the line is full."""
    global _worker

    if _INLINE:
        _run(job, args)
        return

    if not has_room():
        raise WorkerBusy()

    with _start_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(
                target=_work, name="slow-jobs", daemon=True
            )
            _worker.start()

    _jobs.put((job, args))
