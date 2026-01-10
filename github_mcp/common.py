from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

LOGGER = logging.getLogger("github_mcp")
logging.basicConfig(level=logging.INFO)

# DB mode: sqlite (local) or postgres (Render/Supabase)
DB_MODE = os.getenv("DB_MODE", "sqlite").lower()
DATABASE_URL = os.getenv("DATABASE_URL")

DEFAULT_DB_DIR = Path(os.environ.get("GITHUB_MCP_DATA_DIR", Path.home() / ".github_mcp"))

SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS repos (
    user TEXT NOT NULL,
    repo TEXT NOT NULL,
    default_branch TEXT,
    description TEXT,
    language TEXT,
    html_url TEXT,
    readme_text TEXT,
    last_ingested_at TEXT,
    pushed_at TEXT,
    created_at TEXT,
    updated_at TEXT,
    stargazers_count INTEGER DEFAULT 0,
    forks_count INTEGER DEFAULT 0,
    watchers_count INTEGER DEFAULT 0,
    open_issues_count INTEGER DEFAULT 0,
    size INTEGER DEFAULT 0,
    topics TEXT,
    license_name TEXT,
    is_archived INTEGER DEFAULT 0,
    is_fork INTEGER DEFAULT 0,
    PRIMARY KEY (user, repo)
);

CREATE TABLE IF NOT EXISTS commits (
    user TEXT NOT NULL,
    repo TEXT NOT NULL,
    sha TEXT NOT NULL,
    authored_at TEXT,
    message TEXT,
    author_name TEXT,
    author_login TEXT,
    files_changed INTEGER,
    additions INTEGER,
    deletions INTEGER,
    diff_summary TEXT,
    PRIMARY KEY (user, repo, sha)
);

CREATE TABLE IF NOT EXISTS repo_signals (
    user TEXT NOT NULL,
    repo TEXT NOT NULL,
    has_tests INTEGER,
    has_github_actions INTEGER,
    has_ci_config INTEGER,
    has_lint_config INTEGER,
    has_precommit INTEGER,
    has_dockerfile INTEGER,
    has_docker_compose INTEGER DEFAULT 0,
    has_makefile INTEGER,
    detected_test_framework TEXT,
    detected_ci TEXT,
    has_code_of_conduct INTEGER DEFAULT 0,
    has_contributing INTEGER DEFAULT 0,
    has_license INTEGER DEFAULT 0,
    has_security_policy INTEGER DEFAULT 0,
    has_issue_templates INTEGER DEFAULT 0,
    has_pr_templates INTEGER DEFAULT 0,
    has_changelog INTEGER DEFAULT 0,
    has_docs INTEGER DEFAULT 0,
    organization_score REAL DEFAULT 0.0,
    coding_standards_score REAL DEFAULT 0.0,
    automation_score REAL DEFAULT 0.0,
    tech_stack TEXT,
    signals_json TEXT,
    PRIMARY KEY (user, repo)
);
"""


def ensure_db_dir() -> Path:
    DEFAULT_DB_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_DB_DIR


def get_db_path(user: str) -> Path:
    ensure_db_dir()
    safe = user.strip().replace("/", "_")
    return DEFAULT_DB_DIR / f"{safe}.db"


def connect(user: Optional[str] = None):
    """
    Returns either:
    - sqlite3 connection (local)
    - psycopg2 connection (Supabase/Postgres)
    """
    if DB_MODE == "postgres":
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL not set for Postgres mode")

        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        return conn

    # Default: SQLite
    db_path = get_db_path(user or "default")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn):
    cur = conn.cursor()
    for stmt in SCHEMA_SQL.split(";"):
        if stmt.strip():
            cur.execute(stmt)
    conn.commit()


def upsert(conn, sql: str, params: tuple[Any, ...]):
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()


def fetchall(conn, sql: str, params: tuple[Any, ...] = ()):
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur.fetchall()


def fetchone(conn, sql: str, params: tuple[Any, ...] = ()):
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    return row