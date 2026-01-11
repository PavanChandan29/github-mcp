# CodeSense – Runtime & Deployment Notes

This document explains how CodeSense actually runs in practice — using the same  
engineering-style explanations discussed during development.

---

## What Render Actually Does

Render provides a Linux runtime environment in the cloud.

When we deploy:

1. It pulls the GitHub repository  
2. Installs dependencies using `requirements.txt`  
3. Runs the start command that launches the FastAPI app  

That’s it.

Render is simply:

> “Here’s a server, here’s Python, run this command.”

---

## What Runs When the Service Starts

When the backend starts:

- FastAPI starts  
- MCP server loads  
- Database connection is attempted  
- Supabase Postgres is used (not SQLite)  
- API routes become live  

You’ll see logs like:

Connecting to Supabase Postgres...  
Application startup complete.

Once this appears, the service is live.

Render then provides a public URL such as:

https://github-mcp-xxxx.onrender.com  

This URL is your MCP backend.

---

## Where the GitHub Token Comes From

The GitHub token is **not stored** on Render.

Instead:

- The user enters it in the Streamlit UI  
- It is stored in Streamlit session memory  
- When a query is submitted, the app sets:

`os.environ["GITHUB_TOKEN"] = user_input_token`

So the token is passed at runtime, per request.

Nothing is stored in:

- Supabase  
- Render  
- GitHub  
- The repository  

It only exists during the request lifecycle.

---

## What Happens When a User Asks a Question

Example:

“How many Python projects does Pavan have?”

Actual flow:

1. Streamlit collects:
   - Question  
   - GitHub username  
   - GitHub token  
   - Chat history  

2. The agent is invoked.

3. The agent:
   - Understands the intent  
   - Selects the correct MCP tool  
   - Builds structured arguments  

4. MCP server:
   - Queries Supabase  
   - If data is missing:
     - Calls GitHub API  
     - Ingests data  
     - Stores it  

5. The LLM converts structured data into a clean answer.

6. Streamlit displays the result.

Important:

- Streamlit never talks to GitHub directly  
- The agent never talks to GitHub directly  
- Only MCP does  

---

## Why MCP Exists

Without MCP:

- Every question would hit GitHub API  
- Rate limits  
- Slow responses  
- No persistent memory  
- No structured reasoning  

With MCP:

- GitHub is called once  
- Data is stored  
- Queries are fast  
- Results are deterministic  
- The agent can reason better  

MCP is basically:

> A local GitHub brain with memory.

---

## Local vs Cloud Behavior

### Local Mode
- SQLite is used  
- Data stored in `.github_mcp/`  
- No Supabase required  

### Cloud Mode (Render)
- Supabase Postgres is used  
- SQLite is not allowed  
- Persistent storage is external  

Same codebase, different DB backend.

Controlled using environment variables:

DB_MODE=postgres  
DATABASE_URL=Supabase connection string  

---

## Why Supabase

Render free tier:
- No persistent disk  
- No writable data directories  
- Containers reset  

SQLite won’t work reliably.

Supabase provides:
- Persistent Postgres  
- Free tier  
- Managed DB  
- Easy connection  

That’s why Supabase is used.

---

## When the Service Is "Live"

The backend is live when:

- FastAPI starts  
- No DB connection errors  
- Render shows the public URL  

The frontend (Streamlit) can now send requests.

---

## Streamlit’s Role

Streamlit is just the UI layer.

It:

- Collects credentials  
- Sends questions  
- Displays answers  

It does **not**:

- Store data  
- Call GitHub  
- Manage ingestion  
- Run MCP  

It’s purely the interface.

---

## Real Flow Summary

User  
↓  
Streamlit UI  
↓  
Agent (LangGraph)  
↓  
MCP API (Render)  
↓  
Supabase Postgres  
↓  
LLM  
↓  
Answer  

---

## Why This Architecture Works

Because:

- Tokens are passed securely  
- Data is persistent  
- The agent is deterministic  
- API usage is controlled  
- Costs stay low  
- Debugging is easy  

This is clean, practical engineering.

---
