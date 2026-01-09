from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import TypedDict, Optional, Dict, Any

from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client
from mcp.types import CallToolRequest
from mcp import StdioServerParameters

import yaml
from dotenv import load_dotenv

from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters


# ============================================================
# Load configuration and secrets
# ============================================================

BASE_DIR = Path(__file__).parent

# Load secrets (NOT committed)
load_dotenv(BASE_DIR / "secrets.env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY not found in environment or secrets.env")

# Load config (committed)
with open(BASE_DIR / "config.yaml", "r", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

LLM_CFG = CONFIG["llm"]
MCP_CFG = CONFIG["mcp"]


# ============================================================
# Agent state
# ============================================================

class AgentState(TypedDict):
    question: str
    tool_name: Optional[str]
    tool_args: Optional[Dict[str, Any]]
    tool_result: Optional[Any]
    final_answer: Optional[str]


# ============================================================
# LLM initialization
# ============================================================

llm = ChatOpenAI(
    api_key=OPENAI_API_KEY,
    model=LLM_CFG.get("model", "gpt-4"),
    temperature=LLM_CFG.get("temperature", 0),
    max_tokens=LLM_CFG.get("max_tokens", 1024),
)


# ============================================================
# MCP client helper
# ============================================================

async def call_mcp_tool(tool: str, args: dict) -> object:
    # Resolve server command paths relative to config file location
    server_cmd = MCP_CFG["server_command"].copy()
    # Resolve relative paths in args
    resolved_args = []
    for arg in server_cmd[1:]:
        if arg and not os.path.isabs(arg):
            # Resolve relative to config file directory
            resolved_path = (BASE_DIR / arg).resolve()
            if resolved_path.exists():
                resolved_args.append(str(resolved_path))
            else:
                resolved_args.append(arg)
        else:
            resolved_args.append(arg)
    
    server = StdioServerParameters(
        command=server_cmd[0],
        args=resolved_args,
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            # IMPORTANT: handshake
            await session.initialize()

            tools = await session.list_tools()
            print("TOOLS:", [t.name for t in tools.tools])
            # Optional: print full schema for one tool
            for t in tools.tools:
                if t.name == tool:
                    print("SCHEMA FOR", t.name, ":", t.inputSchema)

            # Now tool calls are valid
            result = await session.call_tool(tool, args)
            return result.content

def unwrap_mcp_content(content):
    """
    Normalize MCP tool output into JSON-serializable data.
    """
    if content is None:
        return None

    # MCP may return a list of content blocks
    if isinstance(content, list):
        return [unwrap_mcp_content(c) for c in content]

    # TextContent
    if hasattr(content, "text"):
        return content.text

    # JsonContent
    if hasattr(content, "json"):
        return content.json

    # Fallback (stringify)
    return str(content)

# ============================================================
# LangGraph nodes
# ============================================================

def decide_tool(state: AgentState) -> AgentState:
    """
    Decide which MCP tool to call and with what arguments.
    """
    default_user = CONFIG.get("github", {}).get("default_user", "")

    system_prompt = SystemMessage(
        content=(
            "You are an AI agent that selects the correct MCP tool.\n\n"
            "Available tools:\n"
            "1) list_repos(user)\n"
            "2) get_repo_overview(user, repo)\n"
            "3) get_commit_timeline(user, repo)\n\n"
            f"Default GitHub user is: {default_user}\n"
            "If the question says 'pavan', use the default user.\n\n"
            "Return ONLY valid JSON: "
            "{\"tool_name\": \"...\", \"tool_args\": {...}}"
        )
    )

    response = llm.invoke(
        [
            system_prompt,
            HumanMessage(content=state["question"]),
        ]
    )

    try:
        parsed = json.loads(response.content)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse tool selection JSON: {response.content}") from e

    state["tool_name"] = parsed["tool_name"]
    state["tool_args"] = parsed["tool_args"]
    return state


async def run_tool(state: AgentState) -> AgentState:
    raw_result = await call_mcp_tool(
        state["tool_name"],
        state["tool_args"],
    )

    state["tool_result"] = unwrap_mcp_content(raw_result)
    return state


def synthesize_answer(state: AgentState) -> AgentState:
    """
    Convert structured MCP output into a natural-language answer.
    """

    response = llm.invoke(
        [
            SystemMessage(
                content=(
                    "You are an assistant that converts structured GitHub data "
                    "into a concise, clear answer for the user."
                )
            ),
            HumanMessage(
                content=(
                    f"User question:\n{state['question']}\n\n"
                    f"MCP tool result:\n{json.dumps(state['tool_result'], indent=2)}"
                )
            ),
        ]
    )

    state["final_answer"] = response.content
    return state


# ============================================================
# Build LangGraph
# ============================================================

graph = StateGraph(AgentState)

graph.add_node("decide_tool", decide_tool)
graph.add_node("run_tool", run_tool)
graph.add_node("synthesize_answer", synthesize_answer)

graph.set_entry_point("decide_tool")
graph.add_edge("decide_tool", "run_tool")
graph.add_edge("run_tool", "synthesize_answer")
graph.add_edge("synthesize_answer", END)

agent = graph.compile()


# ============================================================
# CLI entrypoint
# ============================================================

def main():
    print("GitHub MCP Agent (LangGraph)")
    print("Type 'exit' or 'quit' to stop.\n")

    while True:
        question = input("Question: ").strip()
        if question.lower() in {"exit", "quit"}:
            break

        initial_state = {
            "question": question,
            "tool_name": None,
            "tool_args": None,
            "tool_result": None,
            "final_answer": None,
        }

        result = asyncio.run(agent.ainvoke(initial_state))
        print("\nAnswer:\n", result["final_answer"])
        print("\n" + "-" * 60 + "\n")

if __name__ == "__main__":
    main()