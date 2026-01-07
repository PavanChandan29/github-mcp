# GitHub MCP

GitHub MCP is a **Model Context Protocol (MCP) server** that ingests a GitHub
user’s public repositories and commit history into a **local, persistent store**
and exposes that data via MCP tools for agents and LLMs to query.

The project is designed to **ingest once and query many times**, avoiding
repeated GitHub API calls during analysis.

---

## What Problem This Solves

Analyzing GitHub profiles using LLMs typically involves:

- Repeated GitHub API calls (rate limits and latency)
- No persistent context across questions
- Unstructured, ad-hoc data access
- Difficulty reasoning over repositories, commits, and quality signals together

GitHub MCP solves this by:

- Decoupling **data ingestion** from **analysis**
- Persisting GitHub data locally
- Exposing GitHub data through **structured MCP tools**
- Enabling deterministic, repeatable analysis by agents

---

## How This Project Works

### 1. Ingestion Phase

- GitHub API is called once per user
- Public repositories, READMEs, commit metadata, and repo-level signals are collected
- Data is stored locally in a **SQLite-backed MCP store**

This creates a stable, queryable knowledge base.

---

### 2. Serving Phase (MCP)

- An MCP server exposes **tools** backed by the local store
- Each tool represents a **semantic data capability**, such as:
  - Listing repositories
  - Reading repository metadata and READMEs
  - Inspecting commit timelines
  - Surfacing repo-level quality signals

Agents and LLMs query the MCP server instead of GitHub directly.

---

### 3. Agent Layer

On top of the MCP server, the project includes an **agent layer built using LangGraph**.

The agent is responsible for:

- Interpreting natural-language questions
- Deciding **which MCP tool to use**
- Providing valid arguments for that tool
- Executing the tool via MCP
- Converting structured results into clear, human-readable answers

This cleanly separates:

- **Reasoning and planning** (agent)
- **Data access and execution** (MCP)
- **Storage and schemas** (local store)

---

## Why an Agent Is Needed

MCP tools expose **capabilities**, but they do not decide:

- When a tool should be used
- Which tool best answers a question
- How results should be explained

The agent layer acts as the **planner and interpreter**.

In simple terms:

- **MCP answers:** “What data can be accessed?”
- **Agent answers:** “What should be done to answer this question?”

---

## Design Principles

- **Ingest once, query many times**
- **Separate reasoning from data access**
- **Explicit execution flow and state**
- **Schema-enforced, structured tool interfaces**
- **Deterministic and debuggable agent behavior**
- **No hidden memory or side effects**

---