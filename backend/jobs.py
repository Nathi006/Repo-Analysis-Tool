"""Background job manager for repository ingestion.

The authoritative job state lives in the `repos.status` column (SQLite), so
jobs survive a server restart: `recover()` re-queues every unfinished repo at
startup. Live percentage progress stays in progress.py; thread and subprocess
handles live here so a delete can cancel a running job cleanly.
"""
import threading

from . import db, progress


class Cancelled(Exception):
    """Raised inside a worker when its repo was deleted mid-job."""


_THREADS = {}   # repo_id -> threading.Thread
_PROCS = {}     # repo_id -> subprocess.Popen
_lock = threading.Lock()

RECOVERABLE = ("pending", "queued", "cloning", "extracting")


def start_job(repo_id):
    """Run (or re-run) the ingestion worker for a repo in a daemon thread."""
    with _lock:
        current = _THREADS.get(repo_id)
        if current is not None and current.is_alive():
            return
        thread = threading.Thread(target=_worker, args=(repo_id,),
                                  name=f"ingest-{repo_id}", daemon=True)
        _THREADS[repo_id] = thread
    thread.start()


def _worker(repo_id):
    from . import ingest  # local import avoids a circular dependency
    try:
        ingest.run_ingest(repo_id)
    finally:
        with _lock:
            _THREADS.pop(repo_id, None)
            _PROCS.pop(repo_id, None)
        progress.clear_progress(repo_id)


def recover():
    """Re-queue every job left unfinished by a previous run (called at startup)."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id FROM repos WHERE status IN "
            f"({','.join('?' * len(RECOVERABLE))})", RECOVERABLE).fetchall()
    for row in rows:
        start_job(row["id"])


def register_proc(repo_id, proc):
    with _lock:
        _PROCS[repo_id] = proc


def unregister_proc(repo_id):
    with _lock:
        _PROCS.pop(repo_id, None)


def is_cancelled(repo_id):
    """True once the repo row is gone or marked 'cancelled'."""
    with db.connect() as conn:
        row = conn.execute("SELECT status FROM repos WHERE id=?",
                           (repo_id,)).fetchone()
    return row is None or row["status"] == "cancelled"


def cancel(repo_id):
    """Mark the repo cancelled and kill any running subprocess."""
    with db.connect() as conn:
        conn.execute("UPDATE repos SET status='cancelled' WHERE id=?", (repo_id,))
    with _lock:
        proc = _PROCS.pop(repo_id, None)
    if proc is not None and proc.poll() is None:
        proc.kill()


def wait(repo_id, timeout=30):
    """Wait for a running worker to finish (no-op if none is running)."""
    with _lock:
        thread = _THREADS.get(repo_id)
    if thread is not None and thread.is_alive() \
            and thread is not threading.current_thread():
        thread.join(timeout)
