"""Git history extraction: git log --numstat -M50% --use-mailmap -> SQLite.

Line format per commit (verified against git 2.43):
  \\x1e<HASH>\\x1f<committer_ts>\\x1f<author_name>\\x1f<author_email>\\x1f<subject>
  <blank line>
  <added>\\t<removed>\\t<path>            (regular change; '-' '-' = binary)
  <added>\\t<removed>\\t<old> => <new>   (rename, attributed to <new>)
  <blank line>
"""
import subprocess

from . import db, progress

RS, US = "\x1e", "\x1f"
FLUSH_EVERY = 1000


def _ancestors(path):
    """All directory prefixes of a file path (excluding the file itself)."""
    parts = path.split("/")[:-1]
    return ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]


def _split_numstat(line):
    """Returns (added, removed, new_path, old_path_or_None) or None for binary."""
    parts = line.split("\t", 2)
    if len(parts) != 3:
        return None
    added, removed, path = parts
    if added == "-":
        return None  # binary: not measured
    old = None
    if " => " in path and not path.startswith('"'):
        old, path = path.split(" => ", 1)
    return int(added), int(removed), path, old


def extract_repo(conn, repo_id, workdir, head_ref="HEAD"):
    """Extract full history from workdir into the database (long-running)."""
    with db.connect() as conn:
        conn.execute("DELETE FROM commits WHERE repo_id=?", (repo_id,))
        conn.execute("DELETE FROM paths WHERE repo_id=?", (repo_id,))
        conn.execute("DELETE FROM authors WHERE repo_id=?", (repo_id,))

    try:
        total = int(subprocess.run(
            ["git", "-C", workdir, "rev-list", "--count", "--no-merges", head_ref],
            capture_output=True, text=True, timeout=600,
        ).stdout.strip() or 0)
    except Exception:  # noqa: BLE001
        total = 0
    progress.set_progress(repo_id, "extracting", 0, total)

    cmd = [
        "git", "-C", workdir, "-c", "core.quotepath=false",
        "log", "--no-merges", "-M50%", "--use-mailmap",
        f"--format={RS}%H{US}%ct{US}%aN{US}%aE{US}%s",
        "--numstat", head_ref,
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace")

    conn = db.connect()
    author_ids = {}          # (name, email) -> id
    file_buf = []            # (commit_id, path, added, removed)
    dir_buf = []             # (commit_id, path, added, removed)
    path_ranges = {}         # path -> [first_ts, last_ts]
    n_done = 0
    cur = None               # dict for current commit

    def flush():
        nonlocal n_done
        if file_buf:
            conn.executemany(
                "INSERT OR IGNORE INTO file_stats(commit_id, path, added, removed) "
                "VALUES(?,?,?,?)", file_buf)
        if dir_buf:
            conn.executemany(
                "INSERT OR IGNORE INTO dir_stats(commit_id, path, added, removed) "
                "VALUES(?,?,?,?)", dir_buf)
        conn.commit()
        progress.set_progress(repo_id, "extracting", min(n_done, total), total)
        file_buf.clear()
        dir_buf.clear()

    def note_path(path, ts):
        entry = path_ranges.setdefault(path, [None, None])
        if entry[0] is None:
            entry[0] = ts
        entry[1] = ts

    try:
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            if line.startswith(RS):
                _finish_commit(cur, file_buf, dir_buf)  # finalise previous commit
                n_done += 1
                if n_done % FLUSH_EVERY == 0:
                    flush()
                fields = line[1:].split(US)
                if len(fields) != 5:
                    cur = None
                    continue
                h, ts_s, name, email, subject = fields
                ts = int(ts_s)
                key = (name, email)
                aid = author_ids.get(key)
                if aid is None:
                    cur_ = conn.execute(
                        "INSERT OR IGNORE INTO authors(repo_id, name, email) "
                        "VALUES(?,?,?)", (repo_id, name, email))
                    if cur_.rowcount:
                        aid = cur_.lastrowid
                    else:
                        aid = conn.execute(
                            "SELECT id FROM authors WHERE repo_id=? AND name=? "
                            "AND email=?", (repo_id, name, email)).fetchone()[0]
                    author_ids[key] = aid
                cid = conn.execute(
                    "INSERT INTO commits(repo_id, hash, author_id, committer_ts, "
                    "subject) VALUES(?,?,?,?,?)",
                    (repo_id, h, aid, ts, subject)).lastrowid
                cur = {"cid": cid, "ts": ts, "files": []}
            elif line == "" or cur is None:
                continue
            else:
                parsed = _split_numstat(line)
                if parsed is None:
                    continue
                added, removed, path, old = parsed
                cur["files"].append((path, added, removed))
                note_path(path, cur["ts"])
                if old is not None:
                    note_path(old, cur["ts"])
        _finish_commit(cur, file_buf, dir_buf)
        flush()
        err = proc.stderr.read()
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError("git log failed: " + err[-500:])
    finally:
        conn.close()

    _store_paths(repo_id, path_ranges, workdir, head_ref)
    progress.set_progress(repo_id, "extracting", total, total)


def _finish_commit(cur, file_buf, dir_buf):
    """Aggregate current commit's file stats into ancestor directories."""
    if cur is None:
        return
    dirs = {"": [0, 0]}
    for path, added, removed in cur["files"]:
        file_buf.append((cur["cid"], path, added, removed))
        dirs[""][0] += added
        dirs[""][1] += removed
        for d in _ancestors(path):
            acc = dirs.setdefault(d, [0, 0])
            acc[0] += added
            acc[1] += removed
    for d, (a, r) in dirs.items():
        dir_buf.append((cur["cid"], d, a, r))


def _store_paths(repo_id, path_ranges, workdir, head_ref):
    """Write paths table: files with first/last touched ts; dirs always visible."""
    head_files = set()
    try:
        out = subprocess.run(
            ["git", "-C", workdir, "-c", "core.quotepath=false",
             "ls-tree", "-r", "--name-only", head_ref],
            capture_output=True, text=True, timeout=300).stdout
        head_files = {ln for ln in out.splitlines() if ln}
    except Exception:  # noqa: BLE001
        pass
    rows = {(repo_id, "", "dir", None, None)}
    for path, (first, last) in path_ranges.items():
        if path in head_files:
            last = None
        rows.add((repo_id, path, "file", first, last))
        for d in _ancestors(path):
            rows.add((repo_id, d, "dir", None, None))
    for path in head_files:
        if path not in path_ranges:
            rows.add((repo_id, path, "file", None, None))
        for d in _ancestors(path):
            rows.add((repo_id, d, "dir", None, None))
    with db.connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO paths(repo_id, path, kind, first_ts, last_ts) "
            "VALUES(?,?,?,?,?)", list(rows))
