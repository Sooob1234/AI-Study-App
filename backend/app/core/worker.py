"""Waiting lines for slow jobs, each worked off one job at a time.

Slow work (speech recognition, fetching from YouTube) must not run inside
the threads that answer requests, or a burst of it would stall the whole
app. Such jobs wait in a line, and one background thread per line takes
them in turn.

A line lives in the app's memory: jobs still waiting when the app stops are
lost, and their sources are marked FAILED / INTERRUPTED at the next start
(see app/core/recovery.py), from where they can be retried.
"""

import logging
import os
import queue
import threading
from typing import Callable

logger = logging.getLogger(__name__)

# For the automated checks: do each job at once instead of in the background.
_INLINE = os.getenv("RUN_JOBS_INLINE") == "1"


class WorkerBusy(Exception):
    """Too many jobs are already waiting."""


class JobLine:
    def __init__(self, name: str, max_waiting: int):
        self.name = name
        # The most jobs that may wait at once. Beyond this, jobs are refused.
        self.max_waiting = max_waiting
        self._jobs: "queue.Queue[tuple[Callable, tuple]]" = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @staticmethod
    def _run(job: Callable, args: tuple) -> None:
        try:
            job(*args)
        except Exception:
            # A job reports its own failure on its source; this is a last
            # net so that one bad job can never stop the line.
            logger.exception("Background job %s%r failed", job.__name__, args)

    def _work(self) -> None:
        while True:
            job, args = self._jobs.get()
            try:
                self._run(job, args)
            finally:
                self._jobs.task_done()

    def has_room(self) -> bool:
        return _INLINE or self._jobs.qsize() < self.max_waiting

    def submit(self, job: Callable, *args) -> None:
        """Put a job in the line. Raises WorkerBusy if the line is full."""
        if _INLINE:
            self._run(job, args)
            return

        # Checking for room and joining the line happen as one step, so
        # that simultaneous requests cannot overfill the line.
        with self._lock:
            if self._jobs.qsize() >= self.max_waiting:
                raise WorkerBusy()

            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._work, name=f"jobs-{self.name}", daemon=True
                )
                self._thread.start()

            self._jobs.put((job, args))

    def wait_until_empty(self) -> None:
        """Block until every job in the line is done (used by the checks)."""
        self._jobs.join()


# Speech recognition uses every processor core for minutes at a time.
speech = JobLine("speech", max_waiting=20)
# Fetching from YouTube waits on the network.
network = JobLine("network", max_waiting=50)
