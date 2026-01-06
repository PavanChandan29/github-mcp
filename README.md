# GitHub MCP

GitHub MCP is a **Model Context Protocol (MCP) server** that ingests a GitHub
user’s public repositories and commit history into a **local, persistent store**
and exposes that data via MCP tools for agents and LLMs to query.

This project is designed to **ingest once and query many times**, avoiding
repeated GitHub API calls during analysis.

---

## How This Project Works

1. **Ingestion phase**
   - GitHub API is called once
   - Repositories, READMEs, commit metadata, and repo-level signals are collected
   - Data is stored locally in a SQLite-based MCP store

2. **Serving phase**
   - An MCP server exposes tools backed by the local store
   - Agents and LLMs query the MCP server instead of GitHub

---

## Important: Module-Based Execution

This project is implemented as a **Python package** (`github_mcp`).

Because it uses **relative imports**, modules **must be executed using
Python’s `-m` flag**.

🚫 **Do NOT run files directly**, for example:
```
python github_mcp/ingest.py   # ❌ incorrect

python -m github_mcp.ingest   # correct 
```
---
Requirements

Python 3.10+

GitHub Personal Access Token (read-only)
