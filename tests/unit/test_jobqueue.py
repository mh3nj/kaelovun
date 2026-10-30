import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conftest import RecordingLogger  # noqa: E402

from pipeline.job import Job, JobStatus
from pipeline.jobqueue import JobQueue


def make_queue(handler):
    proc = MagicMock()
    proc.get_summary.return_value = "summary"
    proc.process.side_effect = handler
    return JobQueue(proc, RecordingLogger()), proc


def done(job):
    job.set_status(JobStatus.DONE)


def test_runs_all_jobs_and_finishes():
    q, proc = make_queue(done)
    q.add_jobs([Job(Path(f"/x/{i}.psd")) for i in range(3)])
    q.start()
    assert q.join(5) and proc.process.call_count == 3 and not q.running


def test_stop_while_paused_does_not_hang():
    """Regression: `while self.paused: sleep(1)` ignored stop and spun forever."""
    q, _ = make_queue(done)
    q.add_jobs([Job(Path("/x/a.psd"))])
    q.pause()
    q.start()
    time.sleep(0.2)
    q.stop()
    assert q.join(3), "worker did not exit after stop() while paused"


def test_resume_continues_processing():
    q, proc = make_queue(done)
    q.add_jobs([Job(Path("/x/a.psd"))])
    q.pause()
    q.start()
    time.sleep(0.3)
    assert proc.process.call_count == 0 and q.paused
    q.resume()
    assert q.join(3) and proc.process.call_count == 1


def test_jobs_added_while_running_are_processed():
    gate = threading.Event()

    def slow(job):
        gate.wait(2)
        done(job)

    q, proc = make_queue(slow)
    q.add_jobs([Job(Path("/x/a.psd"))])
    q.start()
    time.sleep(0.1)
    q.add_jobs([Job(Path("/x/b.psd"))])
    gate.set()
    assert q.join(5) and proc.process.call_count == 2


def test_error_in_one_job_does_not_stop_the_queue():
    def maybe_fail(job):
        if job.source_file.name == "a.psd":
            raise RuntimeError("boom")
        done(job)

    q, proc = make_queue(maybe_fail)
    q.add_jobs([Job(Path("/x/a.psd")), Job(Path("/x/b.psd"))])
    q.start()
    assert q.join(5) and proc.process.call_count == 2


def test_already_done_jobs_are_skipped_and_apps_closed():
    q, proc = make_queue(done)
    j = Job(Path("/x/a.psd"))
    j.set_status(JobStatus.DONE)
    q.add_jobs([j])
    q.start()
    q.join(3)
    assert proc.process.call_count == 0
    proc.photoshop.close.assert_called_once()
    proc.indesign.close.assert_called_once()
