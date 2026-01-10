from __future__ import annotations

import os
import asyncio
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Import your existing agent
from github_agent.agent import agent, CONFIG

# -----------------------------------------------------------------------------
# FastAPI App
# -----------------------------------------------------------------------------

app = FastAPI(
    title="CodeSense API",
    description="GitHub Intelligence Agent powered by MCP + LangGraph",
    version="1.0.0",
)

# -----------------------------------------------------------------------------
# Request / Response Models
# -----------------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str
    github_username: str
    github_token: str


class AskResponse(BaseModel):
    answer: str


# -----------------------------------------------------------------------------
# Health Check
# -----------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "service": "codesense"}


# -----------------------------------------------------------------------------
# Ask Endpoint (Main API)
# -----------------------------------------------------------------------------

@app.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    """
    Main endpoint used by Streamlit or any frontend.
    """

    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    if not req.github_username or not req.github_token:
        raise HTTPException(status_code=400, detail="GitHub username and token required")

    # Inject GitHub token into environment (used by MCP ingestion/tools)
    os.environ["GITHUB_TOKEN"] = req.github_token

    # Build agent state (matches your AgentState schema)
    initial_state: Dict[str, Any] = {
        "question": req.question,
        "username": req.github_username,
        "conversation_history": [],
        "last_repo": None,
        "last_repo_user": None,
        "plan": None,
        "tool_calls": None,
        "tool_results": None,
        "final_answer": None,
    }

    try:
        result = await agent.ainvoke(initial_state)
        answer = result.get("final_answer", "No answer generated.")

        return AskResponse(answer=answer)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------------------------------------------------------
# Local Dev Runner (Optional)
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        reload=True,
    )