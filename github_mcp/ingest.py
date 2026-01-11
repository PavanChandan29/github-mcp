from __future__ import annotations
import json
import argparse
import base64
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import yaml
from pathlib import Path

import httpx
from dotenv import load_dotenv

from .common import LOGGER, connect, fetchall, fetchone, get_db_path, init_schema, upsert

GITHUB_API = "https://api.github.com"

# Load secrets from secrets.env file in the same directory
_secrets_path = Path(__file__).parent / "secrets.env"
if _secrets_path.exists():
    load_dotenv(_secrets_path)

def load_config() -> dict:
    config_path = Path(__file__).resolve().parents[1] / "config" / "ingest.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "github_mcp/0.1.0",
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
    
    # Test detection
    has_tests = any(
        p.startswith(("test/", "tests/", "__tests__/", "spec/")) or 
        p.endswith(("_test.py", ".spec.ts", ".test.ts", ".test.js", ".test.py", "_spec.rb", ".spec.rb"))
        for p in lower
    )
    
    # CI/CD detection
    has_actions = any(p.startswith(".github/workflows/") for p in lower)
    has_ci = has_actions or any(p.startswith((".circleci/", ".gitlab-ci", "azure-pipelines", "jenkinsfile")) for p in lower)
    
    # Linting and code quality
    lint_files = {
        ".ruff.toml", "ruff.toml", "pyproject.toml", ".flake8", "setup.cfg", ".pylintrc",
        ".eslintrc", ".eslintrc.json", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.yaml",
        ".prettierrc", ".prettierrc.json", ".prettierrc.js", ".prettierrc.yaml",
        ".stylelintrc", ".editorconfig", ".clang-format",
    }
    has_lint = any(p in lint_files or p.endswith(".eslintrc.js") or p.endswith(".prettierrc.json") for p in lower)
    
    # Automation and tooling
    has_precommit = any(p == ".pre-commit-config.yaml" for p in lower)
    has_dockerfile = any(p.endswith("dockerfile") or p == "dockerfile" for p in lower)
    has_docker_compose = any(p.endswith("docker-compose.yml") or p.endswith("docker-compose.yaml") for p in lower)
    has_makefile = any(p == "makefile" for p in lower)
    
    # Documentation and organization
    has_code_of_conduct = any(p in ("code_of_conduct.md", "code-of-conduct.md", ".github/code_of_conduct.md") for p in lower)
    has_contributing = any(p in ("contributing.md", "contributing.rst", ".github/contributing.md") for p in lower)
    has_license = any(p.startswith("license") or p.startswith("licence") for p in lower)
    has_security_policy = any(p in (".github/security.md", "security.md", "security.rst") for p in lower)
    has_issue_templates = any(p.startswith(".github/issue_template") or ".github/ISSUE_TEMPLATE" in p for p in lower)
    has_pr_templates = any(p.startswith(".github/pull_request_template") or ".github/PULL_REQUEST_TEMPLATE" in p for p in lower)
    has_changelog = any(p.startswith(("changelog", "changes", "history")) for p in lower)
    has_docs = any(p.startswith(("docs/", "documentation/")) for p in lower)
    
    # Tech stack detection (from file extensions and configs)
    tech_stack = set()
    for p in lower:
        # ---------- Python ----------
        if (
                p.endswith(".py")
                or p.endswith("requirements.txt")
                or p.endswith("pyproject.toml")
                or p.endswith("setup.py")
                or "/python" in p
        ):
            tech_stack.add("Python")
            # Framework detection
            if "fastapi" in p:
                tech_stack.add("FastAPI")
            elif "flask" in p:
                tech_stack.add("Flask")
            elif "django" in p:
                tech_stack.add("Django")
            elif "streamlit" in p:
                tech_stack.add("Streamlit")
        # ---------- JavaScript / TypeScript ----------
        elif p.endswith((".ts", ".tsx", "tsconfig.json")):
            tech_stack.add("TypeScript")
            if "react" in p:
                tech_stack.add("React")
            elif "next" in p:
                tech_stack.add("Next.js")
            elif "node" in p:
                tech_stack.add("Node.js")
        elif p.endswith((".js", ".jsx", "package.json")):
            tech_stack.add("JavaScript")
            if "react" in p:
                tech_stack.add("React")
            elif "vue" in p:
                tech_stack.add("Vue")
            elif "angular" in p:
                tech_stack.add("Angular")
            elif "node" in p:
                tech_stack.add("Node.js")
        # ---------- Java / JVM ----------
        elif p.endswith((".java", "pom.xml", "build.gradle", "build.gradle.kts")):
            tech_stack.add("Java")
            if "spring" in p:
                tech_stack.add("Spring")
        elif p.endswith((".kt", ".kts")):
            tech_stack.add("Kotlin")
        elif p.endswith((".scala", "build.sbt")):
            tech_stack.add("Scala")
        # ---------- Go / Rust / C / C++ ----------
        elif p.endswith((".go", "go.mod", "go.sum")):
            tech_stack.add("Go")
        elif p.endswith((".rs", "cargo.toml")):
            tech_stack.add("Rust")
        elif p.endswith((".cpp", ".cc", ".cxx", "cmakelists.txt")):
            tech_stack.add("C++")
        elif p.endswith(".c"):
            tech_stack.add("C")
        # ---------- .NET ----------
        elif p.endswith((".cs", ".csproj")):
            tech_stack.add("C#")
            if "dotnet" in p:
                tech_stack.add(".NET")
        # ---------- Web / PHP ----------
        elif p.endswith((".php", "composer.json")):
            tech_stack.add("PHP")
            if "laravel" in p:
                tech_stack.add("Laravel")
        # ---------- Mobile ----------
        elif p.endswith((".swift", "podfile")):
            tech_stack.add("Swift")
        # ---------- Databases / SQL ----------
        elif p.endswith(".sql") or "/migrations/" in p or "/schema/" in p:
            tech_stack.add("SQL")
        elif "dbt_project.yml" in p:
            tech_stack.add("dbt")
        elif p.endswith((".pbix", ".pbit")):
            tech_stack.add("Power BI")
        elif p.endswith((".twb", ".twbx", ".hyper", ".tds", ".tdsx")):
            tech_stack.add("Tableau")
        # ---------- Cloud / IaC ----------
        elif p.endswith(".tf"):
            tech_stack.add("Terraform")
        elif "cloudformation" in p or p.endswith(".yaml") and "aws" in p:
            tech_stack.add("CloudFormation")
        elif "bicep" in p:
            tech_stack.add("Azure Bicep")
        elif "cdk" in p:
            tech_stack.add("AWS CDK")
        # ---------- AI / LLM ----------
        elif "langgraph" in p:
            tech_stack.add("LangGraph")
        elif "langchain" in p:
            tech_stack.add("LangChain")
        elif "openai" in p:
            tech_stack.add("OpenAI")
        # ---------- DevOps ----------
        elif "dockerfile" in p:
            tech_stack.add("Docker")
        elif "docker-compose" in p:
            tech_stack.add("Docker Compose")
        elif "serverless.yml" in p:
            tech_stack.add("Serverless")
        elif ".github/workflows" in p:
            tech_stack.add("GitHub Actions")
    
    # Test framework detection
    detected_test_framework = None
    if any(p.endswith("pytest.ini") or p.endswith("conftest.py") or p.endswith("pytest.ini") for p in lower):
        detected_test_framework = "pytest"
    elif any(p.endswith(("jest.config.js", "jest.config.ts", "jest.config.json")) for p in lower):
        detected_test_framework = "jest"
    elif any(p.endswith(("vitest.config.ts", "vitest.config.js")) for p in lower):
        detected_test_framework = "vitest"
    elif any(p.endswith(("mocha.opts", ".mocharc.json", ".mocharc.js")) for p in lower):
        detected_test_framework = "mocha"
    elif any(p.endswith(("spec_helper.rb", "test_helper.rb")) for p in lower):
        detected_test_framework = "rspec"
    
    # CI/CD detection
    detected_ci = None
    if has_actions:
        detected_ci = "github_actions"
    elif any(p.startswith(".circleci/") for p in lower):
        detected_ci = "circleci"
    elif any(p.startswith(".gitlab-ci") for p in lower):
        detected_ci = "gitlab_ci"
    elif any("azure-pipelines" in p for p in lower):
        detected_ci = "azure_pipelines"
    elif any("jenkinsfile" in p for p in lower):
        detected_ci = "jenkins"
    elif any("travis.yml" in p for p in lower):
        detected_ci = "travis"
    
    # Calculate scores (0-100 scale)
    organization_items = [
        has_code_of_conduct, has_contributing, has_license, has_security_policy,
        has_issue_templates, has_pr_templates, has_changelog, has_docs,
        has_readme := any(p.startswith("readme") for p in lower)
    ]
    organization_score = round((sum(organization_items) / len(organization_items)) * 100, 1)
    
    coding_standards_items = [has_tests, has_lint, has_precommit, has_ci]
    coding_standards_score = round((sum(coding_standards_items) / len(coding_standards_items)) * 100, 1)
    
    automation_items = [has_actions, has_ci, has_precommit, has_dockerfile, has_docker_compose]
    automation_score = round((sum(automation_items) / len(automation_items)) * 100, 1)
    
    return {
        "has_tests": int(has_tests),
        "has_github_actions": int(has_actions),
        "has_ci_config": int(has_ci),
        "has_lint_config": int(has_lint),
        "has_precommit": int(has_precommit),
        "has_dockerfile": int(has_dockerfile),
        "has_docker_compose": int(has_docker_compose),
        "has_makefile": int(has_makefile),
        "has_code_of_conduct": int(has_code_of_conduct),
        "has_contributing": int(has_contributing),
        "has_license": int(has_license),
        "has_security_policy": int(has_security_policy),
        "has_issue_templates": int(has_issue_templates),
        "has_pr_templates": int(has_pr_templates),
        "has_changelog": int(has_changelog),
        "has_docs": int(has_docs),
        "detected_test_framework": detected_test_framework or "",
        "detected_ci": detected_ci or "",
        "organization_score": organization_score,
        "coding_standards_score": coding_standards_score,
        "automation_score": automation_score,
        "tech_stack": ", ".join(sorted(tech_stack)) if tech_stack else "",
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
    conn = connect()
    init_schema(conn)

    repos = await list_repos(user, token)
    LOGGER.info("Found %d repos for user=%s", len(repos), user)

    for r in repos:
        repo = r["name"]
        default_branch = r.get("default_branch") or "main"
        description = r.get("description") or ""
        language = r.get("language") or ""
        html_url = r.get("html_url") or ""
        pushed_at = r.get("pushed_at") or ""
        created_at = r.get("created_at") or ""
        updated_at = r.get("updated_at") or ""
        stargazers_count = r.get("stargazers_count", 0)
        forks_count = r.get("forks_count", 0)
        watchers_count = r.get("watchers_count", 0)
        open_issues_count = r.get("open_issues_count", 0)
        size = r.get("size", 0)
        topics = json.dumps(r.get("topics", [])) if r.get("topics") else ""
        license_name = r.get("license", {}).get("name", "") if r.get("license") else ""
        is_archived = 1 if r.get("archived", False) else 0
        is_fork = 1 if r.get("fork", False) else 0
        
        readme_text = await fetch_readme(user, repo, token, default_branch)

        upsert(
            conn,
            """
            INSERT INTO repos(user, repo, default_branch, description, language, html_url, readme_text, 
                           last_ingested_at, pushed_at, created_at, updated_at, stargazers_count, 
                           forks_count, watchers_count, open_issues_count, size, topics, license_name, 
                           is_archived, is_fork)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user, repo) DO UPDATE SET
              default_branch=excluded.default_branch,
              description=excluded.description,
              language=excluded.language,
              html_url=excluded.html_url,
              readme_text=excluded.readme_text,
              last_ingested_at=excluded.last_ingested_at,
              pushed_at=excluded.pushed_at,
              created_at=excluded.created_at,
              updated_at=excluded.updated_at,
              stargazers_count=excluded.stargazers_count,
              forks_count=excluded.forks_count,
              watchers_count=excluded.watchers_count,
              open_issues_count=excluded.open_issues_count,
              size=excluded.size,
              topics=excluded.topics,
              license_name=excluded.license_name,
              is_archived=excluded.is_archived,
              is_fork=excluded.is_fork
            """,
            (user, repo, default_branch, description, language, html_url, readme_text, 
             datetime.now(timezone.utc).isoformat(), pushed_at, created_at, updated_at,
             stargazers_count, forks_count, watchers_count, open_issues_count, size, topics,
             license_name, is_archived, is_fork),
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
                  has_precommit, has_dockerfile, has_docker_compose, has_makefile, detected_test_framework, detected_ci,
                  has_code_of_conduct, has_contributing, has_license, has_security_policy,
                  has_issue_templates, has_pr_templates, has_changelog, has_docs,
                  organization_score, coding_standards_score, automation_score, tech_stack, signals_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user, repo) DO UPDATE SET
                  has_tests=excluded.has_tests,
                  has_github_actions=excluded.has_github_actions,
                  has_ci_config=excluded.has_ci_config,
                  has_lint_config=excluded.has_lint_config,
                  has_precommit=excluded.has_precommit,
                  has_dockerfile=excluded.has_dockerfile,
                  has_docker_compose=excluded.has_docker_compose,
                  has_makefile=excluded.has_makefile,
                  detected_test_framework=excluded.detected_test_framework,
                  detected_ci=excluded.detected_ci,
                  has_code_of_conduct=excluded.has_code_of_conduct,
                  has_contributing=excluded.has_contributing,
                  has_license=excluded.has_license,
                  has_security_policy=excluded.has_security_policy,
                  has_issue_templates=excluded.has_issue_templates,
                  has_pr_templates=excluded.has_pr_templates,
                  has_changelog=excluded.has_changelog,
                  has_docs=excluded.has_docs,
                  organization_score=excluded.organization_score,
                  coding_standards_score=excluded.coding_standards_score,
                  automation_score=excluded.automation_score,
                  tech_stack=excluded.tech_stack,
                  signals_json=excluded.signals_json
                """,
                (
                    user, repo,
                    sig["has_tests"], sig["has_github_actions"], sig["has_ci_config"], sig["has_lint_config"],
                    sig["has_precommit"], sig["has_dockerfile"], sig.get("has_docker_compose", 0), sig["has_makefile"],
                    sig["detected_test_framework"], sig["detected_ci"],
                    sig["has_code_of_conduct"], sig["has_contributing"], sig["has_license"],
                    sig["has_security_policy"], sig["has_issue_templates"], sig["has_pr_templates"],
                    sig["has_changelog"], sig["has_docs"],
                    sig["organization_score"], sig["coding_standards_score"], sig["automation_score"],
                    sig["tech_stack"],
                    json.dumps(sig["signals_json"]),
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


if __name__ == "__main__":
    main()
