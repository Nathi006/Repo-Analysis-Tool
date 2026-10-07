"""REST API for the RAT dashboard."""

import re
import shutil

from fastapi import APIRouter, HTTPException, Query, UploadFile

from . import db, ingest, jobs, metrics, progress

router = APIRouter(prefix="/api")

_HEX_HASH = re.compile(r"^[0-9a-fA-F]{4,40}$")


def _parse_hashes(raw):
    """Commit-set filter: accept full or prefix hashes, comma-separated."""
    if not raw:
        return None
    hashes = [h.strip() for h in raw.split(",") if h.strip()]
    for h in hashes:
        if not _HEX_HASH.match(h):
            raise HTTPException(400, f"invalid commit hash '{h}'")
    return hashes


def _repo_or_404(repo_id):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM repos WHERE id=?", (repo_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "repository not found")
    return row


@router.get("/repos")
def list_repos():
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT r.*, "
            "(SELECT COUNT(*) FROM commits c WHERE c.repo_id=r.id) commit_count, "
            "(SELECT COUNT(*) FROM authors a WHERE a.repo_id=r.id) author_count "
            "FROM repos r ORDER BY r.id").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d.update(progress.get_progress(r["id"]))
        out.append(d)
    return out


@router.post("/repos/upload")
async def upload_repo(file: UploadFile, name: str = "", ref: str = "HEAD"):
    data = await file.read()
    try:
        repo_id, _ = ingest.ingest_zip(data, name or None, ref or "HEAD")
    except ValueError as e:
        raise HTTPException(400, str(e))
    jobs.start_job(repo_id)
    return {"id": repo_id}


@router.post("/repos/clone")
def clone_repo(url: str, name: str = "", ref: str = "HEAD"):
    if not url.startswith(("http://", "https://", "git://", "ssh://", "git@", "file://")):
        raise HTTPException(400, "invalid repository URL")
    repo_id = ingest.ingest_clone(url, name or None, ref or "HEAD")
    jobs.start_job(repo_id)
    return {"id": repo_id}


@router.delete("/repos/{repo_id}")
def delete_repo(repo_id: int):
    _repo_or_404(repo_id)
    # stop a running job first, then remove data and files
    jobs.cancel(repo_id)
    jobs.wait(repo_id, timeout=30)
    with db.connect() as conn:
        conn.execute("DELETE FROM repos WHERE id=?", (repo_id,))
    shutil.rmtree(ingest.repo_dir(repo_id), ignore_errors=True)
    progress.clear_progress(repo_id)
    return {"ok": True}


@router.post("/repos/{repo_id}/retry")
def retry_repo(repo_id: int):
    """Re-run ingestion for a failed repository."""
    row = _repo_or_404(repo_id)
    if row["status"] == "ready":
        return {"ok": True}
    with db.connect() as conn:
        conn.execute(
            "UPDATE repos SET status='queued', error=NULL WHERE id=?", (repo_id,))
    jobs.start_job(repo_id)
    return {"ok": True}


@router.get("/repos/{repo_id}")
def repo_detail(repo_id: int):
    row = _repo_or_404(repo_id)
    d = dict(row)
    with db.connect() as conn:
        d["commit_count"] = conn.execute(
            "SELECT COUNT(*) FROM commits WHERE repo_id=?", (repo_id,)).fetchone()[0]
        bounds = conn.execute(
            "SELECT MIN(committer_ts) lo, MAX(committer_ts) hi FROM commits "
            "WHERE repo_id=?", (repo_id,)).fetchone()
        d["first_ts"], d["last_ts"] = bounds["lo"], bounds["hi"]
        d["authors"] = [dict(a) for a in conn.execute(
            "SELECT a.id, a.name, a.email, a.canonical_id, COALESCE(n.cnt, 0) commits "
            "FROM authors a LEFT JOIN (SELECT author_id, COUNT(*) cnt FROM commits "
            "WHERE repo_id=? GROUP BY author_id) n ON n.author_id = a.id "
            "WHERE a.repo_id=? ORDER BY commits DESC", (repo_id, repo_id))]
    d.update(progress.get_progress(repo_id))
    return d


