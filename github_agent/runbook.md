# LangGraph + MCP Agent – Common Errors Runbook

This runbook captures the core mistakes and failure patterns encountered while building an agent using **LangGraph** with an **MCP (Model Context Protocol)** server. It focuses on framework usage, data structures, and integration boundaries.

---

## 1. MCP Server Confusion (Already Running vs Used)

### Symptom
- Confusion about whether the MCP server is already running
- Manually running `python -m github_mcp.server`

### Cause
- Misunderstanding **MCP stdio transport**

### Rule
- `stdio_client` **always spawns a new MCP server process**
- It never connects to an existing server

### Fix
- Do not manually run the MCP server when using `stdio_client`

---

## 2. Wrong Server Configuration Type

### Symptom
- `AttributeError: 'list' object has no attribute 'command'`

### Cause
- Passing a raw command list instead of an MCP server configuration object

### Rule
- MCP requires a structured server configuration, not shell-style commands

---

## 3. Writing Raw JSON to MCP

### Symptom
- `AttributeError: 'dict' object has no attribute 'message'`

### Cause
- Attempting to write raw dictionaries directly to MCP stdin

### Rule
- MCP is a protocol, not a raw pipe

### Fix
- Always use `ClientSession`
- Never write JSON directly to stdin/stdout

---

## 4. Missing MCP Handshake

### Symptom
- Tool calls fail unexpectedly

### Cause
- `session.initialize()` not called before tool usage

### Rule
- No handshake means no valid tool calls

---

## 5. Tool Argument Schema Mismatch

### Symptom
- `McpError: Invalid request parameters`

### Cause
- Tool arguments did not exactly match the MCP tool schema

### Rule
- MCP tools enforce strict schemas
- No extra fields, no missing fields

---

## 6. Non-Serializable Tool Output

### Symptom
- `TypeError: Object of type TextContent is not JSON serializable`

### Cause
- MCP returns typed objects (`TextContent`, `JsonContent`)
- These were passed directly into `json.dumps`

### Rule
- Normalize MCP outputs before storing them in LangGraph state

---

## 7. Confusing MCP Tools vs LangGraph Nodes

### Symptom
- Treating `decide_tool` as an executable tool

### Cause
- Overloading the word “tool”

### Rule
- **MCP tools** = executable capabilities
- **LangGraph nodes** = reasoning and control steps

---

## 8. Misunderstanding State

### Symptom
- Treating state as steps or hidden memory

### Cause
- Confusing execution plan with execution context

### Rule
- **Nodes** are steps
- **State** is progress and data so far

---

## 9. Over-Trusting the LLM

### Symptom
- Wrong tool chosen
- Incorrect tool arguments

### Cause
- Expecting zero-shot correctness from the LLM

### Rule
- LLM decides intent, not correctness
- Validation is required at boundaries

---