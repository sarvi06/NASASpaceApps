"""Run a slow job (a back-end call) without freezing the window.

    runner = Runner(widget)
    runner.start(job, on_progress=..., on_done=..., on_error=...)

`job(report)` runs in a background thread and may call `report("message")` as it goes. The three
callbacks run in the window's own thread, which is the only place tkinter may be touched.
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable

POLL_MS = 100


class Runner:
    def __init__(self, widget) -> None:
        self.widget = widget
        self.busy = False
        self._messages: queue.Queue = queue.Queue()

    def start(self, job: Callable[[Callable[[str], None]], Any],
              on_progress: Callable[[str], None], on_done: Callable[[Any], None],
              on_error: Callable[[Exception], None]) -> bool:
        """Start the job; returns False (and does nothing) if one is already running."""
        if self.busy:
            return False
        self.busy = True
        self._callbacks = {"progress": on_progress, "done": on_done, "error": on_error}

        def work() -> None:
            try:
                result = job(lambda message: self._messages.put(("progress", message)))
                self._messages.put(("done", result))
            except Exception as exc:            # shown to the user, never lost in the thread
                self._messages.put(("error", exc))

        threading.Thread(target=work, daemon=True).start()
        self.widget.after(POLL_MS, self._poll)
        return True

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self._messages.get_nowait()
                if kind != "progress":
                    self.busy = False
                self._callbacks[kind](payload)
        except queue.Empty:
            pass
        if self.busy:
            self.widget.after(POLL_MS, self._poll)
