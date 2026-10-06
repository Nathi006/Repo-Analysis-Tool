# RAT (Repo Analysis Tool) — Implementation Plan

**Test:** COMS3011A · **Hard time budget:** ~2 hours (brief allows 2.5 h → 30 min contingency)
**Submission:** URL to a public repository (this repo, pushed publicly)
**Rule:** This document is the source of truth. Implement exactly what it says, in phase order.

---

## 1. Brief Analysis & Target

### 1.1 What we are building

A web-app dashboard that accepts git repositories (zip file containing `.git`, or a remote URL that gets a full clone), extracts metrics, and lets a user filter by **repository**, **author**, **file/directory**, and **commit set** (time range from→to on committer date, or a manually selected list of commits).

### 1.2 Metric categories required

| Category | Metrics |
|---|---|
| File | added lines, removed lines, growth (added − removed), churn (added + removed) — per commit |
| Directory | same four, aggregated over **immediate children** (recursively = full subtree sum), per commit |
| Repository | directory metrics on the root |
| Commit set | sums of added/removed/growth/churn over the set; modifications (commits touching object); modification frequency (n/|H|); churn rate (λ/|H|) |
| Author | author modifications, author churn, author ownership (author churn / total churn), per object |

### 1.3 Semantics we must honor (from the brief)

