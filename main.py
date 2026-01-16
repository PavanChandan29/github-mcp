from __future__ import annotations

import os
import logging
import asyncio
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel

from github_mcp.common import connect
from github_mcp.ingest import ingest
from github_agent.agent import agent
from github_mcp.user_service import upsert_user

# -------------------------------------------------
# Logging
# -------------------------------------------------
LOGGER = logging.getLogger("codesense_api")
logging.basicConfig(level=logging.INFO)

# -------------------------------------------------
# FastAPI App
# -------------------------------------------------
app = FastAPI(title="CodeSense API", version="1.0")

# -------------------------------------------------
# Models
# -------------------------------------------------
class IngestRequest(BaseModel):
    username: str
    github_token: str


class QueryRequest(BaseModel):
    username: str
    question: str


# -------------------------------------------------
# Startup: Test DB / Supabase Connection
# -------------------------------------------------
@app.on_event("startup")
def startup_check():
    try:
        conn = connect()

        if os.environ.get("DB_MODE") == "postgres":
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
        else:
            conn.execute("SELECT 1;")

        conn.close()
        LOGGER.info("✅ Database connection successful")

    except Exception as e:
        LOGGER.error(f"❌ Database connection failed: {e}")


# -------------------------------------------------
# Health Route
# -------------------------------------------------
@app.get("/")
def health():
    return {
        "status": "CodeSense API is running",
        "db_mode": os.environ.get("DB_MODE", "sqlite"),
        "supabase": bool(os.environ.get("DATABASE_URL")),
    }


# -------------------------------------------------
# Background Ingestion Worker
# -------------------------------------------------
def run_ingestion_job(username: str, token: str):
    try:
        os.environ["GITHUB_TOKEN"] = token

        asyncio.run(
            ingest(
                user=username,
                token=token,
                max_commits=200,
            )
        )

    except Exception as e:
        LOGGER.exception(f"Ingestion failed for {username}")
        upsert_user(
            user_name=username,
            status="failed",
            repo_count=0,
            error=str(e),
        )


# -------------------------------------------------
# Ingest Route (Non-Blocking)
# -------------------------------------------------
@app.post("/ingest")
async def ingest_user(data: IngestRequest, background_tasks: BackgroundTasks):
    try:
        LOGGER.info(f"Starting background ingestion for user={data.username}")

        # Mark as in-progress
        upsert_user(
            user_name=data.username,
            status="in_progress",
            repo_count=0,
            error=None,
        )

        background_tasks.add_task(
            run_ingestion_job,
            data.username,
            data.github_token,
        )

        return {
            "status": "started",
            "message": f"Ingestion started for {data.username}",
        }

    except Exception as e:
        LOGGER.exception("Failed to start ingestion")
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------
# User Status Route
# -------------------------------------------------
@app.get("/users/{username}")
def get_user_status(username: str):
    try:
        conn = connect()

        if os.environ.get("DB_MODE") == "postgres":
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM users WHERE username = %s",
                    (username,),
                )
                user = cur.fetchone()
        else:
            cur = conn.execute(
                "SELECT * FROM users WHERE username = ?",
                (username,),
            )
            user = cur.fetchone()
            user = dict(user) if user else None

        conn.close()
        return user or {"status": "not_found"}

    except Exception as e:
        LOGGER.exception("Failed to fetch user status")
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------
# Query Route (Instant)
# -------------------------------------------------
@app.post("/query")
async def query_user(data: QueryRequest):
    try:
        LOGGER.info(f"Query for user={data.username}: {data.question}")

        initial_state = {
            "question": data.question,
            "username": data.username,
            "conversation_history": [],
            "last_repo": None,
            "last_repo_user": None,
            "tool_name": None,
            "tool_args": None,
            "tool_result": None,
            "final_answer": None,
        }

        result = await agent.ainvoke(initial_state)

        return {
            "answer": result.get("final_answer", "No response generated"),
            "repo": result.get("last_repo"),
        }

    except Exception as e:
        LOGGER.exception("Query failed")
        raise HTTPException(status_code=500, detail=str(e))