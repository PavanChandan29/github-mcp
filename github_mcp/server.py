from __future__ import annotations

import argparse
import json
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from .common import LOGGER, connect, fetchall, fetchone, get_db_path, init_schema

# Initialize FastMCP server
mcp = FastMCP("github_mcp")


def _conn_for(user: str):
    db_path = get_db_path(user)
    conn = connect(db_path)
    init_schema(conn)
    return conn


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _loads_json_list(v: Any) -> list[Any]:
    """Safely parse JSON that should represent a list; returns [] on failure."""
    if not v:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            out = json.loads(v)
            return out if isinstance(out, list) else []
        except Exception:
            return []
    return []


def _loads_json_obj(v: Any) -> dict[str, Any]:
    """Safely parse JSON that should represent an object; returns {} on failure."""
    if not v:
        return {}
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            out = json.loads(v)
            return out if isinstance(out, dict) else {}
        except Exception:
            return {}
    return {}


def _normalize_repo_row(r: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize DB row → stable, tool-friendly schema.
    Also ensures 'repo' and 'name' both exist to reduce downstream confusion.
    """
    out = dict(r or {})
    # topics stored as JSON text in DB
    out["topics"] = _loads_json_list(out.get("topics"))
    # Provide both keys so the agent doesn't break if it expects 'name'
    if "repo" in out and "name" not in out:
        out["name"] = out["repo"]
    if "name" in out and "repo" not in out:
        out["repo"] = out["name"]
    return out


# ============================================================
# Core Tools (Single-Repo / Listing)
# ============================================================

@mcp.tool()
async def list_repos(user: str) -> list[dict[str, Any]]:
    """
    List repositories ingested for a GitHub user, ordered by most recently pushed first.

    Returns: list of repos with metadata.
    """
    conn = _conn_for(user)
    rows = fetchall(
        conn,
        """
        SELECT
          repo,
          description,
          language,
          html_url,
          pushed_at,
          created_at,
          updated_at,
          stargazers_count,
          forks_count,
          watchers_count,
          open_issues_count,
          size,
          topics,
          license_name,
          is_archived,
          is_fork
        FROM repos
        WHERE user=?
        ORDER BY pushed_at DESC, repo
        """,
        (user,),
    )
    return [_normalize_repo_row(r) for r in (rows or [])]


@mcp.tool()
async def get_repo_overview(user: str, repo: str) -> dict[str, Any]:
    """
    Get comprehensive repository information including metadata and engineering signals.

    Args:
      user: GitHub username
      repo: repository name
    """
    conn = _conn_for(user)

    r = fetchone(conn, "SELECT * FROM repos WHERE user=? AND repo=?", (user, repo))
    if not r:
        return {"error": f"Repo not found in MCP store: {user}/{repo}. Run ingestion first."}

    s = fetchone(conn, "SELECT * FROM repo_signals WHERE user=? AND repo=?", (user, repo)) or {}

    topics = _loads_json_list(r.get("topics"))

    commit_count_row = fetchone(
        conn,
        "SELECT COUNT(*) as count FROM commits WHERE user=? AND repo=?",
        (user, repo),
    ) or {}
    commit_count = _safe_int(commit_count_row.get("count", 0), 0)

    overview = {
        "repo": repo,
        "description": r.get("description", "") or "",
        "language": r.get("language", "") or "",
        "html_url": r.get("html_url", "") or "",
        "default_branch": r.get("default_branch", "") or "",
        "created_at": r.get("created_at", "") or "",
        "updated_at": r.get("updated_at", "") or "",
        "pushed_at": r.get("pushed_at", "") or "",
        "last_ingested_at": r.get("last_ingested_at", "") or "",
        "readme_text": r.get("readme_text", "") or "",
        "achievements": {
            "stars": _safe_int(r.get("stargazers_count", 0), 0),
            "forks": _safe_int(r.get("forks_count", 0), 0),
            "watchers": _safe_int(r.get("watchers_count", 0), 0),
            "open_issues": _safe_int(r.get("open_issues_count", 0), 0),
            "commits": commit_count,
        },
        "metadata": {
            "size": _safe_int(r.get("size", 0), 0),
            "topics": topics,
            "license": r.get("license_name") or None,
            "is_archived": bool(_safe_int(r.get("is_archived", 0), 0)),
            "is_fork": bool(_safe_int(r.get("is_fork", 0), 0)),
        },
        "automation": {
            "has_github_actions": bool(_safe_int(s.get("has_github_actions", 0), 0)),
            "has_ci_config": bool(_safe_int(s.get("has_ci_config", 0), 0)),
            "has_precommit": bool(_safe_int(s.get("has_precommit", 0), 0)),
            "has_dockerfile": bool(_safe_int(s.get("has_dockerfile", 0), 0)),
            "has_docker_compose": bool(_safe_int(s.get("has_docker_compose", 0), 0)),
            "has_makefile": bool(_safe_int(s.get("has_makefile", 0), 0)),
            "detected_ci": (s.get("detected_ci") or None),
            "automation_score": _safe_float(s.get("automation_score", 0.0), 0.0),
        },
        "coding_standards": {
            "has_tests": bool(_safe_int(s.get("has_tests", 0), 0)),
            "has_lint_config": bool(_safe_int(s.get("has_lint_config", 0), 0)),
            "has_precommit": bool(_safe_int(s.get("has_precommit", 0), 0)),
            "has_ci_config": bool(_safe_int(s.get("has_ci_config", 0), 0)),
            "detected_test_framework": (s.get("detected_test_framework") or None),
            "coding_standards_score": _safe_float(s.get("coding_standards_score", 0.0), 0.0),
        },
        "organization": {
            "has_code_of_conduct": bool(_safe_int(s.get("has_code_of_conduct", 0), 0)),
            "has_contributing": bool(_safe_int(s.get("has_contributing", 0), 0)),
            "has_license": bool(_safe_int(s.get("has_license", 0), 0)),
            "has_security_policy": bool(_safe_int(s.get("has_security_policy", 0), 0)),
            "has_issue_templates": bool(_safe_int(s.get("has_issue_templates", 0), 0)),
            "has_pr_templates": bool(_safe_int(s.get("has_pr_templates", 0), 0)),
            "has_changelog": bool(_safe_int(s.get("has_changelog", 0), 0)),
            "has_docs": bool(_safe_int(s.get("has_docs", 0), 0)),
            "organization_score": _safe_float(s.get("organization_score", 0.0), 0.0),
        },
        # A stable location for “stack + key signals” so the agent can reliably cite it.
        "signals": {
            "tech_stack": (s.get("tech_stack") or ""),
            "has_ci_config": bool(_safe_int(s.get("has_ci_config", 0), 0)),
            "has_tests": bool(_safe_int(s.get("has_tests", 0), 0)),
            "has_dockerfile": bool(_safe_int(s.get("has_dockerfile", 0), 0)),
            "has_precommit": bool(_safe_int(s.get("has_precommit", 0), 0)),
            "detected_ci": (s.get("detected_ci") or None),
            "detected_test_framework": (s.get("detected_test_framework") or None),
        },
    }

    return overview


@mcp.tool()
async def get_commit_timeline(user: str, repo: str, limit: int = 50) -> list[dict[str, Any]]:
    """
    Return commit timeline (most recent first).

    Args:
      user: GitHub username
      repo: repository name
      limit: max commits
    """
    conn = _conn_for(user)
    return fetchall(
        conn,
        """
        SELECT sha, authored_at, message, author_name, author_login,
               files_changed, additions, deletions
        FROM commits
        WHERE user=? AND repo=?
        ORDER BY authored_at DESC
        LIMIT ?
        """,
        (user, repo, _safe_int(limit, 50)),
    ) or []


@mcp.tool()
async def search_readmes(user: str, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """
    Search README text across all repos (simple LIKE search).

    Args:
      user: GitHub username
      query: search string
      limit: max results
    """
    conn = _conn_for(user)
    q = f"%{query}%"
    rows = fetchall(
        conn,
        """
        SELECT repo, html_url, description
        FROM repos
        WHERE user=? AND (readme_text LIKE ? OR description LIKE ?)
        ORDER BY repo
        LIMIT ?
        """,
        (user, q, q, _safe_int(limit, 10)),
    ) or []
    # Normalize 'repo'/'name' for consistency
    return [_normalize_repo_row(r) for r in rows]


# ============================================================
# Multi-Repo Intelligence Tools
# ============================================================

@mcp.tool()
async def query_repos_by_signals(
    user: str,
    tech_stack: Optional[str] = None,
    has_ci_config: Optional[bool] = None,
    has_tests: Optional[bool] = None,
    has_dockerfile: Optional[bool] = None,
    has_precommit: Optional[bool] = None,
    detected_ci: Optional[str] = None,
    detected_test_framework: Optional[str] = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Query multiple repositories by engineering signals and/or tech stack.

    Notes:
    - tech_stack uses LIKE matching against the detected tech stack string.
    - boolean flags map to 0/1 columns in repo_signals.
    """
    conn = _conn_for(user)

    conditions = ["user=?"]
    params: list[Any] = [user]

    if tech_stack:
        conditions.append("tech_stack LIKE ?")
        params.append(f"%{tech_stack}%")

    if has_ci_config is not None:
        conditions.append("has_ci_config=?")
        params.append(int(bool(has_ci_config)))

    if has_tests is not None:
        conditions.append("has_tests=?")
        params.append(int(bool(has_tests)))

    if has_dockerfile is not None:
        conditions.append("has_dockerfile=?")
        params.append(int(bool(has_dockerfile)))

    if has_precommit is not None:
        conditions.append("has_precommit=?")
        params.append(int(bool(has_precommit)))

    if detected_ci:
        conditions.append("detected_ci=?")
        params.append(detected_ci)

    if detected_test_framework:
        conditions.append("detected_test_framework=?")
        params.append(detected_test_framework)

    where_clause = " AND ".join(conditions)

    rows = fetchall(
        conn,
        f"""
        SELECT
          repo,
          tech_stack,
          has_ci_config,
          has_tests,
          has_dockerfile,
          has_precommit,
          detected_ci,
          detected_test_framework,
          automation_score,
          coding_standards_score,
          organization_score
        FROM repo_signals
        WHERE {where_clause}
        ORDER BY
          has_ci_config DESC,
          has_tests DESC,
          automation_score DESC,
          coding_standards_score DESC,
          repo ASC
        LIMIT ?
        """,
        (*params, _safe_int(limit, 20)),
    ) or []

    # normalize key alignment
    out: list[dict[str, Any]] = []
    for r in rows:
        rr = dict(r)
        rr["has_ci_config"] = bool(_safe_int(rr.get("has_ci_config", 0), 0))
        rr["has_tests"] = bool(_safe_int(rr.get("has_tests", 0), 0))
        rr["has_dockerfile"] = bool(_safe_int(rr.get("has_dockerfile", 0), 0))
        rr["has_precommit"] = bool(_safe_int(rr.get("has_precommit", 0), 0))
        rr["automation_score"] = _safe_float(rr.get("automation_score", 0.0), 0.0)
        rr["coding_standards_score"] = _safe_float(rr.get("coding_standards_score", 0.0), 0.0)
        rr["organization_score"] = _safe_float(rr.get("organization_score", 0.0), 0.0)
        # convenience alias
        rr["name"] = rr.get("repo")
        out.append(rr)

    return out


@mcp.tool()
async def aggregate_repo_metrics(user: str) -> dict[str, Any]:
    """
    Return high-level engineering metrics across all repos for a user.
    """
    conn = _conn_for(user)

    def _count(sql: str, params: tuple[Any, ...]) -> int:
        row = fetchone(conn, sql, params) or {}
        return _safe_int(row.get("c", 0), 0)

    return {
        "total_repos": _count("SELECT COUNT(*) as c FROM repos WHERE user=?", (user,)),
        "ci_cd_repos": _count("SELECT COUNT(*) as c FROM repo_signals WHERE user=? AND has_ci_config=1", (user,)),
        "github_actions_repos": _count("SELECT COUNT(*) as c FROM repo_signals WHERE user=? AND has_github_actions=1", (user,)),
        "test_repos": _count("SELECT COUNT(*) as c FROM repo_signals WHERE user=? AND has_tests=1", (user,)),
        "lint_repos": _count("SELECT COUNT(*) as c FROM repo_signals WHERE user=? AND has_lint_config=1", (user,)),
        "precommit_repos": _count("SELECT COUNT(*) as c FROM repo_signals WHERE user=? AND has_precommit=1", (user,)),
        "docker_repos": _count("SELECT COUNT(*) as c FROM repo_signals WHERE user=? AND has_dockerfile=1", (user,)),
        "python_repos": _count("SELECT COUNT(*) as c FROM repo_signals WHERE user=? AND tech_stack LIKE '%Python%'", (user,)),
        "sql_hint_repos": _count("SELECT COUNT(*) as c FROM repos WHERE user=? AND (description LIKE '%SQL%' OR readme_text LIKE '%SQL%')", (user,)),
    }


@mcp.tool()
async def rank_repos_by_activity(user: str, limit: int = 10) -> list[dict[str, Any]]:
    """
    Rank repositories by commit activity (count of commits in the ingested window).

    Note: depends on how many commits you ingested per repo.
    """
    conn = _conn_for(user)
    rows = fetchall(
        conn,
        """
        SELECT repo, COUNT(*) as commit_count
        FROM commits
        WHERE user=?
        GROUP BY repo
        ORDER BY commit_count DESC, repo ASC
        LIMIT ?
        """,
        (user, _safe_int(limit, 10)),
    ) or []
    for r in rows:
        r["commit_count"] = _safe_int(r.get("commit_count", 0), 0)
        r["name"] = r.get("repo")
    return rows


# ============================================================
# Server Entrypoint
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Run the GitHub MCP server (stdio).")
    parser.add_argument("--user", required=False, default=None)
    _ = parser.parse_args()

    # For stdio servers: do not print to stdout (logging goes to stderr).
    LOGGER.info("Starting GitHub MCP server (transport=stdio)")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()