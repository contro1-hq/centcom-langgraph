---
name: centcom-langgraph
description: Guide for integrating CENTCOM human approval into existing LangGraph workflows
user_invocable: true
---

# CENTCOM + LangGraph Integration Guide

You are helping a developer integrate CENTCOM (Human-in-the-Loop approval API) into their existing LangGraph codebase. Follow this guide to analyze their code and add CENTCOM approval nodes.

## Step 1: Understand Their Graph

Read the user's LangGraph graph code. Identify:
- The graph state TypedDict
- Existing nodes and edges
- Where human approval should be inserted (ask the user if unclear)
- Whether they use a checkpointer (required)

## Step 2: Add CentcomState to Their State

Their existing state needs to extend `CentcomState`:

```python
from centcom_langgraph import CentcomState

# Before:
class MyState(TypedDict):
    messages: list
    ...

# After:
class MyState(CentcomState):
    messages: list
    ...
```

This adds: `centcom_request_id`, `centcom_response`, `centcom_status` to the state.

## Step 3: Add the Approval Node

Insert `centcom_approval()` between the node that needs approval and the node that acts on it:

```python
from centcom_langgraph import centcom_approval

graph.add_node("human_approval", centcom_approval(
    type="approval",           # or "yes_no", "free_text"
    question=lambda s: "...",  # dynamic from state
    context=lambda s: "...",   # background info for operator
    callback_url="https://their-app.com/centcom-webhook",
    priority="normal",         # or "urgent" for 3min SLA
    required_role="manager",   # optional role filter
    metadata=lambda s: {...},  # extra data for correlation
))
```

## Step 4: Wire the Edges

```python
# Before: graph.add_edge("prepare", "execute")
# After:
graph.add_edge("prepare", "human_approval")
graph.add_edge("human_approval", "execute")
```

## Step 5: Handle the Response Downstream

In the node after approval, read from state:

```python
def execute_action(state: dict) -> dict:
    status = state.get("centcom_status")
    response = state.get("centcom_response", {})

    if status == "answered":
        if response.get("approved"):  # for approval type
            # proceed
        else:
            # rejected
    elif status in ("expired", "cancelled", "timeout"):
        # handle failure
```

## Step 6: Add Webhook Handler (Production)

CENTCOM responses from the dashboard are delivered to the customer's webhook endpoint.
They must expose a webhook endpoint to resume the paused LangGraph thread:

```python
from centcom_langgraph import create_webhook_handler
from fastapi import FastAPI, Request

handler = create_webhook_handler(
    webhook_secret="whsec_xxx",
    get_graph=lambda: compiled_graph,
)

app = FastAPI()

@app.post("/centcom-webhook")
async def webhook(request: Request):
    result = await handler(request)
    return result
```

## Step 7: Ensure Checkpointer

Webhook resume flow requires a checkpointer:

```python
# Development:
from langgraph.checkpoint.memory import MemorySaver
app = graph.compile(checkpointer=MemorySaver())

# Production:
from langgraph.checkpoint.postgres import PostgresSaver
app = graph.compile(checkpointer=PostgresSaver(conn_string))
```

## Key Points to Mention

- **API Key**: Set `CENTCOM_API_KEY` env var or pass `api_key=` parameter
- **Thread ID**: Auto-injected into CENTCOM metadata for webhook correlation
- **Idempotency**: Safe to retry — duplicate requests are prevented automatically
- **Webhook-only flow**: Operator answers in dashboard, response always arrives via webhook
- **Conditional approval**: Use `question=lambda s: ...` for dynamic questions based on state
- **Agent tool**: For agent graphs where LLM decides when to ask, use `centcom_tool()` instead

## Common Patterns

### Conditional Routing After Approval
```python
def route_after_approval(state: dict) -> str:
    if state.get("centcom_status") == "answered":
        response = state.get("centcom_response", {})
        if response.get("approved"):
            return "execute"
    return "cancel"

graph.add_conditional_edges("human_approval", route_after_approval)
```

### Multiple Approval Points
Use different node names — each gets its own idempotency key:
```python
graph.add_node("manager_approval", centcom_approval(..., required_role="manager"))
graph.add_node("finance_approval", centcom_approval(..., required_role="finance"))
```
