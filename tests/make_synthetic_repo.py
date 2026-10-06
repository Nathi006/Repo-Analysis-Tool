#!/usr/bin/env python3
"""RAT oracle test.

Builds a deterministic synthetic repository (fixed timestamps, authors and
contents), ingests it through the RAT API (clone + zip paths) and asserts the
returned metrics against hand-computed oracle values.

Covers: adds, edits, pure rename, rename+edit below and above the -M50%
threshold, binary exclusion, deletions, .mailmap author canonicalisation,
time-window [i, j) filtering, manual commit-set filtering, author filtering,
manual author merging, and ingestion error handling.

Requires the RAT server running (./run.sh). Exit code 0 = all checks pass.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile

BASE = os.environ.get("RAT_API", "http://127.0.0.1:8000")
HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "_oracle_fixture")
ZIP_PATH = os.path.join(HERE, "_oracle_fixture.zip")

# Fixed timestamps: Jan 1..9 2020, 00:00 UTC.
TS = [1577836800 + i * 86400 for i in range(9)]
TS_1, TS_2, TS_3, TS_4, TS_5, TS_6, TS_7, TS_8, TS_9 = TS

CHECKS = []


def check(name, got, want):
    ok = got == want
    CHECKS.append((ok, name, got, want))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + ("" if ok else f"  (got {got!r}, want {want!r})"))
    return ok


def sh(*args, cwd=None, env=None):
    return subprocess.run(args, check=True, capture_output=True,
                          text=True, cwd=cwd, env=env)


def api(path, method="GET", body=None, raw=False, timeout=30):
    data = None
    headers = {}
    if body is not None:
        if raw:
            data = body
        else:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except Exception:
            pass
        raise AssertionError(f"HTTP {e.code}: {detail}") from e


# ---------------------------------------------------------------- fixture

def build_fixture():
    if os.path.exists(FIXTURE):
        shutil.rmtree(FIXTURE)
    os.makedirs(FIXTURE)
    base_env = dict(os.environ)

    def commit(ts, name, email, msg):
        env = dict(base_env,
                   GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email,
                   GIT_COMMITTER_NAME=name, GIT_COMMITTER_EMAIL=email,
                   GIT_AUTHOR_DATE=f"{ts} +0000",
                   GIT_COMMITTER_DATE=f"{ts} +0000")
        sh("git", "add", "-A", cwd=FIXTURE, env=env)
        sh("git", "commit", "-m", msg, cwd=FIXTURE, env=env)

    def write(path, content, binary=False):
        p = os.path.join(FIXTURE, path)
        os.makedirs(os.path.dirname(p) or FIXTURE, exist_ok=True)
        with open(p, "wb" if binary else "w") as f:
            f.write(content)

    sh("git", "init", "-b", "main", cwd=FIXTURE)
    sh("git", "config", "user.name", "test", cwd=FIXTURE)
    sh("git", "config", "user.email", "test@test", cwd=FIXTURE)

    # c1 initial: a.txt (3 lines), sub/b.py (1 line)
    write("a.txt", "l1\nl2\nl3\n")
    write("sub/b.py", "print('b')\n")
    commit(TS_1, "Alice", "alice@x.com", "initial")

    # c2 edit a: +2/-1 on a.txt
    write("a.txt", "l1\nlX\nlY\nl3\n")
    commit(TS_2, "Alice", "alice@x.com", "edit a")

    # c3 pure rename: a.txt -> renamed.txt (100% similarity -> 0/0)
    sh("git", "mv", "a.txt", "renamed.txt", cwd=FIXTURE)
    commit(TS_3, "Alice", "alice@x.com", "pure rename")

    # c4 rename+edit below 50%: full rewrite of 2 lines -> delete + add
    write("renamed.txt", "totally\nnew\n")
    sh("git", "mv", "renamed.txt", "final.txt", cwd=FIXTURE)
    commit(TS_4, "Bob", "bob@x.com", "rename+edit33")

    # c5 pure rename again: final.txt -> final2.txt (0/0)
    sh("git", "mv", "final.txt", "final2.txt", cwd=FIXTURE)
    commit(TS_5, "Bob", "bob@x.com", "rename+edit80")

    # c6 binary + edit: blob.bin (binary, excluded), final2.txt +1
    write("blob.bin", b"\x00\x01\x02\xff\xfe", binary=True)
    write("final2.txt", "totally\nnew\nmore\n")
    commit(TS_6, "Bob", "bob@x.com", "add binary")

    # c7 delete file: sub/b.py
    os.unlink(os.path.join(FIXTURE, "sub", "b.py"))
    commit(TS_7, "Alice", "alice@x.com", "delete file")

    # c8 m.txt (4 lines) + .mailmap authored as alice.old@x.com
    write(".mailmap", "Alice <alice@x.com> <alice.old@x.com>\n")
    write("m.txt", "m1\nm2\nm3\nm4\n")
    commit(TS_8, "Alice", "alice.old@x.com", "add m")

    # c9 rename+edit >= 50%: counts land on the new path (m2.txt +2/-1)
    write("m.txt", "m1\nm2\nmX\nm4\nm5\n")
    sh("git", "mv", "m.txt", "m2.txt", cwd=FIXTURE)
    commit(TS_9, "Alice", "alice@x.com", "true rename+edit")

    print("  fixture numstat:")
    out = sh("git", "-c", "core.quotepath=false", "log", "--no-merges",
             "-M50%", "--use-mailmap", "--format=COMMIT %s",
             "--numstat", "--reverse", cwd=FIXTURE).stdout
    for line in out.splitlines():
        print("   ", line)


# ---------------------------------------------------------------- oracle

def wait_ready(repo_id, timeout=90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        for r in api("/api/repos"):
            if r["id"] == repo_id:
                if r["status"] in ("ready", "error"):
                    return r
        time.sleep(0.5)
    raise AssertionError(f"timeout waiting for repo {repo_id}")


def upload_zip(path, name):
    with open(path, "rb") as f:
        data = f.read()
    boundary = "----ratboundary1337"
    body = (f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; '
            f'filename="{os.path.basename(path)}"\r\n'
            f"Content-Type: application/zip\r\n\r\n").encode() + data + \
        f"\r\n--{boundary}--\r\n".encode()
    return _post_multipart(name, body, boundary)


def _post_multipart(name, body, boundary):
    req = urllib.request.Request(
        f"{BASE}/api/repos/upload?name={name}", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def metric(repo_id, kind="repo", path="", from_=None, to=None,
           commits=None, authors=None):
    qs = f"kind={kind}&path={urllib.parse.quote(path)}"
    if from_ is not None:
        qs += f"&from={from_}"
    if to is not None:
        qs += f"&to={to}"
    if commits:
        qs += f"&commits={commits}"
    if authors is not None:
        qs += f"&authors={authors}"
    return api(f"/api/repos/{repo_id}/metrics?{qs}")


def run_metric_checks(repo_id, expect_ready):
    m = metric(repo_id)["metric"]
    s = metric(repo_id)["set"]
    check("repo |H| = 9", s["count"], 9)
    check("repo added = 16", m["added"], 16)
    check("repo removed = 7", m["removed"], 7)
    check("repo growth = 9", m["growth"], 9)
    check("repo churn = 23", m["churn"], 23)
    check("repo mods = 7", m["modifications"], 7)
    check("repo frequency = 7/9", m["frequency"], round(7 / 9, 6))
    check("repo churn_rate = 23/9", m["churn_rate"], round(23 / 9, 6))

    files = {
        "a.txt": (5, 1, 2), "renamed.txt": (0, 4, 1),
        "final.txt": (2, 0, 1), "final2.txt": (1, 0, 1),
        "sub/b.py": (1, 1, 2), "m.txt": (4, 0, 1),
        "m2.txt": (2, 1, 1), ".mailmap": (1, 0, 1),
    }
    for path, (add, rem, mods) in files.items():
        m = metric(repo_id, "file", path)["metric"]
        check(f"file {path} +{add}/-{rem} mods {mods}",
              (m["added"], m["removed"], m["modifications"]),
              (add, rem, mods))

    # binary file excluded from metrics but present in the tree
    m = metric(repo_id, "file", "blob.bin")["metric"]
    check("binary blob.bin has zero metrics",
          (m["added"], m["removed"], m["modifications"]), (0, 0, 0))
    tree = api(f"/api/repos/{repo_id}/tree")
    check("blob.bin present in path tree",
          any(p["path"] == "blob.bin" and p["kind"] == "file" for p in tree), True)

    # directory metrics
    m = metric(repo_id, "dir", "sub")["metric"]
    check("dir sub +1/-1 mods 2",
          (m["added"], m["removed"], m["modifications"]), (1, 1, 2))

    # time window [Jan 3 00:00, Jan 6 00:00) -> commits c3, c4, c5
    m = metric(repo_id, from_=TS_3, to=TS_6)
    check("window |H| = 3", m["set"]["count"], 3)
    check("window churn = 6", m["metric"]["churn"], 6)
    check("window added = 2", m["metric"]["added"], 2)
    check("window removed = 4", m["metric"]["removed"], 4)
    check("window mods = 1", m["metric"]["modifications"], 1)

    # manual commit selection {c1, c4}
    hashes = {c["subject"]: c["hash"] for c in
              api(f"/api/repos/{repo_id}/commits?limit=200")}
    manual = ",".join([hashes["initial"], hashes["rename+edit33"]])
    m = metric(repo_id, commits=manual)
    check("manual |H| = 2", m["set"]["count"], 2)
    check("manual churn = 10", m["metric"]["churn"], 10)
    check("manual added = 6", m["metric"]["added"], 6)
    check("manual removed = 4", m["metric"]["removed"], 4)
    check("manual mods = 2", m["metric"]["modifications"], 2)

    # commit selection by short hash prefix
    m = metric(repo_id, commits=hashes["initial"][:10])
    check("prefix hash |H| = 1", m["set"]["count"], 1)
    check("prefix hash churn = 4", m["metric"]["churn"], 4)

    # malformed hashes rejected
    try:
        metric(repo_id, commits="zzz")
        check("invalid hash rejected", "no exception", "HTTP 400")
    except AssertionError as e:
        check("invalid hash rejected",
              "HTTP 400" if "HTTP 400" in str(e) else str(e), "HTTP 400")

    # authors: mailmap canonicalised alice.old -> Alice at extraction time
    authors = api(f"/api/repos/{repo_id}/authors")
    check("author count = 2 (mailmap applied)", len(authors), 2)
    alice = next((a for a in authors if a["name"] == "Alice"), None)
    bob = next((a for a in authors if a["name"] == "Bob"), None)
    check("Alice churn 16 / mods 5",
          (alice["churn"], alice["mods"]), (16, 5))
    check("Bob churn 7 / mods 2", (bob["churn"], bob["mods"]), (7, 2))
    check("Alice ownership 16/23", alice["ownership"], round(16 / 23, 6))
    check("Bob ownership 7/23", bob["ownership"], round(7 / 23, 6))

    # author filter
    m = metric(repo_id, authors=bob["id"])
    check("Bob filter |H| = 3", m["set"]["count"], 3)
    check("Bob filter churn = 7", m["metric"]["churn"], 7)
    check("Bob filter added = 3", m["metric"]["added"], 3)
    check("Bob filter removed = 4", m["metric"]["removed"], 4)

    # leaders
    top = api(f"/api/repos/{repo_id}/leaders?kind=file&limit=50")
    check("leader #1 is a.txt", top[0]["path"], "a.txt")
    check("leader #1 a.txt 5/1 mods 2",
          (top[0]["added"], top[0]["removed"], top[0]["mods"]), (5, 1, 2))
    check("blob.bin absent from leaders",
          any(r["path"] == "blob.bin" for r in top), False)

    # timeseries (day buckets): one bucket per day, totals match
    ts = api(f"/api/repos/{repo_id}/timeseries?bucket=day")
    check("timeseries has 9 buckets", len(ts), 9)
    check("timeseries totals match",
          (sum(d["added"] for d in ts), sum(d["removed"] for d in ts)), (16, 7))

    return alice, bob


def main():
    print("== building deterministic fixture ==")
    build_fixture()

    created = []

    try:
        print("\n== clone ingestion ==")
        rid = api(f"/api/repos/clone?url={urllib.parse.quote('file://' + FIXTURE)}"
                  f"&name=oracle-clone&ref=HEAD", method="POST")["id"]
        created.append(("id", rid))
        r = wait_ready(rid)
        check("clone repo status ready", r["status"], "ready")

        print("\n== metric oracle (clone path) ==")
        alice, bob = run_metric_checks(rid, r)

        print("\n== zip ingestion ==")
        shutil.make_archive(ZIP_PATH[:-4], "zip", FIXTURE)
        zid = upload_zip(ZIP_PATH, "oracle-zip")["id"]
        created.append(("id", zid))
        check("zip repo status ready", wait_ready(zid)["status"], "ready")
        m = metric(zid)
        check("zip repo totals identical",
              (m["metric"]["added"], m["metric"]["removed"],
               m["metric"]["churn"], m["set"]["count"]), (16, 7, 23, 9))

        print("\n== manual author merge (Bob -> Alice) ==")
        api(f"/api/repos/{rid}/authors/merge", method="POST",
            body=[alice["id"], bob["id"]])
        authors = api(f"/api/repos/{rid}/authors")
        check("after merge: single author", len(authors), 1)
        check("after merge: churn 23, ownership 1.0",
              (authors[0]["churn"], authors[0]["ownership"]), (23, 1.0))
        detail = api(f"/api/repos/{rid}")
        check("merged author flagged canonical",
              next(a["canonical_id"] for a in detail["authors"]
                   if a["id"] == bob["id"]), alice["id"])

        print("\n== ingestion error handling ==")
        bad_dir = os.path.join(HERE, "_badzip")
        os.makedirs(bad_dir, exist_ok=True)
        with open(os.path.join(bad_dir, "x.txt"), "w") as f:
            f.write("no git here\n")
        bad_zip = os.path.join(HERE, "_bad.zip")
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.write(os.path.join(bad_dir, "x.txt"), "x.txt")
        try:
            upload_zip(bad_zip, "oracle-badzip")
            check("zip without .git rejected", "no exception", "HTTP 400")
        except (AssertionError, urllib.error.HTTPError) as e:
            check("zip without .git rejected",
                  "HTTP 400" if "400" in str(e) else str(e), "HTTP 400")
        created.append(("name", "oracle-badzip"))

        try:
            api("/api/repos/clone?url=ftp%3A%2F%2Fbad.example%2Fx.git",
                method="POST")
            check("invalid URL scheme rejected", "no exception", "HTTP 400")
        except AssertionError as e:
            check("invalid URL scheme rejected",
                  "HTTP 400" if "HTTP 400" in str(e) else str(e), "HTTP 400")

        bid = api("/api/repos/clone?url=file%3A%2F%2F%2Fnonexistent-git-dir"
                  "&name=oracle-badclone", method="POST")["id"]
        created.append(("id", bid))
        check("unreachable clone -> status error",
              wait_ready(bid)["status"], "error")

        # retry re-attempts the failed job
        check("retry endpoint returns ok",
              api(f"/api/repos/{bid}/retry", method="POST")["ok"], True)
        check("retry re-attempts and fails again",
              wait_ready(bid)["status"], "error")

        # empty repository -> friendly error instead of a git crash
        empty_dir = os.path.join(HERE, "_empty")
        os.makedirs(empty_dir, exist_ok=True)
        subprocess.run(["git", "init", "-b", "main", "-q"], cwd=empty_dir,
                       check=True)
        eid = api("/api/repos/clone?url=" +
                  urllib.parse.quote("file://" + empty_dir) +
                  "&name=oracle-empty", method="POST")["id"]
        created.append(("id", eid))
        r = wait_ready(eid)
        check("empty repo -> error with friendly message",
              (r["status"], "no commits" in (r["error"] or "")),
              ("error", True))
        shutil.rmtree(empty_dir, ignore_errors=True)

    finally:
        print("\n== cleanup ==")
        for kind, val in created:
            if kind == "id":
                api(f"/api/repos/{val}", method="DELETE")
            else:
                for r in api("/api/repos"):
                    if r["name"] == val:
                        api(f"/api/repos/{r['id']}", method="DELETE")
        for p in (ZIP_PATH, os.path.join(HERE, "_bad.zip")):
            if os.path.exists(p):
                os.unlink(p)
        shutil.rmtree(os.path.join(HERE, "_badzip"), ignore_errors=True)
        shutil.rmtree(FIXTURE, ignore_errors=True)

    passed = sum(1 for ok, *_ in CHECKS if ok)
    print(f"\n{passed}/{len(CHECKS)} checks passed")
    sys.exit(0 if passed == len(CHECKS) else 1)


if __name__ == "__main__":
    main()
