# CodeSense – Intelligent GitHub Profile Analyzer

RepoSense is an **AI-powered GitHub analysis system** that ingests a user’s public repositories into a **local knowledge base** and allows LLM agents to reason over that data using **structured MCP tools**.

This project was built as a **learning-focused system design exercise** to understand:

- How to separate **data ingestion**, **storage**, and **reasoning**
- How to avoid repeated API calls and context loss
- How agents can reason over *structured tools* instead of raw APIs
- How to design debuggable, deterministic AI systems

---

## Why I Built This

When you ask an LLM questions like:

- *“Which of my projects use Python?”*  
- *“Do I have CI/CD in any repo?”*  
- *“Which projects follow SDLC best?”*  

Most AI tools:

- Call the GitHub API repeatedly  
- Lose context between questions  
- Hallucinate tech stacks  
- Struggle with multi-repo reasoning  

I wanted to build something that:

- **Ingests GitHub data once**
- **Stores it locally**
- **Exposes it through structured tools**
- **Lets an agent reason over it deterministically**

This project is the result of that goal.

---

## Why MCP Instead of Direct GitHub API Calls?

Using the GitHub API directly inside an agent causes several problems:

| Problem | GitHub API + LLM | MCP-Based System |
|--------|-----------------|------------------|
| API Rate Limits | Frequent calls | One-time ingestion |
| Latency | Slow per question | Instant local queries |
| Context Loss | Each question starts fresh | Persistent local store |
| Hallucination Risk | High | Low (tool-grounded) |
| Multi-repo reasoning | Hard | Structured + reliable |
| Debugging | Difficult | Transparent + logged |

With MCP:

- GitHub data becomes **queryable knowledge**, not raw API responses  
- Agents operate on **stable schemas**, not unstructured JSON  
- Every action is **explicit and traceable**  

MCP turns GitHub from an API into a **local intelligence system**.

---

## System Architecture (High Level)

RepoSense is split into **three clean layers**:

### 1. Ingestion Layer  
Fetches and stores GitHub data once.

- Repositories  
- READMEs  
- File trees  
- Commits  
- Engineering signals (CI/CD, tests, Docker, etc.)  
- Detected tech stack  

Stored in a **SQLite knowledge store**.

---

### 2. MCP Server Layer  

Exposes structured tools like:

- `list_repos`  
- `get_repo_overview`  
- `query_repos_by_signals`  
- `rank_repos_by_activity`  
- `aggregate_repo_metrics`  

Each tool represents a **semantic capability**, not just raw data.

---

### 3. Agent Layer (LangGraph)

The agent:

- Understands natural-language questions  
- Creates a **semantic plan**  
- Chooses the right MCP tools  
- Executes them  
- Synthesizes grounded answers  

This separates:

- **Reasoning** → Agent  
- **Execution** → MCP  
- **Storage** → SQLite  

Which makes the system **clean, debuggable, and scalable**.

---

## What I Learned From This Project

This was not just about GitHub analysis. It was about learning **AI system design**.

Key takeaways:

- LLMs work best with **structured tools**, not raw APIs  
- Persistent knowledge > repeated API calls  
- Separating reasoning from execution makes systems easier to debug  
- “Semantic planning” is more reliable than keyword routing  
- Data schemas matter more than prompt engineering  

This project helped me think more like a **platform engineer** than just a prompt engineer.

---

## Design Principles

- Ingest once, query many times  
- No repeated API calls during analysis  
- Structured tools over raw JSON  
- Deterministic execution  
- Debuggable agent behavior  
- No hidden memory  
- No hallucinated data  

---

## Example Questions RepoSense Can Answer

- How many of my projects use Python?  
- Which repos have CI/CD configured?  
- Do I use Docker anywhere?  
- Which projects follow good SDLC practices?  
- What’s my most active repository?  
- Which tech stacks do I work with most?  

All answers are grounded in **stored data**, not guesses.

---

## Why This Is Better Than a Simple Chatbot

Most “GitHub AI bots”:

- Just call APIs  
- Summarize READMEs  
- Guess tech stacks  
- Can’t reason across repos  

RepoSense:

- Uses a **local knowledge base**  
- Uses **structured tools**  
- Supports **multi-step reasoning**  
- Produces **auditable answers**  

It’s not just a chatbot.  
It’s a **GitHub intelligence system**.

---

## Future Improvements

- Embedding-based semantic search  
- Code-level analysis  
- Skill profiling  
- Timeline-based growth analysis  
- SDLC maturity scoring  
- Portfolio auto-generation  

---