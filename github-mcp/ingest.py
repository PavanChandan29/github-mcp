from __future__ import annotations

import argparse
import base64
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import yaml
from pathlib import Path

import httpx

from .common import LOGGER, connect, fetchall, fetchone, get_db_path, init_schema, upsert

GITHUB_API = "https://api.github.com"

def load_config() -> dict:
    config_path = Path(__file__).resolve().parents[1] / "config" / "ingest.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "github-mcp/0.1.0",
    }


async def _get_json(client: httpx.AsyncClient, url: str, token: str, params: Optional[dict[str, Any]] = None) -> Any:
    resp = await client.get(url, headers=_headers(token), params=params, timeout=60.0)
    resp.raise_for_status()
    return resp.json()


async def _get_text(client: httpx.AsyncClient, url: str, token: str) -> str:
    resp = await client.get(url, headers=_headers(token), timeout=60.0)
    resp.raise_for_status()
    return resp.text


async def list_repos(user: str, token: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient() as client:
        # Use /users/{user}/repos (public) or /user/repos when token belongs to the user.
        # Here we use /users to allow analyzing any public profile with a token for rate limits.
        repos = []
        page = 1
        while True:
            data = await _get_json(
                client,
                f"{GITHUB_API}/users/{user}/repos",
                token,
                params={"per_page": 100, "page": page, "sort": "updated"},
            )
            if not data:
                break
            repos.extend(data)
            page += 1
        return repos


async def fetch_readme(user: str, repo: str, token: str, default_branch: str) -> str:
    async with httpx.AsyncClient() as client:
        # GitHub README API returns base64 content.
        try:
            data = await _get_json(client, f"{GITHUB_API}/repos/{user}/{repo}/readme", token)
            content_b64 = data.get("content", "")
            if content_b64:
                return base64.b64decode(content_b64).decode("utf-8", errors="replace")
        except Exception:
            pass
        return ""


async def list_tree(user: str, repo: str, token: str, default_branch: str) -> list[str]:
    """
    Shallow repo signals: we fetch the git tree (recursive=1) and inspect file paths.
    """
    async with httpx.AsyncClient() as client:
        ref = await _get_json(client, f"{GITHUB_API}/repos/{user}/{repo}/git/refs/heads/{default_branch}", token)
        sha = ref["object"]["sha"]
        commit = await _get_json(client, f"{GITHUB_API}/repos/{user}/{repo}/git/commits/{sha}", token)
        tree_sha = commit["tree"]["sha"]
        tree = await _get_json(
            client,
            f"{GITHUB_API}/repos/{user}/{repo}/git/trees/{tree_sha}",
            token,
            params={"recursive": "1"},
        )
        paths = [t["path"] for t in tree.get("tree", []) if "path" in t]
        return paths


def detect_signals(paths: list[str]) -> dict[str, Any]:
    lower = [p.lower() for p in paths]

    def has_any(prefixes: list[str]) -> bool:
        return any(any(p.startswith(pref) for pref in prefixes) for p in lower)

    has_tests = any(
        p.startswith(("test/", "tests/", "__tests__/")) or p.endswith(("_test.py", ".spec.ts", ".test.ts", ".test.js"))
        for p in lower
    )
    has_actions = any(p.startswith(".github/workflows/") for p in lower)
    has_ci = has_actions or any(p.startswith((".circleci/", ".gitlab-ci", "azure-pipelines", "jenkinsfile")) for p in lower)

    lint_files = {
        ".ruff.toml", "ruff.toml", "pyproject.toml", ".flake8", "setup.cfg", ".pylintrc",
        ".eslintrc", ".eslintrc.json", ".eslintrc.js", ".prettierrc", ".prettierrc.json",
    }
    has_lint = any(p in lint_files for p in lower)

    has_precommit = any(p == ".pre-commit-config.yaml" for p in lower)
    has_dockerfile = any(p.endswith("dockerfile") or p == "dockerfile" for p in lower)
    has_makefile = any(p == "makefile" for p in lower)

    # very light framework detection
    detected_test_framework = None
    if any(p.endswith("pytest.ini") for p in lower) or any(p.endswith("conftest.py") for p in lower):
        detected_test_framework = "pytest"
    elif any(p.endswith("jest.config.js") or p.endswith("jest.config.ts") for p in lower):
        detected_test_framework = "jest"
    elif any(p.endswith("vitest.config.ts") or p.endswith("vitest.config.js") for p in lower):
        detected_test_framework = "vitest"

    detected_ci = None
    if has_actions:
        detected_ci = "github_actions"
    elif any(p.startswith(".circleci/") for p in lower):
        detected_ci = "circleci"
    elif any(p.startswith(".gitlab-ci") for p in lower):
        detected_ci = "gitlab_ci"

    return {
        "has_tests": int(has_tests),
        "has_github_actions": int(has_actions),
        "has_ci_config": int(has_ci),
        "has_lint_config": int(has_lint),
        "has_precommit": int(has_precommit),
        "has_dockerfile": int(has_dockerfile),
        "has_makefile": int(has_makefile),
        "detected_test_framework": detected_test_framework or "",
        "detected_ci": detected_ci or "",
        "signals_json": {
            "total_paths": len(paths),
            "sample_paths": paths[:50],
        },
    }


async def list_commits(user: str, repo: str, token: str, max_commits: int = 200) -> list[dict[str, Any]]:
    commits: list[dict[str, Any]] = []
    per_page = 100
    page = 1
    async with httpx.AsyncClient() as client:
        while len(commits) < max_commits:
            batch = await _get_json(
                client,
                f"{GITHUB_API}/repos/{user}/{repo}/commits",
                token,
                params={"per_page": per_page, "page": page},
            )
            if not batch:
                break
            commits.extend(batch)
            page += 1
            if len(batch) < per_page:
                break
    return commits[:max_commits]


async def fetch_commit_details(user: str, repo: str, sha: str, token: str) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        return await _get_json(client, f"{GITHUB_API}/repos/{user}/{repo}/commits/{sha}", token)


def _iso(dt: Optional[str]) -> str:
    if not dt:
        return ""
    return dt


async def ingest(user: str, token: str, max_commits: int) -> None:
    db_path = get_db_path(user)
    conn = connect(db_path)
    init_schema(conn)

    repos = await list_repos(user, token)
    LOGGER.info("Found %d repos for user=%s", len(repos), user)

    for r in repos:
        repo = r["name"]
        default_branch = r.get("default_branch") or "main"
        description = r.get("description") or ""
        language = r.get("language") or ""
        html_url = r.get("html_url") or ""
        readme_text = await fetch_readme(user, repo, token, default_branch)

        upsert(
            conn,
            """
            INSERT INTO repos(user, repo, default_branch, description, language, html_url, readme_text, last_ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user, repo) DO UPDATE SET
              default_branch=excluded.default_branch,
              description=excluded.description,
              language=excluded.language,
              html_url=excluded.html_url,
              readme_text=excluded.readme_text,
              last_ingested_at=excluded.last_ingested_at
            """,
            (user, repo, default_branch, description, language, html_url, readme_text, datetime.now(timezone.utc).isoformat()),
        )

        # Signals
        try:
            paths = await list_tree(user, repo, token, default_branch)
            sig = detect_signals(paths)
            upsert(
                conn,
                """
                INSERT INTO repo_signals(
                  user, repo, has_tests, has_github_actions, has_ci_config, has_lint_config,
                  has_precommit, has_dockerfile, has_makefile, detected_test_framework, detected_ci, signals_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user, repo) DO UPDATE SET
                  has_tests=excluded.has_tests,
                  has_github_actions=excluded.has_github_actions,
                  has_ci_config=excluded.has_ci_config,
                  has_lint_config=excluded.has_lint_config,
                  has_precommit=excluded.has_precommit,
                  has_dockerfile=excluded.has_dockerfile,
                  has_makefile=excluded.has_makefile,
                  detected_test_framework=excluded.detected_test_framework,
                  detected_ci=excluded.detected_ci,
                  signals_json=excluded.signals_json
                """,
                (
                    user, repo,
                    sig["has_tests"], sig["has_github_actions"], sig["has_ci_config"], sig["has_lint_config"],
                    sig["has_precommit"], sig["has_dockerfile"], sig["has_makefile"],
                    sig["detected_test_framework"], sig["detected_ci"],
                    __import__("json").dumps(sig["signals_json"]),
                ),
            )
        except Exception as e:
            LOGGER.warning("Signals scan failed for %s/%s: %s", user, repo, e)

        # Commits (metadata only; diff_summary left for later enhancement)
        try:
            commits = await list_commits(user, repo, token, max_commits=max_commits)
            for c in commits:
                sha = c["sha"]
                details = await fetch_commit_details(user, repo, sha, token)
                commit_obj = details.get("commit", {})
                authored_at = commit_obj.get("author", {}).get("date", "")
                message = commit_obj.get("message", "")
                author_name = commit_obj.get("author", {}).get("name", "")
                author_login = (details.get("author") or {}).get("login", "") if details.get("author") else ""
                files = details.get("files") or []
                additions = details.get("stats", {}).get("additions", 0)
                deletions = details.get("stats", {}).get("deletions", 0)

                upsert(
                    conn,
                    """
                    INSERT INTO commits(
                      user, repo, sha, authored_at, message, author_name, author_login,
                      files_changed, additions, deletions, diff_summary
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user, repo, sha) DO UPDATE SET
                      authored_at=excluded.authored_at,
                      message=excluded.message,
                      author_name=excluded.author_name,
                      author_login=excluded.author_login,
                      files_changed=excluded.files_changed,
                      additions=excluded.additions,
                      deletions=excluded.deletions
                    """,
                    (user, repo, sha, authored_at, message, author_name, author_login, len(files), additions, deletions, ""),
                )
        except Exception as e:
            LOGGER.warning("Commit ingestion failed for %s/%s: %s", user, repo, e)

    LOGGER.info("Ingestion complete. DB=%s", db_path)


def main():
    parser = argparse.ArgumentParser(
        description="Ingest a GitHub user's public repos into a local MCP store (SQLite)."
    )
    parser.add_argument(
        "--token",
        required=False,
        default=None,
        help="GitHub token (optional; falls back to GITHUB_TOKEN env var).",
    )
    args = parser.parse_args()

    # --- Load config ---
    config = load_config()

    user = config["github"]["user"]
    max_commits = config["ingestion"].get("max_commits_per_repo", 200)

    data_dir = config.get("storage", {}).get("data_dir")
    if data_dir:
        import os
        os.environ["GITHUB_MCP_DATA_DIR"] = os.path.expanduser(data_dir)

    # --- Resolve token ---
    token = args.token or __import__("os").environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit(
            "Missing GitHub token. Set GITHUB_TOKEN env var or pass --token."
        )

    import asyncio
    asyncio.run(ingest(user, token, max_commits))

    import asyncio
    asyncio.run(ingest(args.user, token, args.max_commits))


if __name__ == "__main__":
    main()
