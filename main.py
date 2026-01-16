from __future__ import annotations

import os
import sys
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
# Force real-time logging (important for EC2)
# -------------------------------------------------
sys.stdout.reconfigure(line_buffering=True)

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
    user_name: str
    github_token: str


class QueryRequest(BaseModel):
    user_name: str
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
                cur.execute("SELECT user_name FROM users;")
                users = cur.fetchall()
        else:
            conn.execute("SELECT 1;")
            cur = conn.execute("SELECT user_name FROM users;")
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
def run_ingestion_job(user_name: str, token: str):
    """
    This runs in a background thread.
    We MUST force Postgres here because env vars
    are not inherited reliably across threads.
    """

    try:
        # Force Postgres mode
        os.environ["DB_MODE"] = "postgres"
        os.environ["DATABASE_URL"] = os.getenv("DATABASE_URL")
        os.environ["GITHUB_TOKEN"] = token

        LOGGER.info(f"🔥 Ingestion thread started for {user_name}")
        LOGGER.info(f"🧠 DB_MODE inside thread = {os.environ.get('DB_MODE')}")

        # Create a fresh event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        loop.run_until_complete(
            ingest(
                user_name,
                token,
                200,
            )
        )

        loop.close()

        LOGGER.info(f"✅ Ingestion completed for {user_name}")

        upsert_user(
            user_name=user_name,
            status="completed",
            repo_count=0,
            error=None,
        )

    except Exception as e:
        LOGGER.exception(f"❌ Ingestion failed for {user_name}")

        upsert_user(
            user_name=user_name,
            status="failed",
            repo_count=0,
            error=str(e),
        )


# -------------------------------------------------
# Ingest Route (Non-Blocking)
# -------------------------------------------------
@app.post("/ingest")
async def ingest_user(data: IngestRequest):
    try:
        LOGGER.info(f"🚀 Ingest API hit for user={data.user_name}")

        upsert_user(
            user_name=data.user_name,
            status="in_progress",
            repo_count=0,
            error=None,
        )

        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            executor,
            run_ingestion_job,
            data.user_name,
            data.github_token,
        )

        return {
            "status": "started",
            "message": f"Ingestion started for {data.user_name}",
        }

    except Exception as e:
        LOGGER.exception("Failed to start ingestion")
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------
# User Status Route
# -------------------------------------------------
@app.get("/users/{user_name}")
def get_user_status(user_name: str):
    try:
        conn = connect()

        if os.environ.get("DB_MODE") == "postgres":
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM users WHERE user_name = %s",
                    (user_name,),
                )
                user = cur.fetchone()
        else:
            cur = conn.execute(
                "SELECT * FROM users WHERE user_name = ?",
                (user_name,),
            )
            user = cur.fetchone()
            user = dict(user) if user else None

        conn.close()

        LOGGER.info(f"📊 Status fetched for {user_name}: {user}")
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
        LOGGER.info(f"💬 Query for {data.user_name}: {data.question}")

        initial_state = {
            "question": data.question,
            "user_name": data.user_name,
            "conversation_history": [],
            "last_repo": None,
            "last_repo_user": None,
            "tool_name": None,
            "tool_args": None,
            "tool_result": None,
            "final_answer": None,
        }

        result = await agent.ainvoke(initial_state)

        LOGGER.info(f"🤖 Answer generated for {data.user_name}")

        return {
            "answer": result.get("final_answer", "No response generated"),
            "repo": result.get("last_repo"),
        }

    except Exception as e:
        LOGGER.exception("Query failed")
        raise HTTPException(status_code=500, detail=str(e))