- **H̄** = non-merge commits reachable from reference commit h_r (default HEAD). Use `git log --no-merges <h_r>`.
- **Commit sets**: H_t = commits with `committer-date ≥ t`; H_i,j = `i ≤ committer-date < j` (inclusive start, exclusive end); manual = user-picked commit list. Filters AND together.
- **Binary files are not measured** — use git's own binary detection (`--numstat` emits `-`); skip those rows entirely.
- **Rename detection at 50%** (`-M50%`): pure rename contributes nothing; rename + edit attributes changes to the **new path**. Using git's own `-M50%` numstat output gives this for free.
- **Deleted objects** still record their removed lines on their path (numstat reports deletes; we must not drop them).
- **Author merging**: apply `.mailmap` (`--use-mailmap`), plus manual merging in the UI.
- **H[F]/H[D]**: union of snapshot file/dir sets over the commit set (including parents of the set's commits) — a file deleted mid-set still appears with its removed lines. Implementation shortcut in §6.3.
- **Initial commit** has an empty parent — numstat vs empty tree naturally reports all lines as added. No special-casing.
- **Every commit has exactly one author** (after merging), so author metrics = commit-set metrics filtered by author.

### 1.4 Rubric mapping (target: 100% requirements tier)

Requirements are **cumulative**; target the full 100% column:

| Tier | Required | Effort |
|---|---|---|
| ≤25% | Some categories correct; one ingestion method | baseline |
| ≤50% | **All** metrics correct; **both** zip + URL ingestion | core |
| ≤75% | One of: Filtering / Author Merge / Multi-repo + decent UX | cheap once core exists |
| ≤100% | **All three** of Filtering, Author Merge, Multi-repo + efficient algorithms + strong UI | doable in budget |

Since filtering and multi-repo fall out of the DB design nearly for free, we implement everything. **Fallback ladder if time runs short** (cut in this order, each cut costs one rubric tier):
1. Manual author-merge UI (keep mailmap — it's automatic)
2. Manual commit selection (keep time-range filtering)
3. Timeseries/ownership charts (keep tables)

---

## 2. Recommended Tech Stack

### 2.1 Primary (RECOMMENDED)

| Layer | Choice | Why |
|---|---|---|
| Backend | **Python 3.12 + FastAPI + uvicorn** | Fastest framework to write correct async CRUD + background jobs; auto OpenAPI docs aid debugging |
| Git access | **`git` CLI via subprocess** (NOT GitPython/NodeGit/go-git) | Correctness is graded against git's own output. `git log --numstat -M50% --use-mailmap` is the *definition* of the metrics. C-speed for large repos. |
| Storage | **SQLite (stdlib `sqlite3`)** | Zero config, single file, indexed GROUP BY queries are fast enough for 100k commits; WAL mode + batch inserts |
| Frontend | **Vanilla HTML/CSS/JS + Chart.js 4 (CDN)** | No build step, no node_modules — critical for a 2 h budget. Fetch + template rendering |
| Dependencies | `fastapi`, `uvicorn`, `python-multipart` only | Everything else is stdlib (`zipfile`, `subprocess`, `json`, `sqlite3`) |

**Rationale:** every hard correctness requirement (binary detection, −M50% renames, mailmap, committer timestamps) is satisfied by delegating to git itself. Everything else is standard. This stack minimizes both correctness risk and development time.

### 2.2 Alternatives (rejected)

- **Node + Express + simple-git + React**: simple-git parses porcelain outputs awkwardly for `-M` renames; React/Vite build overhead eats the budget.
- **Go + go-git + embedded UI**: go-git is pure-Go and fast, but its rename detection and mailmap support don't track `git log` semantics exactly; slower to iterate in 2 h.
- **GitPython**: wrapper over git CLI but with awkward rename/mailmap plumbing and slower bulk parsing; subprocess streaming is simpler and faster.

### 2.3 Project layout

```
repo-analysis-tool/
├── README.md                 # submission doc: features, run steps, screenshot, AI declaration
├── requirements.txt          # fastapi, uvicorn, python-multipart
├── run.sh                    # uvicorn backend.main:app --port 8000
├── data/                     # gitignored: rat.db + repos/<id>/
├── backend/
│   ├── main.py               # FastAPI app, static file serving, startup
│   ├── db.py                 # connection, schema, WAL pragmas
│   ├── ingest.py             # zip upload / clone, background task + progress state
│   ├── extract.py            # git log → authors/commits/file_stats/dir_stats/paths
│   ├── metrics.py            # all metric queries (file/dir/repo/set/author)
│   └── api.py                # REST routes
├── frontend/
│   ├── index.html
│   ├── app.js
│   └── style.css
└── tests/
    └── make_synthetic_repo.py  # builds a tiny repo with hand-verifiable metrics
```

---

## 3. Architecture

```
Upload zip / paste URL ──► ingest.py (background task, progress polled)
                               │  zip → extract to data/repos/<id>/
                               │  url → git clone (full, not shallow) to data/repos/<id>/
                               ▼
                        extract.py  ──►  git log --no-merges -M50% --use-mailmap
                               │           (streamed, parsed incrementally)
                               ▼
                        SQLite rat.db  (WAL, batch executemany, indexed)
                               ▲
metrics.py (pure SQL GROUP BY) │
                               ▼
                        api.py (FastAPI JSON)
                               ▼
                        frontend (vanilla JS + Chart.js) — filters drive query params
```

**Key performance decision:** per-commit **directory aggregates are precomputed at ingestion time** (each changed file's stats bubble up through every ancestor path prefix, stored in `dir_stats`). This makes every later filter query a simple indexed GROUP BY — required for "good performance on ~100000-commit repos". No per-request git calls ever.

**Ingestion runs once per repo, in the background**, with a polling progress endpoint. All dashboard queries are pure SQL.

---

## 4. Database Schema (SQLite)

```sql
PRAGMA journal_mode=WAL;

repos(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,            -- sanitized display/slug name
  kind TEXT NOT NULL,            -- 'zip' | 'clone'
  source TEXT,                   -- original URL or zip filename
  head_ref TEXT DEFAULT 'HEAD',  -- reference commit h_r used at extraction
  status TEXT DEFAULT 'pending', -- pending|cloning|extracting|ready|error
  error TEXT,
  created_at REAL
);

authors(
  id INTEGER PRIMARY KEY,
  repo_id INTEGER REFERENCES repos(id),
  name TEXT, email TEXT,         -- post-mailmap identity from --use-mailmap
  canonical_id INTEGER,          -- manual merge: points at canonical author row
  UNIQUE(repo_id, name, email)
);

commits(
  id INTEGER PRIMARY KEY,
  repo_id INTEGER REFERENCES repos(id),
  hash TEXT, author_id INTEGER, committer_ts INTEGER,  -- UNIX, %ct
  UNIQUE(repo_id, hash)
);
CREATE INDEX ix_commits_repo_ts ON commits(repo_id, committer_ts);

file_stats(                     -- one row per (commit, changed file) from numstat
  commit_id INTEGER REFERENCES commits(id),
  path TEXT, added INTEGER, removed INTEGER,
  PRIMARY KEY(commit_id, path)
);
CREATE INDEX ix_file_path ON file_stats(path);

dir_stats(                      -- precomputed: per-commit subtree aggregates
  commit_id INTEGER REFERENCES commits(id),
  path TEXT,                    -- '' = root = repository metrics
  added INTEGER, removed INTEGER,
  PRIMARY KEY(commit_id, path)
);
CREATE INDEX ix_dir_path ON dir_stats(path);

paths(                          -- H[F]/H[D] existence info for the tree UI
  repo_id INTEGER, path TEXT, kind TEXT,   -- 'file' | 'dir'
  first_ts INTEGER, last_ts INTEGER,       -- touched range; NULL last = still present
  PRIMARY KEY(repo_id, path, kind)
);
```

Binary files produce **no rows** in `file_stats`/`dir_stats`. Renames produce a row on the new path (possibly 0/0). Deletes produce a row on the old path with `removed > 0`.

---

## 5. Metric Computation Spec

All formulas below are computed **in SQL** over `file_stats`/`dir_stats` joined to a commit-set CTE.

### 5.1 Extraction pipeline (`extract.py`)

One streamed command per repo (h_r = repo.head_ref):

```
git -C <repo> log --no-merges --topo-order -M50% --use-mailmap <h_r> \
    --format=%x1e%H%x1f%ct%x1f%aN%x1f%aE --numstat
```

- `%x1e` = record separator, `%x1f` = field separator (control chars never appear in names/hashes → unambiguous parsing even with spaces/newlines in author names).
- Parse incrementally; skip `-`/`-` binary lines; batch-insert with `executemany` every ~10k rows.
- After each commit's files are collected, compute ancestor-prefix aggregation **in Python** and insert into `dir_stats` (root path `''` always gets a row). This is the single O(total changed files × path depth) pass.
- Maintain `paths` table: first/last touched timestamps; after extraction, union in `git ls-tree -r --name-only <h_r>` so currently-present-but-untouched files appear in the tree UI with NULL `last_ts`.
- Count rows to drive progress (repos can expose `git rev-list --count` upfront for a progress bar).

### 5.2 Commit-set membership (SQL CTE, reused everywhere)

```
set_cte = SELECT id FROM commits
          WHERE repo_id = :rid
            AND (from IS NULL OR committer_ts >= :from)
            AND (to   IS NULL OR committer_ts <  :to)          -- exclusive end
            AND (manual list empty OR hash IN (...))           -- AND with time filter
```

`|H|` = `COUNT(*)` of this CTE — feeds frequency `η = n/|H|` and churn rate `ρ = λ/|H|`.

### 5.3 Metric definitions → implementation

**Per-object (file, directory, repository = dir path `''`):**

| Metric | Definition | SQL |
|---|---|---|
| added | Σ l⁺ over H | `SUM(added)` from `file_stats` (path = :p) or `dir_stats` (path = :p) JOIN set_cte |
| removed | Σ l⁻ over H | `SUM(removed)` likewise |
| growth | added − removed | derived in code |
| churn λ | added + removed | derived in code |
| modifications n | commits where λ_h,o > 0 | `COUNT(*) WHERE added+removed > 0` |
| frequency η | n / |H| (0 if |H| = 0) | derived in code |
| churn rate ρ | λ / |H| (0 if |H| = 0) | derived in code |

**Per-author on object o** (one query, GROUP BY canonical author):

| Metric | Definition | SQL |
|---|---|---|
| author modifications | Σ I(a,h)·Iₙ(h,o) | `COUNT(*) WHERE added+removed>0 GROUP BY canonical` |
| author churn λ_H,o,a | Σ λ_h,o·I(a,h) | `SUM(added+removed) GROUP BY canonical` |
| ownership ω | λ_H,o,a / λ_H,o (0 if λ_H,o = 0) | derived in code |

Canonical author = `COALESCE(canonical_id, id)`; mailmap already applied at extraction, manual merges set `canonical_id`.

**Aggregate views** (tables/lists): GROUP BY path (top files/dirs by churn), GROUP BY author (author leaderboard), and a timeseries `GROUP BY committer_ts / bucket` from `dir_stats` (root) for charts.

### 5.4 Edge cases checklist (correctness)

- [ ] Binary files excluded everywhere (including modification counts)
- [ ] Pure rename (0/0 on new path): no metric change, no modification count
- [ ] Rename + edit: counts land on new path; old path gets nothing
- [ ] Deleted file: removed lines counted on old path; file still selectable in tree (via `paths`)
- [ ] Initial commit: all lines added vs empty parent
- [ ] Directory aggregation = subtree sum (immediate-child recursion), root = repository
- [ ] |H| = 0 → η, ρ = 0 (no div-by-zero)
- [ ] Time window is [i, j) on **committer** date
- [ ] Merges excluded from H̄; mailmap applied; manual merge redirects all queries

---

## 6. API Design (FastAPI)

```
GET  /api/repos                          → repo list + status/progress/error
POST /api/repos/upload  (multipart file) → {id}   (zip must contain .git — else 400)
POST /api/repos/clone   (json url, name?, ref?)   → {id}
GET  /api/repos/{id}                     → detail: head, commit count, first/last ts, authors
POST /api/repos/{id}/authors/merge  (json ids:[])  → merge into canonical (lowest id)
GET  /api/repos/{id}/commits?q=&limit=   → [{hash, subject, ts, author}] for manual selection
GET  /api/repos/{id}/tree               → nested H[F]/H[D] tree with per-path churn
GET  /api/repos/{id}/metrics
       ?from=&to=&commits=hash1,hash2&authors=ids&path=&kind=file|dir
       → { set:{count,from,to}, metric:{added,removed,growth,churn,modifications,frequency,churn_rate},
           authors:[{name,modifications,churn,ownership}] }
GET  /api/repos/{id}/timeseries?bucket=day|week|month&from=&to=&authors=&path=
       → [{t, churn, added, removed}] for the line chart
GET  /api/repos/{id}/leaders?kind=file|dir|author&limit=50  → sortable-table data
```

- `kind=dir`/`path` selection: file vs directory determined by the tree node clicked; directory path queried from `dir_stats`.
- Ingestion = `BackgroundTask`; progress in an in-memory dict `{stage, done, total}` returned in `/api/repos`.

---

## 7. UI Design (single page, no framework)

**Layout:**
- **Left sidebar**: repo list with status badges; "Upload zip" and "Add from URL" buttons (with optional ref/hash input); remove repo.
- **Top filter bar**: author multi-select (searchable, shows commit counts), date range (from/to date inputs → UNIX ts), "select commits manually" toggle opening a searchable commit checklist, path filter (searchable tree of H[F]/H[D]).
- **Main tabs**: Overview · Files · Directories · Authors · Commit set.
  - **Overview**: repository metric cards (added/removed/growth/churn/modifications/frequency/churn-rate), churn-over-time line chart, ownership doughnut (top 8 + "other").
  - **Files/Directories**: sortable, searchable tables (path, added, removed, growth, churn, modifications, churn rate, top owner + ownership %); clicking a row drills into that object as the path filter.
  - **Authors**: table (author, commits, modifications, churn, ownership) + **merge workflow**: check ≥2 authors → "Merge" → POST merge.
  - **Commit set**: summary of current set (count, ts range) + manual selection list.
- **QoL (usability marks)**: loading spinners, toast errors (bad zip, clone failure), empty states, debounced search, sortable columns, sticky filter bar, progress bar during ingestion.

Charts via Chart.js 4 CDN. All state in one JS object `{repoId, filters}`; every change re-fetches `/api/repos/{id}/metrics` + `/timeseries` + `/leaders`.

---

## 8. Implementation Phases (2 h, time-boxed)

### Phase 0 — Scaffold & plumbing (5 min)
- [ ] git init (already), README stub, requirements.txt, run.sh, .gitignore (data/, __pycache__)
- [ ] FastAPI hello world serving `frontend/index.html` + static files; verify server runs

### Phase 1 — Ingestion & extraction (25 min) — *critical path*
- [ ] db.py: schema above, WAL, connection helper
- [ ] ingest.py: zip upload (zipfile, find `.git`, extract), clone (`git clone --progress`), background task + progress state
- [ ] extract.py: stream `git log --numstat -M50% --use-mailmap` with RS/US separators → authors/commits/file_stats; ancestor-prefix aggregation → dir_stats; paths table + `ls-tree` union
- [ ] Manual smoke: ingest this repo itself (small) end-to-end via curl

### Phase 2 — Metrics engine + API (20 min)
- [ ] metrics.py: set CTE builder + the queries of §5.3; leaders; timeseries
- [ ] api.py: all routes from §6 with validation and error responses
- [ ] Author merge endpoint (canonical_id update)

### Phase 3 — Frontend dashboard (35 min)
- [ ] index.html/style.css: sidebar, filter bar, tab skeleton
- [ ] Repo add/upload/clone flows with progress polling
- [ ] Filters (author, dates, path tree, manual commits) wired to `/metrics`
- [ ] Tables (files/dirs/authors) with sorting + search; Overview cards + two charts

### Phase 4 — Author merge & manual commit selection UI (10 min)
- [ ] Author merge checklist workflow
- [ ] Manual commit checklist + set summary tab

### Phase 5 — Verification, performance, polish (25 min)
- [ ] tests/make_synthetic_repo.py: scripted repo (~6 commits: adds, edit, pure rename, rename+edit, delete, binary file) with **hand-computed expected metrics** → assert via API. This catches formula bugs fast.
- [ ] Cross-check cJSON vs raw `git log --numstat | awk` sums (file + directory + author)
- [ ] Ingest cJSON (must be seconds) and Redis (must be < ~1 min); ingest git/git.git once (~75k commits, expect a few minutes, background) and verify dashboard queries stay < 1 s
- [ ] Error handling pass: invalid zip, zip without .git, unreachable URL, dup repo names
- [ ] README: features, screenshots, run instructions, architecture blurb, AI declaration
- [ ] Push to public remote

**Buffer:** 30 min against the brief's 2.5 h allowance — spend any of it on the fallback-ladder items cut earlier.

---

## 9. Verification Plan (metric correctness)

1. **Synthetic repo** (Phase 5, hand-computed oracle) — must pass 100% before anything else.
2. **cJSON** (≈1k commits): compare our per-file sums and repo totals against direct `git log --numstat -M50% --no-merges` awk aggregation; verify a known commit hash's metrics.
3. **Redis** (≈14k commits): spot-check totals + measure ingestion/query time.
4. **git/git.git** (≈75k commits): perf gate only (ingestion one-time in background; queries < 1 s).
5. When graders provide "sample metrics from a specific commit hash", plug that hash in as `ref` and diff our output against the samples — the final correctness gate.

---

## 10. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Running out of time | Strict phase order; core metrics+ingestion first (guarantees 50% tier); fallback ladder §1.4 |
| Wrong rename/binary/mailmap semantics | Delegate everything to git CLI flags (`-M50%`, numstat, `--use-mailmap`); synthetic-repo oracle test |
| Slow on 75k-commit repo | Precomputed `dir_stats`, indexed GROUP BY, WAL, batch inserts, background ingestion |
| Zip without .git / broken clone | Validate early, clear toast errors, `status: error` in repo list |
| Commit-set window edge cases ([i,j), empty sets) | Centralized set CTE + explicit zero-division guards + synthetic tests |
| Frontend scope creep | Vanilla JS only, one page, Chart.js CDN; tables before charts |

---

## 11. Key Assumptions (rubric interpretation)

- "Binary files are not measured" ⇒ excluded from **all** metrics including modification counts.
- H̄ uses **committer date** for time windows; merges always excluded; default reference = HEAD, overridable per repo.
- Manual author merge is per-repo and maps to one canonical identity; mailmap is applied at extraction time.
- The tree UI shows H̄-wide H[F]/H[D] (superset of any subset's), with `first_ts`/`last_ts` so deleted files remain visible — safe because untouched files have zero metrics.
- Submission is judged by repo content (URL), so README + screenshot + clean run instructions matter.

---

## 12. Definition of Done

- [ ] All 4 metric categories + author metrics correct on the synthetic oracle and cJSON
- [ ] Zip upload **and** URL clone ingestion working, background + progress
- [ ] Multi-repo dashboard with repo list/status
- [ ] Filtering: repository, author, file/directory, time range, manual commit list
- [ ] Author merging: mailmap automatic + manual merge UI
- [ ] Redis ingests < 1 min; git/git.git ingests successfully; queries < 1 s
- [ ] Error handling + QoL (spinners, toasts, search, sorting) present
- [ ] README with screenshots and run instructions; repo pushed public
