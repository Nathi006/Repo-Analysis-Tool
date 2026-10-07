"""Metric computation. All queries are pure SQL over precomputed tables.

Semantics (from the test brief):
  - commit set H = non-merge commits reachable from h_r (extraction already
    stores exactly H_bar), restricted by [from, to) on committer date and/or a
    manual list of commit hashes, and/or authors.
  - growth = added - removed, churn = added + removed
  - modifications n = |{h in H : lambda_h,o > 0}|
  - frequency = n/|H|, churn rate = churn/|H| (0 when |H| = 0)
  - author ownership = author churn / total churn
"""


def _set_conditions(alias, from_ts, to_ts, hashes, author_ids):
    """Returns (sql_fragment, params) for the commit-set restriction."""
    sql = [f"{alias}.repo_id = ?"]
    params = []
    if from_ts is not None:
        sql.append(f"{alias}.committer_ts >= ?")
        params.append(from_ts)
    if to_ts is not None:
        sql.append(f"{alias}.committer_ts < ?")
        params.append(to_ts)
    if hashes:
        # full or prefix hashes: LIKE 'ab12%' also matches the full 40 chars
        sql.append("(" + " OR ".join([f"{alias}.hash LIKE ?"] * len(hashes)) + ")")
        params.extend([h + "%" for h in hashes])
    if author_ids:
        sql.append(f"{alias}.author_id IN ({','.join('?' * len(author_ids))})")
        params.extend(author_ids)
    return " AND ".join(sql), params


def set_info(conn, repo_id, from_ts, to_ts, hashes, author_ids):
    cond, params = _set_conditions("c", from_ts, to_ts, hashes, author_ids)
    row = conn.execute(
        f"SELECT COUNT(*) n, MIN(c.committer_ts) lo, MAX(c.committer_ts) hi "
        f"FROM commits c WHERE {cond}", [repo_id] + params).fetchone()
    return {"count": row["n"] or 0, "from": row["lo"], "to": row["hi"]}


def object_metrics(conn, repo_id, kind, path, from_ts, to_ts, hashes, author_ids):
    """kind: 'file' | 'dir' | 'repo'. path ignored for 'repo' (root)."""
    stats = "dir_stats" if kind in ("dir", "repo") else "file_stats"
    obj_path = "" if kind == "repo" else path
    cond, params = _set_conditions("c", from_ts, to_ts, hashes, author_ids)

    row = conn.execute(
        f"SELECT COALESCE(SUM(s.added),0) added, COALESCE(SUM(s.removed),0) removed, "
        f"COUNT(*) FILTER (WHERE s.added + s.removed > 0) mods "
        f"FROM {stats} s JOIN commits c ON c.id = s.commit_id "
        f"WHERE {cond} AND s.path = ?", [repo_id] + params + [obj_path]).fetchone()

    n = set_info(conn, repo_id, from_ts, to_ts, hashes, author_ids)["count"]
    added, removed, mods = row["added"], row["removed"], row["mods"]
    churn = added + removed

    authors = conn.execute(
        f"SELECT COALESCE(ca.id, a.id) id, COALESCE(ca.name, a.name) name, "
        f"COALESCE(ca.email, a.email) email, "
        f"COUNT(*) FILTER (WHERE s.added + s.removed > 0) mods, "
        f"COALESCE(SUM(s.added + s.removed),0) churn "
        f"FROM {stats} s "
        f"JOIN commits c ON c.id = s.commit_id "
        f"JOIN authors a ON a.id = c.author_id "
        f"LEFT JOIN authors ca ON ca.id = a.canonical_id "
        f"WHERE {cond} AND s.path = ? "
        f"GROUP BY COALESCE(ca.id, a.id) "
        f"ORDER BY churn DESC", [repo_id] + params + [obj_path]).fetchall()

    author_list = []
    for a in authors:
        ownership = round(a["churn"] / churn, 6) if churn else 0.0
        author_list.append({
            "id": a["id"], "name": a["name"], "email": a["email"],
            "modifications": a["mods"], "churn": a["churn"],
            "ownership": ownership,
        })

    return {
        "object": {"kind": kind, "path": obj_path},
        "metric": {
            "added": added, "removed": removed,
            "growth": added - removed, "churn": churn,
            "modifications": mods,
            "frequency": round(mods / n, 6) if n else 0.0,
            "churn_rate": round(churn / n, 6) if n else 0.0,
        },
        "authors": author_list,
    }