@router.post("/repos/{repo_id}/authors/merge")
def merge_authors(repo_id: int, ids: list[int]):
    if len(ids) < 2:
        raise HTTPException(400, "select at least two authors to merge")
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, canonical_id FROM authors WHERE repo_id=? AND id IN "
            f"({','.join('?' * len(ids))})", [repo_id] + ids).fetchall()
        if len(rows) != len(ids):
            raise HTTPException(404, "unknown author")
        # resolve each selected author to its root canonical identity
        def root(aid):
            seen = set()
            while aid in {r["id"] for r in rows} and aid not in seen:
                seen.add(aid)
                nxt = next((r["canonical_id"] for r in rows if r["id"] == aid), None)
                if nxt is None:
                    return aid
                aid = nxt
            return aid
        canonical = min(root(r["id"]) for r in rows)
        for r in rows:
            if r["id"] != canonical:
                conn.execute("UPDATE authors SET canonical_id=? WHERE id=?",
                             (canonical, r["id"]))
    return {"ok": True, "canonical_id": canonical}


@router.get("/repos/{repo_id}/commits")
def list_commits(repo_id: int, q: str = "", limit: int = 200):
    with db.connect() as conn:
        if q:
            rows = conn.execute(
                "SELECT c.hash, c.committer_ts, c.subject, a.name, a.email "
                "FROM commits c JOIN authors a ON a.id=c.author_id "
                "WHERE c.repo_id=? AND (c.subject LIKE ? OR c.hash LIKE ?) "
                "ORDER BY c.committer_ts DESC LIMIT ?",
                (repo_id, f"%{q}%", f"{q}%", limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT c.hash, c.committer_ts, c.subject, a.name, a.email "
                "FROM commits c JOIN authors a ON a.id=c.author_id "
                "WHERE c.repo_id=? ORDER BY c.committer_ts DESC LIMIT ?",
                (repo_id, limit)).fetchall()
    return [dict(r) for r in rows]


@router.get("/repos/{repo_id}/tree")
def repo_tree(repo_id: int):
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT path, kind, first_ts, last_ts FROM paths WHERE repo_id=? "
            "ORDER BY path", (repo_id,)).fetchall()
    return [dict(r) for r in rows]


def _parse_filters(repo_id, params):
    def to_ints(raw):
        return [int(x) for x in raw.split(",") if x.strip()] if raw else None
    from_ts = int(params.get("from")) if params.get("from") not in (None, "") else None
    to_ts = int(params.get("to")) if params.get("to") not in (None, "") else None
    hashes = _parse_hashes(params.get("commits"))
    authors = to_ints(params.get("authors"))
    return from_ts, to_ts, hashes, authors


@router.get("/repos/{repo_id}/metrics")
def repo_metrics(repo_id: int, kind: str = "repo", path: str = "",
                 from_: int = Query(default=None, alias="from"),
                 to: int = None, commits: str = "", authors: str = ""):
    _repo_or_404(repo_id)
    if kind not in ("repo", "dir", "file"):
        raise HTTPException(400, "kind must be repo, dir or file")
    hashes = _parse_hashes(commits)
    author_ids = [int(x) for x in authors.split(",") if x.strip()] or None
    with db.connect() as conn:
        info = metrics.set_info(conn, repo_id, from_, to, hashes, author_ids)
        data = metrics.object_metrics(conn, repo_id, kind, path, from_, to,
                                      hashes, author_ids)
    data["set"] = info
    return data


@router.get("/repos/{repo_id}/leaders")
def repo_leaders(repo_id: int, kind: str = "file",
                 from_: int = Query(default=None, alias="from"),
                 to: int = None, commits: str = "", authors: str = "",
                 limit: int = 100):
    hashes = _parse_hashes(commits)
    author_ids = [int(x) for x in authors.split(",") if x.strip()] or None
    with db.connect() as conn:
        return metrics.leaders(conn, repo_id, kind, from_, to, hashes,
                               author_ids, limit)


@router.get("/repos/{repo_id}/authors")
def repo_authors(repo_id: int, from_: int = Query(default=None, alias="from"),
                 to: int = None, commits: str = "", limit: int = 100):
    hashes = _parse_hashes(commits)
    with db.connect() as conn:
        return metrics.author_leaderboard(conn, repo_id, from_, to, hashes, limit)


@router.get("/repos/{repo_id}/timeseries")
def repo_timeseries(repo_id: int, kind: str = "repo", path: str = "",
                    from_: int = Query(default=None, alias="from"),
                    to: int = None, commits: str = "",
                    authors: str = "", bucket: str = "month"):
    buckets = {"day": 86400, "week": 604800, "month": 2592000, "year": 31536000}
    if bucket not in buckets:
        raise HTTPException(400, "bucket must be day, week, month or year")
    hashes = _parse_hashes(commits)
    author_ids = [int(x) for x in authors.split(",") if x.strip()] or None
    with db.connect() as conn:
        return metrics.timeseries(conn, repo_id, kind, path, from_, to, hashes,
                                  author_ids, buckets[bucket])
