from __future__ import annotations

import argparse
import json
import logging
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


@mcp.tool()
async def list_repos(user: str) -> list[dict[str, Any]]:
    """List repositories ingested for a GitHub user, ordered by most recently pushed first.
    Returns comprehensive repo information including stars, forks, dates, and metadata.

    Args:
        user: GitHub username whose MCP store should be queried.
    """
    conn = _conn_for(user)
    # Order by pushed_at DESC (most recent first), with NULLs appearing last
    repos = fetchall(
        conn,
        """SELECT repo, description, language, html_url, pushed_at, created_at, updated_at,
                  stargazers_count, forks_count, watchers_count, open_issues_count, 
                  size, topics, license_name, is_archived, is_fork
           FROM repos WHERE user=? ORDER BY pushed_at DESC, repo""",
        (user,),
    )
    
    # Parse topics JSON for each repo
    for repo in repos:
        if repo.get("topics"):
            try:
                repo["topics"] = json.loads(repo["topics"])
            except (json.JSONDecodeError, TypeError):
                repo["topics"] = []
        else:
            repo["topics"] = []
    
    return repos


@mcp.tool()
async def get_repo_overview(user: str, repo: str) -> dict[str, Any]:
    """Get comprehensive repository information including metadata, achievements, automation, and quality metrics.

    Args:
        user: GitHub username
        repo: Repository name
    """
    conn = _conn_for(user)
    r = fetchone(conn, "SELECT * FROM repos WHERE user=? AND repo=?", (user, repo))
    if not r:
        return {"error": f"Repo not found in MCP store: {user}/{repo}. Run ingestion first."}
    s = fetchone(conn, "SELECT * FROM repo_signals WHERE user=? AND repo=?", (user, repo)) or {}
    
    # Parse topics
    topics = []
    if r.get("topics"):
        try:
            topics = json.loads(r["topics"])
        except (json.JSONDecodeError, TypeError):
            topics = []
    
    # Get commit count
    commit_count = fetchone(
        conn,
        "SELECT COUNT(*) as count FROM commits WHERE user=? AND repo=?",
        (user, repo)
    ) or {}
    
    return {
        "repo": repo,
        "description": r.get("description", ""),
        "language": r.get("language", ""),
        "html_url": r.get("html_url", ""),
        "default_branch": r.get("default_branch", ""),
        "created_at": r.get("created_at", ""),
        "updated_at": r.get("updated_at", ""),
        "pushed_at": r.get("pushed_at", ""),
        "last_ingested_at": r.get("last_ingested_at", ""),
        "readme_text": r.get("readme_text", ""),
        "achievements": {
            "stars": r.get("stargazers_count", 0),
            "forks": r.get("forks_count", 0),
            "watchers": r.get("watchers_count", 0),
            "open_issues": r.get("open_issues_count", 0),
            "commits": commit_count.get("count", 0),
        },
        "metadata": {
            "size": r.get("size", 0),
            "topics": topics,
            "license": r.get("license_name", "") or None,
            "is_archived": bool(r.get("is_archived", 0)),
            "is_fork": bool(r.get("is_fork", 0)),
        },
        "automation": {
            "has_github_actions": bool(s.get("has_github_actions", 0)),
            "has_ci_config": bool(s.get("has_ci_config", 0)),
            "has_precommit": bool(s.get("has_precommit", 0)),
            "has_dockerfile": bool(s.get("has_dockerfile", 0)),
            "has_docker_compose": bool(s.get("has_docker_compose", 0)),
            "has_makefile": bool(s.get("has_makefile", 0)),
            "detected_ci": s.get("detected_ci", "") or None,
            "automation_score": s.get("automation_score", 0.0),
        },
        "coding_standards": {
            "has_tests": bool(s.get("has_tests", 0)),
            "has_lint_config": bool(s.get("has_lint_config", 0)),
            "has_precommit": bool(s.get("has_precommit", 0)),
            "has_ci_config": bool(s.get("has_ci_config", 0)),
            "detected_test_framework": s.get("detected_test_framework", "") or None,
            "coding_standards_score": s.get("coding_standards_score", 0.0),
        },
        "organization": {
            "has_code_of_conduct": bool(s.get("has_code_of_conduct", 0)),
            "has_contributing": bool(s.get("has_contributing", 0)),
            "has_license": bool(s.get("has_license", 0)),
            "has_security_policy": bool(s.get("has_security_policy", 0)),
            "has_issue_templates": bool(s.get("has_issue_templates", 0)),
            "has_pr_templates": bool(s.get("has_pr_templates", 0)),
            "has_changelog": bool(s.get("has_changelog", 0)),
            "has_docs": bool(s.get("has_docs", 0)),
            "organization_score": s.get("organization_score", 0.0),
        },
        "tech_stack": s.get("tech_stack", "") or None,
    }


@mcp.tool()
async def get_repo_signals(user: str, repo: str) -> dict[str, Any]:
    """Return engineering-practice signals (tests/CI/lint/etc) detected from the repo tree.

    Args:
        user: GitHub username
        repo: Repository name
    """
    conn = _conn_for(user)
    s = fetchone(conn, "SELECT * FROM repo_signals WHERE user=? AND repo=?", (user, repo))
    if not s:
        return {"error": f"No signals found for {user}/{repo}. Run ingestion first."}
    out = dict(s)
    # normalize json blob
    try:
        out["signals_json"] = json.loads(out.get("signals_json") or "{}")
    except Exception:
        out["signals_json"] = {}
    return out


@mcp.tool()
async def get_commit_timeline(user: str, repo: str, limit: int = 50) -> list[dict[str, Any]]:
    """Return a commit timeline (most recent first) with basic change metrics.

    Args:
        user: GitHub username
        repo: Repository name
        limit: Max commits to return
    """
    conn = _conn_for(user)
    return fetchall(
        conn,
        """
        SELECT sha, authored_at, message, author_name, author_login, files_changed, additions, deletions
        FROM commits
        WHERE user=? AND repo=?
        ORDER BY authored_at DESC
        LIMIT ?
        """,
        (user, repo, int(limit)),
    )


@mcp.tool()
async def search_readmes(user: str, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search README text across repos (simple LIKE search).

    Args:
        user: GitHub username
        query: Search string
        limit: Max results
    """
    conn = _conn_for(user)
    q = f"%{query}%"
    return fetchall(
        conn,
        """
        SELECT repo, html_url, description
        FROM repos
        WHERE user=? AND (readme_text LIKE ? OR description LIKE ?)
        ORDER BY repo
        LIMIT ?
        """,
        (user, q, q, int(limit)),
    )


def main():
    parser = argparse.ArgumentParser(description="Run the GitHub MCP server (stdio).")
    parser.add_argument("--user", required=False, default=None, help="Default GitHub username for convenience.")
    args = parser.parse_args()

    # For stdio servers: do not print to stdout (logging goes to stderr via logging module).
    LOGGER.info("Starting GitHub MCP server (transport=stdio)")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
