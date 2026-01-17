from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

LOGGER = logging.getLogger("github_mcp")
logging.basicConfig(level=logging.INFO)

def get_db_mode() -> str:
    """
    Determine DB_MODE with priority:
    1. If .env has DB_MODE=sqlite, use sqlite
    2. Otherwise, if DB_MODE is set in environment variables, use that
    3. Otherwise, default to postgres
    """
    # First, check .env file directly for DB_MODE=sqlite
    env_path = Path(__file__).parent / "secrets.env"
    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if not line or line.startswith("#"):
                        continue
                    # Check for DB_MODE=sqlite
                    if "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key == "DB_MODE" and value.lower() == "sqlite":
                            return "sqlite"
        except Exception:
            # If we can't read the file, continue with environment check
            pass
    
    # If .env doesn't have DB_MODE=sqlite, check environment variables
    env_db_mode = os.environ.get("DB_MODE", "").lower()
    if env_db_mode:
        return env_db_mode
    
    # Default to postgres
    return "postgres"

def get_database_url() -> Optional[str]:
    return os.environ.get("DATABASE_URL")

# =========================
# ENV HELPERS (DYNAMIC)
# =========================

SQLITE_PATH = Path(os.environ.get("SQLITE_DB_PATH", "github_mcp.db"))

# =========================
# SQL ADAPTER
# =========================

def adapt_sql(sql: str) -> str:
    """
    Converts %s placeholders to ? for SQLite automatically.
    """
    if get_db_mode() == "sqlite":
        return sql.replace("%s", "?")
    return sql

# =========================
# CONNECTION
# =========================

def connect():
    db_mode = get_db_mode()
    database_url = get_database_url()

    LOGGER.info(f"CONNECT DB_MODE: {db_mode}")

    if db_mode == "postgres":
        if not psycopg2:
            raise RuntimeError("psycopg2 not installed")

        if not database_url:
            raise RuntimeError("DATABASE_URL not set for Postgres mode")

        LOGGER.info("Connecting to Supabase Postgres...")
        conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
        
        # Ensure search_path is set to public explicitly
        # This is important for connection pooling (Supabase Pooler) where
        # the search_path from connection string options might not persist
        try:
            with conn.cursor() as cur:
                cur.execute("SET search_path TO public")
            # Note: SET is session-level, no commit needed
        except Exception as e:
            LOGGER.warning(f"Could not set search_path: {e}")
        
        return conn

    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOGGER.warning("⚠️ Using local SQLite DB at %s", SQLITE_PATH)

    conn = sqlite3.connect(SQLITE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

# =========================
# SCHEMA (SQLite)
# =========================

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS repos (
    user_name TEXT NOT NULL,
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
    PRIMARY KEY (user_name, repo)
);

CREATE TABLE IF NOT EXISTS commits (
    user_name TEXT NOT NULL,
    repo TEXT NOT NULL,
    sha TEXT NOT NULL,
    authored_at TEXT,
    message TEXT,
    author_name TEXT,
    author_login TEXT,
    files_changed INTEGER,
    additions INTEGER,
    deletions INTEGER,
    PRIMARY KEY (user_name, repo, sha)
);

CREATE TABLE IF NOT EXISTS repo_signals (
    user_name TEXT NOT NULL,
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
    PRIMARY KEY (user_name, repo)
);

CREATE TABLE IF NOT EXISTS repo_text_files (
    user_name TEXT NOT NULL,
    repo TEXT NOT NULL,
    path TEXT NOT NULL,
    extension TEXT,
    content TEXT,
    PRIMARY KEY (user_name, repo, path)
);

CREATE TABLE IF NOT EXISTS users (
    user_name TEXT PRIMARY KEY,
    last_ingested_at TEXT,
    status TEXT DEFAULT 'ready',
    repo_count INTEGER DEFAULT 0,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_repos_user_pushed
ON repos(user_name, pushed_at DESC);
"""

def init_schema(conn):
    if get_db_mode() == "postgres":
        # Postgres schema is managed externally (tables already exist)
        # Just verify connection works
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            LOGGER.info("Postgres connection verified (schema managed externally)")
        except Exception as e:
            LOGGER.warning(f"Postgres connection check failed: {e}")
        return

    LOGGER.info("Initializing SQLite schema...")
    conn.executescript(SCHEMA_SQL)
    conn.commit()

# =========================
# DB HELPERS
# =========================

def upsert(conn, sql: str, params: tuple[Any, ...]) -> None:
    if get_db_mode() == "postgres":
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    else:
        sql = adapt_sql(sql)
        conn.execute(sql, params)
        conn.commit()


def fetchall(conn, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    if get_db_mode() == "postgres":
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    else:
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def fetchone(conn, sql: str, params: tuple[Any, ...] = ()) -> Optional[dict[str, Any]]:
    if get_db_mode() == "postgres":
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    else:
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None