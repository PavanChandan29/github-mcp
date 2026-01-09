from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

LOGGER = logging.getLogger("github_mcp")
logging.basicConfig(level=logging.INFO)

DEFAULT_DB_DIR = Path(os.environ.get("GITHUB_MCP_DATA_DIR", Path.home() / ".github_mcp"))
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "github_mcp.db"


def ensure_db_dir() -> Path:
    DEFAULT_DB_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_DB_DIR


def get_db_path(user: str) -> Path:
    """
    One DB per GitHub user to keep MCP instances cleanly separated.
    """
    ensure_db_dir()
    safe = user.strip().replace("/", "_")
    return DEFAULT_DB_DIR / f"{safe}.db"


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


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

CREATE INDEX IF NOT EXISTS idx_commits_repo_time
ON commits(user, repo, authored_at);

CREATE INDEX IF NOT EXISTS idx_repos_pushed_at
ON repos(user, pushed_at DESC);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    
    # Migrate existing databases: add new columns if they don't exist
    migration_columns_repos = [
        ("pushed_at", "TEXT"),
        ("created_at", "TEXT"),
        ("updated_at", "TEXT"),
        ("stargazers_count", "INTEGER DEFAULT 0"),
        ("forks_count", "INTEGER DEFAULT 0"),
        ("watchers_count", "INTEGER DEFAULT 0"),
        ("open_issues_count", "INTEGER DEFAULT 0"),
        ("size", "INTEGER DEFAULT 0"),
        ("topics", "TEXT"),
        ("license_name", "TEXT"),
        ("is_archived", "INTEGER DEFAULT 0"),
        ("is_fork", "INTEGER DEFAULT 0"),
    ]
    
    migration_columns_signals = [
        ("has_docker_compose", "INTEGER DEFAULT 0"),
        ("has_code_of_conduct", "INTEGER DEFAULT 0"),
        ("has_contributing", "INTEGER DEFAULT 0"),
        ("has_license", "INTEGER DEFAULT 0"),
        ("has_security_policy", "INTEGER DEFAULT 0"),
        ("has_issue_templates", "INTEGER DEFAULT 0"),
        ("has_pr_templates", "INTEGER DEFAULT 0"),
        ("has_changelog", "INTEGER DEFAULT 0"),
        ("has_docs", "INTEGER DEFAULT 0"),
        ("organization_score", "REAL DEFAULT 0.0"),
        ("coding_standards_score", "REAL DEFAULT 0.0"),
        ("automation_score", "REAL DEFAULT 0.0"),
        ("tech_stack", "TEXT"),
    ]
    
    for col_name, col_type in migration_columns_repos:
        try:
            conn.execute(f"ALTER TABLE repos ADD COLUMN {col_name} {col_type}")
            conn.commit()
        except sqlite3.OperationalError:
            # Column already exists, which is fine
            pass
    
    for col_name, col_type in migration_columns_signals:
        try:
            conn.execute(f"ALTER TABLE repo_signals ADD COLUMN {col_name} {col_type}")
            conn.commit()
        except sqlite3.OperationalError:
            # Column already exists, which is fine
            pass
    
    # Try to create index if it doesn't exist
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_repos_pushed_at ON repos(user, pushed_at DESC)")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    
    conn.commit()


def upsert(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> None:
    conn.execute(sql, params)
    conn.commit()


def fetchall(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cur = conn.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def fetchone(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Optional[dict[str, Any]]:
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    return dict(row) if row else None
