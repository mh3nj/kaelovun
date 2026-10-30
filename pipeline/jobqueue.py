"""
jobqueue.py

Processing queue manager.

(Renamed from queue.py: a module called ``queue`` shadows the standard library's
``queue`` whenever this folder lands on sys.path, which breaks pytest plugins,
PyInstaller analysis and anything else that does ``import queue``.)

Pause/stop use threading.Event so they take effect immediately and cannot
deadlock: stopping a paused queue used to leave the worker sleeping forever.
"""

import threading


class JobQueue:

    def __init__(self, processor, logger, session=None):
        self.processor = processor
        self.logger = logger
        self.session = session
        self.jobs = []
        self.thread = None
        self._lock = threading.Lock()
        self._run = threading.Event()        # set while the queue is allowed to run
        self._go = threading.Event()         # set while NOT paused
        self._go.set()
        self.finished = threading.Event()    # set when the worker has fully wound down
        self.finished.set()

    # Read-only views, kept as plain attributes for the UI/CLI code.
    @property
    def running(self) -> bool:
        return self._run.is_set()

    @property
    def paused(self) -> bool:
        return not self._go.is_set()

    # ── control ──────────────────────────────────────────────

    def add_jobs(self, jobs):
        with self._lock:
            self.jobs.extend(jobs)
        self.logger.info(f"Added {len(jobs)} jobs.")

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        with self._lock:
            pending = [j for j in self.jobs if j.status.value != "done"]
        self.processor.set_queue_size(len(pending))
        self._run.set()
        self.finished.clear()
        self.thread = threading.Thread(target=self.worker, daemon=True)
        self.thread.start()

    def pause(self):
        self._go.clear()
        self.logger.info("Queue paused.")

    def resume(self):
        self._go.set()
        self.logger.info("Queue resumed.")

    def stop(self):
        self._run.clear()
        self._go.set()      # wake a paused worker so it can exit
        self.logger.warning("Queue stopped.")

    def join(self, timeout=None) -> bool:
        return self.finished.wait(timeout)

    # ── worker ───────────────────────────────────────────────

    def _next_job(self, index):
        with self._lock:
            return self.jobs[index] if index < len(self.jobs) else None

    def worker(self):
        self.logger.info("Queue started.")
        try:
            index = 0
            while self._run.is_set():
                job = self._next_job(index)
                if job is None:
                    break
                index += 1
                while self._run.is_set() and not self._go.wait(0.25):
                    pass
                if not self._run.is_set():
                    break
                if job.status.value == "done":
                    continue
                try:
                    self.logger.info(f"Processing {job.source_file.name}")
                    self.processor.process(job)
                except Exception as error:
                    self.logger.error(str(error))
                finally:
                    if self.session:
                        try:
                            with self._lock:
                                snapshot = list(self.jobs)
                            self.session.save(snapshot)
                        except Exception as error:
                            self.logger.warning(f"Could not save session: {error}")
        finally:
            self._run.clear()
            self.logger.info("=" * 50)
            self.logger.info(self.processor.get_summary())
            self.logger.info("=" * 50)
            self._close_apps()
            self.finished.set()

    def _close_apps(self):
        """Close external applications when the queue is fully done."""
        for attr in ("photoshop", "illustrator", "indesign", "affinity"):
            app = getattr(self.processor, attr, None)
            if app:
                try:
                    app.close()
                except Exception:
                    pass
