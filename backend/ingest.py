"""Repository ingestion: zip upload / remote clone, then metric extraction."""
import io
import os
import re
import shutil
import subprocess
import time
import zipfile

from . import db, extract, progress

REPO_ROOT = db.DATA_DIR / "repos"


def repo_dir(repo_id):
    return REPO_ROOT / str(repo_id)


def sanitize_name(name):
    name = re.sub(r"[^\w.\-]+", "-", name.strip()).strip("-") or "repo"
    return name[:80]


def _unique_name(conn, base):
    name, i = base, 2
    while conn.execute("SELECT 1 FROM repos WHERE name=?", (name,)).fetchone():
        name = f"{base}-{i}"
        i += 1
    return name


def _register(conn, name, kind, source, head_ref):
    name = _unique_name(conn, sanitize_name(name))
    conn.execute(
        "INSERT INTO repos(name, kind, source, head_ref, status, created_at) "
        "VALUES(?,?,?,?, 'pending', ?)",
        (name, kind, source, head_ref or "HEAD", time.time()),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _find_git_dir(root):
    """Locate the .git directory (or gitdir file) inside an extracted archive."""
    for dirpath, dirnames, _ in os.walk(root):
        if ".git" in dirnames:
            return os.path.join(dirpath, ".git")
        if ".git" in os.listdir(dirpath) and os.path.isfile(os.path.join(dirpath, ".git")):
            return os.path.join(dirpath, ".git")
    return None


def ingest_zip(zip_bytes, name=None, head_ref=None):
    """Extract a zip archive and register it. Returns repo_id."""
    with db.connect() as conn:
        repo_id = _register(conn, name or "upload", "zip", None, head_ref)
    target = repo_dir(repo_id)
    try:
        progress.set_progress(repo_id, "extracting")
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            _safe_extract(zf, target)
        git_dir = _find_git_dir(target)
        if git_dir is None:
            raise ValueError("zip contains no .git directory")
        workdir = os.path.dirname(git_dir)
        # if the archive contained a single top-level folder, we already are in it
        with db.connect() as conn:
            conn.execute(
                "UPDATE repos SET source=?, status='queued' WHERE id=?",
                ("zip:" + (name or ""), repo_id),
            )
    except Exception as e:  # noqa: BLE001 - surface any ingest failure
        with db.connect() as conn:
            conn.execute(
                "UPDATE repos SET status='error', error=? WHERE id=?", (str(e), repo_id)
            )
        raise
    return repo_id, workdir


def _safe_extract(zf, target):
    for member in zf.infolist():
        path = os.path.normpath(member.filename)
        if path.startswith("..") or os.path.isabs(path):
            continue
        zf.extract(member, target)


def ingest_clone(url, name=None, head_ref=None):
    """Register a clone job. Returns repo_id."""
    with db.connect() as conn:
        repo_id = _register(conn, name or url.rstrip("/").rsplit("/", 1)[-1].replace(".git", ""),
                            "clone", url, head_ref)
        conn.execute("UPDATE repos SET status='queued' WHERE id=?", (repo_id,))
    return repo_id


def run_ingest(repo_id):
    """Background task: performs clone (if needed) then extraction."""
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM repos WHERE id=?", (repo_id,)).fetchone()
        if row is None:
            return
        kind, source, head_ref = row["kind"], row["source"], row["head_ref"]
        workdir = None
    try:
        if kind == "clone":
            target = repo_dir(repo_id)
            if target.exists():
                shutil.rmtree(target)
            target.mkdir(parents=True)
            progress.set_progress(repo_id, "cloning", 0, 0)
            proc = subprocess.run(
                ["git", "clone", "--progress", source, str(target / "repo")],
                capture_output=True, text=True, timeout=3600,
            )
            if proc.returncode != 0:
                raise RuntimeError("clone failed: " + proc.stderr[-500:])
            workdir = str(target / "repo")
        elif kind == "zip":
            workdir = _locate_workdir(repo_id)
        if workdir is None:
            raise RuntimeError("cannot locate repository working directory")
        # validate it is a git repo and resolve the ref
        subprocess.run(["git", "-C", workdir, "rev-parse", "--git-dir"],
                       check=True, capture_output=True, timeout=120)
        if head_ref and head_ref != "HEAD":
            try:
                subprocess.run(["git", "-C", workdir, "rev-parse", "--verify", head_ref + "^{commit}"],
                               check=True, capture_output=True, timeout=120)
            except subprocess.CalledProcessError:
                raise RuntimeError(f"reference '{head_ref}' does not exist in repository")
        progress.set_progress(repo_id, "extracting", 0, 0)
        extract.extract_repo(conn=None, repo_id=repo_id, workdir=workdir, head_ref=head_ref)
        with db.connect() as conn:
            conn.execute(
                "UPDATE repos SET status='ready', error=NULL WHERE id=?", (repo_id,)
            )
        progress.set_progress(repo_id, "ready", 100, 100)
    except Exception as e:  # noqa: BLE001
        with db.connect() as conn:
            conn.execute(
                "UPDATE repos SET status='error', error=? WHERE id=?", (str(e), repo_id)
            )
        progress.set_progress(repo_id, "error")


def _locate_workdir(repo_id):
    root = repo_dir(repo_id)
    git_dir = _find_git_dir(root)
    return os.path.dirname(git_dir) if git_dir else None
