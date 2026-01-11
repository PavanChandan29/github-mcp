from __future__ import annotations

import os
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from github_mcp.common import connect, get_db_path
from github_mcp.ingest import ingest
from github_agent.agent import agent

import asyncio

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
        db_path = get_db_path("healthcheck")
        conn = connect(db_path)
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
# Ingest Route
# -------------------------------------------------
@app.post("/ingest")
async def ingest_user(data: IngestRequest):
    try:
        os.environ["GITHUB_TOKEN"] = data.github_token

        LOGGER.info(f"Starting ingestion for user={data.username}")

        await ingest(
            user=data.username,
            token=data.github_token,
            max_commits=200,
        )

        return {"message": "Ingestion completed"}

    except Exception as e:
        LOGGER.exception("Ingestion failed")
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------
# Query Route
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