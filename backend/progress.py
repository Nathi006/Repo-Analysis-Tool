"""Shared progress registry for background ingestion tasks."""
import threading

# repo_id -> {"stage": str, "done": int, "total": int}
PROGRESS = {}
_lock = threading.Lock()


def set_progress(repo_id, stage, done=None, total=None):
    with _lock:
        cur = PROGRESS.get(repo_id, {"stage": "pending", "done": 0, "total": 0})
        cur["stage"] = stage
        if done is not None:
            cur["done"] = done
        if total is not None:
            cur["total"] = total
        PROGRESS[repo_id] = cur


def get_progress(repo_id):
    with _lock:
        cur = PROGRESS.get(repo_id)
        return dict(cur) if cur else {"stage": "pending", "done": 0, "total": 0}


def clear_progress(repo_id):
    with _lock:
        PROGRESS.pop(repo_id, None)
