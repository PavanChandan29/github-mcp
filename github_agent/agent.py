from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict, cast

import yaml
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

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
    conversation_history: List[Dict[str, str]]  # Previous messages
    last_repo: Optional[str]  # Last repository discussed
    last_repo_user: Optional[str]  # Last repository user
    plan: Optional[Dict[str, Any]]  # Semantic plan (may include multi-step)
    tool_calls: Optional[List[Dict[str, Any]]]  # Planned tool calls
    tool_results: Optional[List[Dict[str, Any]]]  # Results per tool call
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
# MCP client helper + tool catalog caching
# ============================================================

_TOOL_CATALOG: Optional[List[Dict[str, Any]]] = None


def _resolve_server_params() -> StdioServerParameters:
    """
    Resolve server command paths relative to this file directory.
    MCP_CFG["server_command"] is expected like:
      ["python", "../github_mcp/server.py", ...]
    """
    server_cmd = MCP_CFG["server_command"].copy()
    resolved_args: list[str] = []
    for arg in server_cmd[1:]:
        if arg and not os.path.isabs(arg):
            resolved_path = (BASE_DIR / arg).resolve()
            resolved_args.append(str(resolved_path) if resolved_path.exists() else arg)
        else:
            resolved_args.append(arg)

    return StdioServerParameters(command=server_cmd[0], args=resolved_args)


async def _with_mcp_session(fn):
    server = _resolve_server_params()
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await fn(session)


async def get_tool_catalog() -> List[Dict[str, Any]]:
    """
    Cache the MCP tool catalog (names + inputSchema).
    """
    global _TOOL_CATALOG
    if _TOOL_CATALOG is not None:
        return _TOOL_CATALOG

    async def _fetch(session: ClientSession):
        tools = await session.list_tools()
        out: List[Dict[str, Any]] = []
        for t in tools.tools:
            out.append(
                {
                    "name": getattr(t, "name", ""),
                    "description": getattr(t, "description", "") or "",
                    "inputSchema": getattr(t, "inputSchema", {}) or {},
                }
            )
        return out

    _TOOL_CATALOG = await _with_mcp_session(_fetch)
    return _TOOL_CATALOG


async def call_mcp_tool(tool: str, args: dict) -> Any:
    async def _call(session: ClientSession):
        result = await session.call_tool(tool, args)
        return result.content

    return await _with_mcp_session(_call)


def unwrap_mcp_content(content: Any) -> Any:
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
        return getattr(content, "text")

    # JsonContent
    if hasattr(content, "json"):
        return getattr(content, "json")

    # Fallback (stringify)
    return str(content)


def make_json_safe(obj: Any) -> Any:
    """
    Recursively convert objects into JSON-serializable structures.
    Prevents crashes like: 'Object of type method is not JSON serializable'
    """
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [make_json_safe(x) for x in obj]
    return str(obj)

# ============================================================
# Semantic planning (intent reasoning)
# ============================================================

def _looks_like_greeting(q: str) -> bool:
    ql = (q or "").strip().lower()
    return ql in {"hi", "hello", "hey", "hii", "yo"} or ql.startswith(("hi ", "hello ", "hey "))


