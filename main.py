from __future__ import annotations

import os
import logging
import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from concurrent.futures import ThreadPoolExecutor

from github_mcp.common import connect
from github_mcp.ingest import ingest
from github_agent.agent import agent
from github_mcp.user_service import upsert_user

# -------------------------------------------------
# Logging
# -------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    force=True,
)
LOGGER = logging.getLogger("BitofGit_API")

# -------------------------------------------------
# FastAPI App
# -------------------------------------------------
app = FastAPI(title="BitofGit API", version="1.0")

# Thread pool for background ingestion
executor = ThreadPoolExecutor(max_workers=2)

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
# Startup: Test DB + Print Users
# -------------------------------------------------
@app.on_event("startup")
def startup_check():
    try:
        conn = connect()

        if os.environ.get("DB_MODE") == "postgres":
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.execute("SELECT username FROM users;")
                users = cur.fetchall()
        else:
            conn.execute("SELECT 1;")
            cur = conn.execute("SELECT username FROM users;")
            users = cur.fetchall()

        conn.close()

        LOGGER.info("✅ Database connection successful")
        LOGGER.info(f"📌 Existing users in DB: {users}")

    except Exception as e:
        LOGGER.error(f"❌ Database connection failed: {e}")


# -------------------------------------------------
# Health Route
# -------------------------------------------------
@app.get("/")
def health():
    return {
        "status": "BitofGit API is running",
        "db_mode": os.environ.get("DB_MODE", "sqlite"),
        "supabase": bool(os.environ.get("DATABASE_URL")),
    }


# -------------------------------------------------
# Background Ingestion Worker (THREAD SAFE)
# -------------------------------------------------
def run_ingestion_job(username: str, token: str):
    try:
        print(f"🔥 Ingestion thread started for {username}", flush=True)
        LOGGER.info(f"Starting ingestion job for {username}")

        os.environ["GITHUB_TOKEN"] = token

        asyncio.run(
            ingest(
                user=username,
                token=token,
                max_commits=200,
            )
        )

        LOGGER.info(f"✅ Ingestion completed for {username}")

        upsert_user(
            user_name=username,
            status="completed",
            repo_count=0,
            error=None,
        )

    except Exception as e:
        LOGGER.exception(f"❌ Ingestion failed for {username}")
        upsert_user(
            user_name=username,
            status="failed",
            repo_count=0,
            error=str(e),
        )


# -------------------------------------------------
# Ingest Route (Non-Blocking + Reliable)
# -------------------------------------------------
@app.post("/ingest")
async def ingest_user(data: IngestRequest):
    try:
        LOGGER.info(f"🚀 Ingest API hit for user={data.username}")

        upsert_user(
            user_name=data.username,
            status="in_progress",
            repo_count=0,
            error=None,
        )

        # Force background execution via thread
        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            executor,
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

        LOGGER.info(f"📊 Status fetched for {username}: {user}")
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
        LOGGER.info(f"💬 Query for {data.username}: {data.question}")

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

        LOGGER.info(f"🤖 Answer generated for {data.username}")

        return {
            "answer": result.get("final_answer", "No response generated"),
            "repo": result.get("last_repo"),
        }

    except Exception as e:
        LOGGER.exception("Query failed")
        raise HTTPException(status_code=500, detail=str(e))