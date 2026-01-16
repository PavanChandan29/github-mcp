# BitofGit EC2 Runbook

## Backend Deployment on AWS EC2

This document explains how the BitofGit backend (FastAPI + GitHub MCP + SQLite) is deployed and run on an AWS EC2 instance.

### Goals

The goal of this setup is to:
- Keep the backend always running
- Allow Streamlit (frontend) to call it via HTTP
- Avoid paid platforms and complex infrastructure
- Maintain full control over the system

---

## Architecture Overview

The system has two main parts:

### 1. Streamlit Frontend (Cloud)
- Hosted on Streamlit Cloud
- Collects GitHub username and token from the user
- Sends API requests to the backend

### 2. FastAPI Backend (AWS EC2)
- Runs on an AWS EC2 instance
- Handles GitHub ingestion
- Runs the MCP server
- Stores data in SQLite
- Communicates with OpenAI

**Important:** The frontend never talks to GitHub directly. All GitHub access happens through the EC2 backend.

---

## EC2 Instance Setup

### Instance Type
- Amazon Linux
- Free tier (t2.micro or similar)
- Public IPv4 enabled

### Security Group Rules

**Inbound rules:**
- Port 22 → SSH
- Port 8000 (or 10000) → FastAPI

> ⚠️ Without opening the API port, Streamlit cannot reach the backend.

### Connecting to EC2

You can connect using:
- EC2 Instance Connect (browser)
- Or SSH with a key file

Once connected, all setup is done in the terminal.

---

## Installing Dependencies

The following are installed on the EC2 instance:
- Python 3
- pip
- git
- virtualenv (optional)

**Setup steps:**
1. Clone the GitHub repository
2. Create a virtual environment
3. Install dependencies from `requirements.txt`

---

## Environment Variables

These environment variables must be set:
- `OPENAI_API_KEY`
- `GITHUB_TOKEN` (optional if passed from UI)
- `DEPLOY_MODE=cloud`

They are added to:
- `~/.bashrc`
- or `~/.profile`

This ensures they persist after reboot.

---

## Backend Startup

The backend runs using:
- FastAPI
- Uvicorn

**Main entry point:** `main.py`

**Exposed endpoints:**
- `/health`
- `/ingest`
- `/query`

Once started, you should see:
```
BitofGit API is running
```

**Verify the server:**
```
http://EC2_PUBLIC_IP:8000/health
```

---

## Runtime Flow

### Step 1 – User Opens Streamlit App

The user enters:
- GitHub username
- GitHub token

These values are stored in Streamlit session state.

### Step 2 – Ingestion Request

Streamlit sends: `POST /ingest`

**Payload includes:**
- `username`
- `github_token`

**The EC2 backend:**
- Calls the GitHub API
- Fetches repositories and commits
- Stores everything in SQLite
- Initializes MCP tools

This happens once per user session.

### Step 3 – Query Request

Streamlit sends: `POST /query`

**Payload includes:**
- `username`
- `question`

**The backend:**
- Uses MCP tools
- Retrieves repository data
- Calls OpenAI
- Returns a structured answer

Streamlit displays the result.

---

## Database Mode

**Currently:**
- SQLite is used
- Stored at `/tmp/github_mcp.db`

This is lightweight and free.

> Postgres or Supabase can be added later if needed.

---

## MCP Server Behavior

The MCP server:
- Runs inside the FastAPI process
- Exposes tools such as:
  - `list_repos`
  - `get_repo_overview`
  - `get_commit_timeline`

**Important:** The LLM never calls GitHub directly. It only interacts with MCP tools.

---

## Restarting the Server

If the EC2 instance reboots:

1. Reconnect to EC2
2. Activate the virtual environment
3. Start the FastAPI server again

> Optional: Tools like `tmux`, `screen`, or `systemd` can be added later for auto-restart.

---

## Updating the Code

When you push changes to GitHub:

1. SSH into EC2
2. Pull the latest changes
3. Restart the server

> Streamlit automatically redeploys when the GitHub repo updates.

---

## Why This Setup Works Well

- ✅ No platform limits
- ✅ Full control
- ✅ Free tier friendly
- ✅ Persistent backend
- ✅ Real API access
- ✅ No GitHub rate issues
- ✅ No Streamlit timeouts

---

## Known Limitations

- ⚠️ SQLite resets on instance restart
- ⚠️ No auto-scaling
- ⚠️ Manual restarts
- ⚠️ Single-user optimized
