# LangGraph Basics – Concepts & Intuition

This document explains the **fundamental ideas behind LangGraph** using simple language and analogies.  
It is meant as a **conceptual reference**, not an implementation guide.

---

## What is LangGraph?

LangGraph is a framework for building **agent workflows** as a **graph of steps**.

It is useful when:
- An agent needs to reason step-by-step
- Each step depends on results from previous steps
- You want explicit control and debuggability

---

## Core Concepts

LangGraph is built around four ideas:

| Concept | Meaning |
|------|--------|
| Graph | The execution plan |
| Node | One step in the plan |
| Edge | The order of steps |
| State | Shared execution context |

---

## Execution Plan vs State

This distinction is critical.

| Concept | In practice |
|------|------------|
| Execution plan | The graph structure |
| Step | A node |
| Step execution | A node running |
| State | What the agent knows so far |

### Key idea

> **The graph defines _how_ execution happens.  
> The state defines _what_ has happened so far.**

---

## What is “State”?

State is the **shared memory** that flows through the graph.

It contains:
- The original user question
- Intermediate decisions
- Tool outputs
- The final answer

Every node:
- Reads from state
- Writes back to state

LangGraph itself does **not** remember anything — the **state does**.

---

## Why State Exists

State makes the system:
- Explicit
- Deterministic
- Easy to debug
- Easy to extend

Nothing important is hidden.

---

## Nodes (Steps)

A node represents:
- A single logical step
- One responsibility
- One transformation of state

Examples:
- Decide what to do
- Execute a tool
- Summarize results

---

## Analogy: Cooking Recipe

| Cooking | LangGraph |
|------|----------|
| Recipe | Graph |
| Step | Node |
| Ingredients + food | State |
| Cooking progress | State evolution |

You don’t change the recipe while cooking — you change the food.

---

## What LangGraph Is Not

LangGraph does **not**:
- Automatically manage chat memory
- Decide which tools to use
- Store data permanently
- Loop unless you define it

All of that must be modeled explicitly using state and edges.

---

## Why This Model Scales

This design enables:
- Branching logic
- Retries
- Multi-step planning
- Clear reasoning paths
- Production-grade debugging

