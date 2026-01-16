from datetime import datetime, timezone
from typing import Optional

from .common import connect, upsert, fetchone, LOGGER


def upsert_user(
    user_name: str,
    repo_count: int = 0,
    status: str = "pending",
    error: Optional[str] = None
):
    """
    Insert or update a GitHub user ingestion record.
    """

    conn = connect()

    now = datetime.now(timezone.utc).isoformat()

    sql = """
    INSERT INTO users (user_name, last_ingested_at, repo_count, status, error)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (user_name) DO UPDATE SET
        last_ingested_at = EXCLUDED.last_ingested_at,
        repo_count = EXCLUDED.repo_count,
        status = EXCLUDED.status,
        error = EXCLUDED.error;
    """

    params = (user_name, now, repo_count, status, error)

    upsert(conn, sql, params)

    LOGGER.info("User record updated: %s (status=%s)", user_name, status)


def get_user(user_name: str):
    conn = connect()

    sql = "SELECT * FROM users WHERE user_name = %s"
    return fetchone(conn, sql, (user_name,))