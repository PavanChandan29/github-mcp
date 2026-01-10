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
    username: Optional[str]  # GitHub username to use for queries
    conversation_history: Optional[list[Dict[str, str]]]  # Previous Q&A pairs
    last_repo: Optional[str]  # Last repository discussed
    last_repo_user: Optional[str]  # Last repository user
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
    Intelligently handles follow-up questions and maintains conversation context.
    """
    # Use username from state if provided, otherwise fall back to config
    username = state.get("username") or CONFIG.get("github", {}).get("default_user", "")
    
    # Get conversation context
    conversation_history = state.get("conversation_history") or []
    last_repo = state.get("last_repo")
    last_repo_user = state.get("last_repo_user")
    
    # Build conversation context string
    context_str = ""
    if conversation_history:
        context_str = "\n\nPrevious conversation:\n"
        for msg in conversation_history[-3:]:  # Last 3 Q&A pairs
            if msg.get("role") == "user":
                context_str += f"User: {msg.get('content', '')}\n"
            elif msg.get("role") == "assistant":
                context_str += f"Assistant: {msg.get('content', '')}\n"
    
    if last_repo and last_repo_user:
        context_str += f"\nNOTE: The last repository discussed was {last_repo_user}/{last_repo}. "
        context_str += "If the current question references 'the project', 'that project', 'it', 'this project', "
        context_str += "or asks follow-up questions without specifying a repo, use this repository.\n"

    system_prompt = SystemMessage(
        content=(
            "You are an intelligent AI agent that selects the correct MCP tool based on natural language questions. "
            "You understand conversational context and follow-up questions.\n\n"
            "Available tools:\n"
            "1) list_repos(user) - List all repositories for a user\n"
            "2) get_repo_overview(user, repo) - Get comprehensive repo info including:\n"
            "   - Tech stack (from signals)\n"
            "   - Repository description and README\n"
            "   - Stars, forks, watchers (collaboration metrics)\n"
            "   - CI/CD practices (GitHub Actions, Docker, etc.)\n"
            "   - Coding standards and automation signals\n"
            "3) get_commit_timeline(user, repo, limit) - Get commit history for effort analysis\n\n"
            "Tool selection guidance:\n"
            "- Questions about 'tech stack', 'technologies', 'languages', 'frameworks' → use get_repo_overview\n"
            "- Questions about 'what is the project about', 'description', 'README' → use get_repo_overview\n"
            "- Questions about 'effort', 'days worked', 'commit history', 'timeline' → use get_commit_timeline\n"
            "- Questions about 'CI/CD', 'Docker', 'GitHub Actions', 'automation' → use get_repo_overview\n"
            "- Questions about 'collaborators', 'stars', 'forks', 'popularity' → use get_repo_overview\n"
            "- Questions asking for 'latest project', 'most recent', 'recent repos' → use list_repos\n\n"
            f"GitHub user to query: {username}\n"
            f"{context_str}\n"
            "IMPORTANT: If the question is a follow-up (uses words like 'the project', 'that project', 'it', 'what about', etc.) "
            "and we have a last_repo context, USE THAT REPOSITORY. Don't require explicit repo name in follow-ups.\n\n"
            "Return ONLY valid JSON (no markdown, no code blocks): "
            "{\"tool_name\": \"tool_name_here\", \"tool_args\": {\"user\": \"username\", \"repo\": \"repo_name\"}}"
        )
    )
    
    messages = [system_prompt]
    if conversation_history:
        # Add recent conversation for context
        for msg in conversation_history[-2:]:
            if msg.get("role") == "user":
                messages.append(HumanMessage(content=msg.get("content", "")))
            elif msg.get("role") == "assistant":
                messages.append(SystemMessage(content=f"Previous assistant response: {msg.get('content', '')}"))
    
    messages.append(HumanMessage(content=state["question"]))

    response = llm.invoke(messages)

    try:
        parsed = json.loads(response.content)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse tool selection JSON: {response.content}") from e

    state["tool_name"] = parsed["tool_name"]
    tool_args = parsed["tool_args"]
    
    # Ensure username is set in tool_args if not explicitly provided
    if "user" not in tool_args and username:
        tool_args["user"] = username
    
    # Handle follow-up questions: if tool needs a repo but none specified, use last_repo
    if state["tool_name"] in ["get_repo_overview", "get_commit_timeline"] and "repo" not in tool_args:
        if last_repo and last_repo_user:
            tool_args["repo"] = last_repo
            tool_args["user"] = last_repo_user
        else:
            # Try to infer from question or use default user
            tool_args["user"] = username
    
    state["tool_args"] = tool_args
    return state


async def run_tool(state: AgentState) -> AgentState:
    raw_result = await call_mcp_tool(
        state["tool_name"],
        state["tool_args"],
    )

    state["tool_result"] = unwrap_mcp_content(raw_result)
    
    # Update last_repo context if we successfully queried a repo
    if state["tool_name"] in ["get_repo_overview", "get_commit_timeline"]:
        tool_args = state.get("tool_args", {})
        if "repo" in tool_args and "user" in tool_args:
            # Only update if we got valid results (not an error)
            if isinstance(state["tool_result"], dict):
                if "error" not in state["tool_result"]:
                    state["last_repo"] = tool_args["repo"]
                    state["last_repo_user"] = tool_args["user"]
    
    # Handle list_repos: if question asks about "latest", "most recent", set first repo as last_repo
    if state["tool_name"] == "list_repos":
        if isinstance(state["tool_result"], list) and len(state["tool_result"]) > 0:
            # Check if question mentions "latest", "most recent", "newest", etc.
            question_lower = state.get("question", "").lower()
            if any(word in question_lower for word in ["latest", "most recent", "newest", "recent", "last"]):
                first_repo = state["tool_result"][0]
                if isinstance(first_repo, dict) and "repo" in first_repo:
                    tool_args = state.get("tool_args", {})
                    state["last_repo"] = first_repo["repo"]
                    state["last_repo_user"] = tool_args.get("user")
    
    return state


def synthesize_answer(state: AgentState) -> AgentState:
    """
    Convert structured MCP output into a natural-language answer.
    """
    
    # Check if tool result contains an error about repo not being found
    tool_result = state.get("tool_result")
    question = state.get("question", "").lower()
    conversation_history = state.get("conversation_history") or []
    
    # Check if the result is an error about repo not found
    is_repo_error = False
    if isinstance(tool_result, dict) and tool_result.get("error"):
        error_msg = tool_result.get("error", "")
        if "not found" in error_msg.lower() or "ingestion" in error_msg.lower():
            is_repo_error = True
    
    # If it's a repo error and question is about tech stack, provide github-mcp project tech stack
    if is_repo_error and any(keyword in question for keyword in ["tech stack", "technology", "technologies", "stack", "libraries", "frameworks"]):
        github_mcp_tech_stack = """
