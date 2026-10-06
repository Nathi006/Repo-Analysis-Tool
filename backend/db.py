"""SQLite storage layer for RAT: schema, connection, small helpers."""
import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "rat.db"

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS repos(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  source TEXT,
  head_ref TEXT DEFAULT 'HEAD',
  status TEXT DEFAULT 'pending',
  error TEXT,
  created_at REAL
);

CREATE TABLE IF NOT EXISTS authors(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  repo_id INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  email TEXT NOT NULL,
  canonical_id INTEGER,
  UNIQUE(repo_id, name, email)
);

CREATE TABLE IF NOT EXISTS commits(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  repo_id INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  hash TEXT NOT NULL,
  author_id INTEGER NOT NULL REFERENCES authors(id),
  committer_ts INTEGER NOT NULL,
  subject TEXT,
  UNIQUE(repo_id, hash)
);
CREATE INDEX IF NOT EXISTS ix_commits_repo_ts ON commits(repo_id, committer_ts);
CREATE INDEX IF NOT EXISTS ix_commits_repo_author ON commits(repo_id, author_id);

CREATE TABLE IF NOT EXISTS file_stats(
  commit_id INTEGER NOT NULL REFERENCES commits(id) ON DELETE CASCADE,
  path TEXT NOT NULL,
  added INTEGER NOT NULL,
  removed INTEGER NOT NULL,
  PRIMARY KEY(commit_id, path)
);
CREATE INDEX IF NOT EXISTS ix_file_path ON file_stats(path);

CREATE TABLE IF NOT EXISTS dir_stats(
  commit_id INTEGER NOT NULL REFERENCES commits(id) ON DELETE CASCADE,
  path TEXT NOT NULL,
  added INTEGER NOT NULL,
  removed INTEGER NOT NULL,
  PRIMARY KEY(commit_id, path)
);
CREATE INDEX IF NOT EXISTS ix_dir_path ON dir_stats(path);

CREATE TABLE IF NOT EXISTS paths(
  repo_id INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  path TEXT NOT NULL,
  kind TEXT NOT NULL,
  first_ts INTEGER,
  last_ts INTEGER,
  PRIMARY KEY(repo_id, path, kind)
);
CREATE INDEX IF NOT EXISTS ix_paths_repo ON paths(repo_id);
"""


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