def leaders(conn, repo_id, kind, from_ts, to_ts, hashes, author_ids, limit=100):
    """Top paths by churn over the set. kind: 'file' | 'dir'."""
    stats = "dir_stats" if kind == "dir" else "file_stats"
    cond, params = _set_conditions("c", from_ts, to_ts, hashes, author_ids)
    rows = conn.execute(
        f"SELECT s.path, COALESCE(SUM(s.added),0) added, COALESCE(SUM(s.removed),0) removed, "
        f"COUNT(*) FILTER (WHERE s.added + s.removed > 0) mods "
        f"FROM {stats} s JOIN commits c ON c.id = s.commit_id "
        f"WHERE {cond} GROUP BY s.path "
        f"ORDER BY (COALESCE(SUM(s.added),0) + COALESCE(SUM(s.removed),0)) DESC, s.path "
        f"LIMIT ?", [repo_id] + params + [limit]).fetchall()
    return [dict(r) for r in rows]


def author_leaderboard(conn, repo_id, from_ts, to_ts, hashes, limit=100):
    """Per-author totals over the set (canonical merged)."""
    cond, params = _set_conditions("c", from_ts, to_ts, hashes, None)
    rows = conn.execute(
        f"SELECT COALESCE(ca.id, a.id) id, COALESCE(ca.name, a.name) name, "
        f"COALESCE(ca.email, a.email) email, COUNT(c.id) commits, "
        f"COALESCE(SUM(d.added + d.removed),0) churn, "
        f"COUNT(*) FILTER (WHERE d.added + d.removed > 0) mods "
        f"FROM commits c "
        f"JOIN authors a ON a.id = c.author_id "
        f"LEFT JOIN authors ca ON ca.id = a.canonical_id "
        f"LEFT JOIN dir_stats d ON d.commit_id = c.id AND d.path = '' "
        f"WHERE {cond} GROUP BY COALESCE(ca.id, a.id) "
        f"ORDER BY churn DESC LIMIT ?", [repo_id] + params + [limit]).fetchall()
    total = conn.execute(
        f"SELECT COALESCE(SUM(d.added + d.removed),0) FROM dir_stats d "
        f"JOIN commits c ON c.id = d.commit_id "
        f"WHERE d.path = '' AND {cond}", [repo_id] + params).fetchone()[0]
    out = []
    for r in rows:
        d = dict(r)
        d["ownership"] = round(d["churn"] / total, 6) if total else 0.0
        out.append(d)
    return out


def timeseries(conn, repo_id, kind, path, from_ts, to_ts, hashes, author_ids,
               bucket_seconds):
    stats = "dir_stats" if kind in ("dir", "repo") else "file_stats"
    obj_path = "" if kind == "repo" else path
    cond, params = _set_conditions("c", from_ts, to_ts, hashes, author_ids)
    rows = conn.execute(
        f"SELECT (c.committer_ts / ?) * ? t, "
        f"COALESCE(SUM(s.added),0) added, COALESCE(SUM(s.removed),0) removed "
        f"FROM {stats} s JOIN commits c ON c.id = s.commit_id "
        f"WHERE {cond} AND s.path = ? GROUP BY t ORDER BY t",
        [bucket_seconds, bucket_seconds, repo_id] + params + [obj_path]).fetchall()
    return [dict(r) for r in rows]