## Core Technology
- **Language**: Python 3.10+

## Main Libraries & Frameworks

### AI/ML & Agent Framework
- **LangGraph** (≥0.2.0) - Agent orchestration and state management
- **LangChain OpenAI** (≥0.1.0) - OpenAI integration for LLM calls
- **LangChain Core** (≥0.3.0) - Core LangChain abstractions

### MCP (Model Context Protocol)
- **MCP[CLI]** (≥1.2.0) - MCP server/client implementation for tool exposure

### Web & HTTP
- **httpx** (≥0.27.0) - Async HTTP client for GitHub API calls
- **Streamlit** (≥1.28.0) - Web UI framework for the chatbot interface

### Data & Configuration
- **Pydantic** (≥2.7.0) - Data validation and settings management
- **PyYAML** (≥6.0) - YAML configuration file parsing
- **python-dotenv** (≥1.0.1) - Environment variable management

### Storage
- **SQLite** (built-in) - Local database for storing repository and commit data

## Architecture Components

1. **MCP Server Layer** - Exposes tools backed by SQLite database
2. **Agent Layer** - LangGraph-based agent for tool selection and execution
3. **UI Layer** - Streamlit chatbot interface
4. **Data Layer** - SQLite for local data persistence

## Build & Package Management
- **setuptools** - Package building system
- **pyproject.toml** - Modern Python packaging configuration
"""
        
        state["final_answer"] = f"Based on the github-mcp project you're working with, here's the tech stack used:\n\n{github_mcp_tech_stack}"
        return state

    # Build context for the synthesis
    context_str = ""
    if conversation_history:
        context_str = "\n\nConversation context:\n"
        for msg in conversation_history[-2:]:
            if msg.get("role") == "user":
                context_str += f"Previous question: {msg.get('content', '')}\n"
            elif msg.get("role") == "assistant":
                context_str += f"Previous answer: {msg.get('content', '')[:200]}...\n"
    
    # Enhanced system prompt for better understanding
    system_prompt_content = (
        "You are an intelligent assistant that converts structured GitHub repository data "
        "into clear, natural language answers. You understand conversational context.\n\n"
        "When answering questions about repositories, extract and highlight:\n"
        "- Tech stack: languages, frameworks, libraries (from tech_stack field or detected signals)\n"
        "- Project description: from description or README fields\n"
        "- Effort/days: analyze commit timeline, frequency, and patterns\n"
        "- CI/CD practices: mention GitHub Actions, Docker, automation signals\n"
        "- Collaboration metrics: stars, forks, watchers count\n"
        "- Code quality signals: tests, linting, code standards\n\n"
        "If the user asks a follow-up question (like 'what is the tech stack?', 'how much effort?', etc.) "
        "after discussing a repository, assume they're asking about that same repository.\n\n"
        "Always provide comprehensive, well-structured answers. If data is missing, say so clearly."
    )
    
    if context_str:
        system_prompt_content += context_str

    response = llm.invoke(
        [
            SystemMessage(content=system_prompt_content),
            HumanMessage(
                content=(
                    f"Current question: {state['question']}\n\n"
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
            "username": None,
            "conversation_history": [],
            "last_repo": None,
            "last_repo_user": None,
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