def _compact_history(history: List[Dict[str, str]], n: int = 6) -> str:
    """
    Keep the last N messages as compact context for planning.
    """
    if not history:
        return ""
    recent = history[-n:]
    lines: List[str] = []
    for m in recent:
        role = m.get("role", "")
        content = (m.get("content", "") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


async def semantic_plan(state: AgentState) -> AgentState:
    """
    Use the LLM to produce a semantic plan:
      - direct answer (no tool)
      - single tool call
      - multi-step tool calls (e.g., latest repo -> overview)
    """
    question = state["question"].strip()
    username = state.get("username") or CONFIG.get("github", {}).get("default_user", "")
    last_repo = state.get("last_repo")
    last_repo_user = state.get("last_repo_user")
    history = state.get("conversation_history") or []

    # No-tool fast path for greetings / social chatter
    if _looks_like_greeting(question):
        state["plan"] = {
            "type": "direct_answer",
            "answer": "Hello. You can ask me about a GitHub user’s repositories (tech stack, CI/CD, tests, activity, etc.).",
        }
        state["tool_calls"] = []
        state["tool_results"] = []
        return state

    tools = await get_tool_catalog()

    tool_brief = []
    for t in tools:
        tool_brief.append(
            {
                "name": t.get("name"),
                "description": t.get("description", ""),
                "inputSchema": t.get("inputSchema", {}),
            }
        )

    context_note = ""
    if last_repo and last_repo_user:
        context_note = (
            f"Last discussed repo: {last_repo_user}/{last_repo}. "
            "If the user uses pronouns ('this project', 'that repo', 'it'), you may use it."
        )

    planner_system = SystemMessage(
        content=(
            "You are a semantic planner for a GitHub analysis assistant.\n"
            "You MUST output a single JSON object only.\n\n"
            "Your job:\n"
            "- Decide whether the user needs tool calls.\n"
            "- If so, select the best tool(s) from the provided catalog.\n"
            "- Support multi-step plans when required (e.g., 'tech stack of latest project' needs list_repos then get_repo_overview).\n\n"
            "Planning constraints:\n"
            "- Prefer multi-repo tools for questions across repositories (e.g., 'any repo with CI/CD', 'which repos use Python').\n"
            "- Prefer single-repo tools only when the question is explicitly about one repo or a pronoun refers to last repo.\n"
            "- If the question is ambiguous and cannot be answered safely, propose a short clarification_question.\n\n"
            "Output JSON schema:\n"
            "{\n"
            '  "type": "direct_answer" | "tool_plan" | "clarify",\n'
            '  "answer": string (only for direct_answer),\n'
            '  "clarification_question": string (only for clarify),\n'
            '  "tool_calls": [\n'
            "     {\"tool_name\": string, \"tool_args\": object, \"save_as\": string (optional)}\n"
            "  ]\n"
            "}\n"
        )
    )

    planner_user = HumanMessage(
        content=(
            f"Default GitHub user: {username}\n"
            f"{context_note}\n\n"
            "Recent conversation:\n"
            f"{_compact_history(history)}\n\n"
            "Tool catalog:\n"
            f"{json.dumps(tool_brief, indent=2)}\n\n"
            f"User question:\n{question}\n"
        )
    )

    resp = llm.invoke([planner_system, planner_user])
    raw = resp.content.strip()

    # Strict JSON parse with one retry
    try:
        plan = json.loads(raw)
    except json.JSONDecodeError:
        retry = llm.invoke(
            [
                SystemMessage(content="Return ONLY valid JSON matching the required schema. No text."),
                planner_user,
            ]
        )
        plan = json.loads(retry.content.strip())

    # Post-processing: fill defaults, enforce user, handle pronouns for repo tools.
    plan_type = plan.get("type", "tool_plan")
    tool_calls = plan.get("tool_calls", []) or []

    # If model returned tool_plan but empty tool_calls, convert to clarify
    if plan_type == "tool_plan" and not tool_calls:
        plan_type = "clarify"
        plan["type"] = "clarify"
        plan["clarification_question"] = plan.get(
            "clarification_question",
            "Which repository (name) or which GitHub username should I use for this question?",
        )

    # Normalize tool calls: ensure user default, handle pronoun repo reference
    normalized_calls: List[Dict[str, Any]] = []
    for c in tool_calls:
        tool_name = c.get("tool_name")
        tool_args = c.get("tool_args", {}) or {}
        if isinstance(tool_args, str):
            # sometimes LLM emits tool_args as stringified json
            try:
                tool_args = json.loads(tool_args)
            except Exception:
                tool_args = {}

        # default user
        if "user" not in tool_args and username:
            tool_args["user"] = username

        # if repo required but missing, use last repo if available
        if tool_name in {"get_repo_overview", "get_commit_timeline", "get_repo_signals"}:
            if "repo" not in tool_args and last_repo and last_repo_user:
                tool_args["repo"] = last_repo
                tool_args["user"] = last_repo_user

        normalized_calls.append(
            {
                "tool_name": tool_name,
                "tool_args": tool_args,
                "save_as": c.get("save_as"),
            }
        )

    plan["type"] = plan_type
    plan["tool_calls"] = normalized_calls

    state["plan"] = plan
    state["tool_calls"] = normalized_calls
    state["tool_results"] = []
    return state

# ============================================================
# Execute tools (supports multi-step plans)
# ============================================================

async def execute_tools(state: AgentState) -> AgentState:
    plan = state.get("plan") or {}
    if plan.get("type") != "tool_plan":
        state["tool_results"] = []
        return state

    tool_calls = state.get("tool_calls") or []
    results: List[Dict[str, Any]] = []

    # Used for simple in-plan passing (save_as references)
    memory: Dict[str, Any] = {}

    for i, call in enumerate(tool_calls):
        tool_name = call.get("tool_name")
        tool_args = call.get("tool_args") or {}

        # Simple variable substitution if tool_args contains {"repo":"$latest.repo"} etc.
        # We keep it conservative: only replace strings starting with "$".
        for k, v in list(tool_args.items()):
            if isinstance(v, str) and v.startswith("$"):
                key = v[1:]
                tool_args[k] = memory.get(key, v)

        raw = await call_mcp_tool(cast(str, tool_name), cast(dict, tool_args))
        unwrapped = unwrap_mcp_content(raw)
        safe = make_json_safe(unwrapped)

        # Save-as support
        save_as = call.get("save_as")
        if save_as:
            memory[save_as] = safe

        # Convenience: if list_repos, store latest repo name for downstream steps
        if tool_name == "list_repos":
            repos = safe
            if isinstance(repos, str):
                try:
                    repos = json.loads(repos)
                except Exception:
                    repos = None
            if isinstance(repos, list) and repos and isinstance(repos[0], dict):
                latest = sorted(repos, key=lambda r: r.get("pushed_at", "") or "", reverse=True)[0]
                latest_repo = latest.get("repo") or latest.get("name")
                memory["latest.repo"] = latest_repo
                memory["latest"] = latest

                # update conversational "last repo"
                if latest_repo:
                    state["last_repo"] = latest_repo
                    state["last_repo_user"] = (state.get("username") or CONFIG.get("github", {}).get("default_user", ""))

        # Update last repo context on single-repo tools
        if tool_name in {"get_repo_overview", "get_commit_timeline", "get_repo_signals"}:
            if isinstance(safe, dict) and "error" not in safe:
                if "repo" in tool_args and "user" in tool_args:
                    state["last_repo"] = tool_args["repo"]
                    state["last_repo_user"] = tool_args["user"]

        results.append(
            {
                "tool_name": tool_name,
                "tool_args": make_json_safe(tool_args),
                "result": safe,
            }
        )

    state["tool_results"] = results
    return state

# ============================================================
# Synthesis (grounded answer)
# ============================================================

def synthesize_answer(state: AgentState) -> AgentState:
    plan = state.get("plan") or {}

    # Direct answer path
    if plan.get("type") == "direct_answer":
        answer = plan.get("answer") or ""
        state["final_answer"] = answer
        # persist history
        hist = state.get("conversation_history") or []
        hist.append({"role": "user", "content": state["question"]})
        hist.append({"role": "assistant", "content": answer})
        state["conversation_history"] = hist
        return state

    # Clarification path
    if plan.get("type") == "clarify":
        cq = plan.get("clarification_question") or "Can you clarify what repository or GitHub user you mean?"
        state["final_answer"] = cq
        hist = state.get("conversation_history") or []
        hist.append({"role": "user", "content": state["question"]})
        hist.append({"role": "assistant", "content": cq})
        state["conversation_history"] = hist
        return state

    # Tool plan path
    tool_results = state.get("tool_results") or []

    # Centralized tool error handling
    for tr in tool_results:
        res = tr.get("result")
        if isinstance(res, dict) and res.get("error"):
            msg = (
                f"Tool Error from {tr.get('tool_name')}: {res.get('error')}\n\n"
                "If this is a missing-ingestion issue, re-run ingestion and retry."
            )
            state["final_answer"] = msg
            hist = state.get("conversation_history") or []
            hist.append({"role": "user", "content": state["question"]})
            hist.append({"role": "assistant", "content": msg})
            state["conversation_history"] = hist
            return state

    synthesis_system = SystemMessage(
        content=(
            "You are a GitHub analysis assistant. You MUST answer using ONLY the provided tool outputs.\n\n"
            "Rules:\n"
            "- If the question is about tech stack, prioritize detected tech stack fields (e.g., signals.tech_stack) over repo.language.\n"
            "- For multi-repo questions (CI/CD, tests, Docker, language usage), summarize across repositories using the multi-repo tool results.\n"
            "- If the tool output lacks a detail, explicitly say it is not available.\n"
            "- Do not hallucinate frameworks/tools that are not in tool outputs.\n"
        )
    )

    # IMPORTANT: ensure JSON-serializable
    tool_bundle = {
        "question": state["question"],
        "username": state.get("username") or CONFIG.get("github", {}).get("default_user", ""),
        "last_repo": state.get("last_repo"),
        "tool_results": tool_results,
    }
    safe_bundle = make_json_safe(tool_bundle)

    resp = llm.invoke(
        [
            synthesis_system,
            HumanMessage(content=json.dumps(safe_bundle, indent=2)),
        ]
    )

    answer = resp.content
    state["final_answer"] = answer

    hist = state.get("conversation_history") or []
    hist.append({"role": "user", "content": state["question"]})
    hist.append({"role": "assistant", "content": answer})
    state["conversation_history"] = hist
    return state

# ============================================================
# Build LangGraph
# ============================================================

graph = StateGraph(AgentState)
graph.add_node("semantic_plan", semantic_plan)
graph.add_node("execute_tools", execute_tools)
graph.add_node("synthesize_answer", synthesize_answer)

graph.set_entry_point("semantic_plan")
graph.add_edge("semantic_plan", "execute_tools")
graph.add_edge("execute_tools", "synthesize_answer")
graph.add_edge("synthesize_answer", END)

agent = graph.compile()

# ============================================================
# CLI entrypoint (keeps conversation context across turns)
# ============================================================

def main() -> None:
    print("GitHub MCP Agent (LangGraph) — Semantic Planner + Multi-Repo Tools")
    print("Type 'exit' or 'quit' to stop.\n")

    # Persist context across turns
    conversation_history: List[Dict[str, str]] = []
    last_repo: Optional[str] = None
    last_repo_user: Optional[str] = None

    while True:
        question = input("Question: ").strip()
        if question.lower() in {"exit", "quit"}:
            break

        initial_state: AgentState = {
            "question": question,
            "username": CONFIG.get("github", {}).get("default_user"),
            "conversation_history": conversation_history,
            "last_repo": last_repo,
            "last_repo_user": last_repo_user,
            "plan": None,
            "tool_calls": None,
            "tool_results": None,
            "final_answer": None,
        }

        result = asyncio.run(agent.ainvoke(initial_state))

        # Print
        print("\nAnswer:\n", result.get("final_answer", ""))
        print("\n" + "-" * 60 + "\n")

        # Carry forward context
        conversation_history = result.get("conversation_history", conversation_history)
        last_repo = result.get("last_repo", last_repo)
        last_repo_user = result.get("last_repo_user", last_repo_user)

if __name__ == "__main__":
    main()