# Contro1 LangGraph Skill

Use this when integrating Contro1 into LangGraph.

## Rules

- Use `centcom_approval()` for graph nodes that must pause for an operator.
- Use `centcom_tool()` when the model decides whether to request approval.
- Use `CentcomClient.log_action()` for allowed autonomous actions that should be auditable.
- LangGraph's `config.configurable.thread_id` is LangGraph's own state key. The connector maps it to Contro1's `correlation_id` so all approval nodes in the same LangGraph thread appear in one Contro1 case timeline.
- Use `in_reply_to={"type": "request", "id": request_id}` when logging what happened after an operator answer.
- `in_reply_to` must point to an item in the same organization; when both `correlation_id` and `in_reply_to` are sent, they must belong to the same case.

## Case continuity

After a human approves and execution resumes, log the follow-up action in the same case so the dashboard shows the full story:

```python
client.log_action(
    action="langgraph.action_completed",
    summary="Completed the action approved by the operator",
    source={"integration": "langgraph", "workflow_id": node_name, "run_id": langgraph_thread_id},
    correlation_id=case_id,
    in_reply_to={"type": "request", "id": request_id},
)
```

---
name: centcom-langgraph
description: Guide for integrating CENTCOM human approval into existing LangGraph workflows
user_invocable: true
---

# CENTCOM + LangGraph Integration Guide

You are helping a developer integrate CENTCOM (Human-in-the-Loop approval API) into their existing LangGraph codebase. Follow this guide to analyze their code and add CENTCOM approval nodes.

## Installation

```bash
pip install centcom-langgraph
# With webhook handler (FastAPI/Starlette)
pip install centcom-langgraph[webhook]
```

## Required configuration

```bash
CENTCOM_API_KEY=cc_live_your_key
CENTCOM_BASE_URL=https://api.contro1.com/api/centcom/v1
CENTCOM_WEBHOOK_SECRET=whsec_your_signing_secret
```

The SDK reads `CENTCOM_API_KEY` and `CENTCOM_BASE_URL` automatically. Set all three before running.

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

## Step 3: Check Routing Before a High-Risk Node (Control Map)

For nodes that use `approval_policy` with required roles or two-person approval, preview routing before the graph runs. This confirms that the required reviewers are mapped and available.

```python
from centcom import CentcomClient

client = CentcomClient()

preview = client.post("/requests/control-map", {
    "approval_requirements": {"required_roles": ["finance"], "required_approvals": 2},
    "approval_policy": {
        "mode": "threshold",
        "required_approvals": 2,
        "separation_of_duties": True,
        "fail_closed_on_timeout": True,
    },
})

if not preview["satisfiable"]:
    # preview["warnings"] lists what is missing
    # preview["suggested_action"] says what an admin should do
    raise RuntimeError(f"Routing not ready: {preview['warnings']}")
```

Cache the result for 5–15 minutes. Do not call Control Map on every graph invocation.

## Step 4: Add the Approval Node

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

Role routing semantics:
- `required_role` set (for example `operator`, `manager`, `admin`) means only operators with that role can see/claim the request.
- `required_role` omitted means the request is visible to all eligible operators.
- Non-matching role claim attempts are rejected by the API with `403 forbidden`.
- Use only existing org roles (built-in or custom org-defined roles); do not invent new role names in examples.

Mini example - two-person approval for a production deploy:
```python
graph.add_node("approve_deploy", centcom_approval(
    type="approval",
    question="Approve production deploy?",
    context="Release includes billing migration.",
    callback_url="https://my-app.com/centcom-webhook",
    required_role="admin",
    approval_policy={
        "mode": "threshold",
        "required_approvals": 2,
        "required_roles": ["manager", "admin"],
        "separation_of_duties": True,
        "fail_closed_on_timeout": True,
    },
))
```

Multi-approval behavior:
- Use `approval_policy.required_approvals = 2` for production deploys, vendor payments, bulk deletion, and privilege escalation.
- The first approval records an audit event but does not resume LangGraph.
- The webhook fires only when quorum is met, a reviewer rejects, or the request times out.
- Treat timeout before quorum as fail-closed for high-risk actions.

Examples:
```python
graph.add_node("operator_approval", centcom_approval(..., required_role="operator"))
graph.add_node("manager_approval", centcom_approval(..., required_role="manager"))
graph.add_node("admin_approval", centcom_approval(..., required_role="admin"))
graph.add_node("open_queue_approval", centcom_approval(...))  # no required_role
```

## Step 5: Wire the Edges

```python
# Before: graph.add_edge("prepare", "execute")
# After:
graph.add_edge("prepare", "human_approval")
graph.add_edge("human_approval", "execute")
```

## Step 6: Handle the Response Downstream

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

## Step 7: Add Webhook Handler (Production)

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

## Step 8: Ensure Checkpointer

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
- **Case ID**: LangGraph's `config.configurable.thread_id` is mapped to Contro1 `correlation_id` automatically; all nodes in the same LangGraph run share one case timeline in the dashboard
- **Idempotency**: Safe to retry - duplicate requests are prevented automatically
- **Webhook-only flow**: Operator answers in dashboard, response always arrives via webhook
- **Conditional approval**: Use `question=lambda s: ...` for dynamic questions based on state
- **Agent tool**: For agent graphs where LLM decides when to ask, use `centcom_tool()` instead
- **Role filters**: `required_role` is optional; when provided, it limits who can claim/respond to the request

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
Use different node names - each gets its own idempotency key:
```python
graph.add_node("manager_approval", centcom_approval(..., required_role="manager"))
graph.add_node("finance_approval", centcom_approval(..., required_role="finance"))
```

## Production pattern: Agent Plugin

For teams running multiple graphs with overlapping governance requirements, wrap the Contro1 calls behind a thin plugin. This reduces prompt token usage and makes policy decisions consistent across nodes.

```python
import asyncio
from datetime import datetime, timedelta
from centcom import CentcomClient

class Contro1Plugin:
    """Thin adapter for LangGraph nodes. Cache preview_policy to avoid calling
    the Control Map endpoint on every graph invocation."""

    def __init__(self, client: CentcomClient, cache_ttl_minutes: int = 10):
        self._client = client
        self._cache: dict = {}
        self._cache_ttl = timedelta(minutes=cache_ttl_minutes)

    async def preview_policy(self, approval_requirements: dict, approval_policy: dict) -> dict:
        key = str(sorted(approval_requirements.items()))
        cached = self._cache.get(key)
        if cached and datetime.utcnow() < cached["expires"]:
            return cached["data"]
        result = await self._client.post_async("/requests/control-map", {
            "approval_requirements": approval_requirements,
            "approval_policy": approval_policy,
        })
        self._cache[key] = {"data": result, "expires": datetime.utcnow() + self._cache_ttl}
        return result

    async def request_human_review(self, payload: dict) -> dict:
        return await self._client.create_protocol_request_async(payload)

    async def log_audit_action(self, payload: dict) -> dict:
        return await self._client.log_action_async(payload)

    async def resume_from_decision(self, case_id: str) -> dict:
        return await self._client.get_async(f"/cases/{case_id}")
```

## Full reference links

- Repo: https://github.com/contro1-hq/centcom-langgraph
- Approval node implementation: https://github.com/contro1-hq/centcom-langgraph/blob/main/centcom_langgraph/node.py
- Tool implementation: https://github.com/contro1-hq/centcom-langgraph/blob/main/centcom_langgraph/tool.py
- Webhook handler docs: https://github.com/contro1-hq/centcom-langgraph
- Skill file source: https://github.com/contro1-hq/centcom-langgraph/blob/main/skills/centcom-langgraph.md
- Microsoft AGT companion skill: https://github.com/contro1-hq/contro1-microsoft-agent-governance-toolkit-integration/blob/main/skills/contro1-microsoft-agent-governance-toolkit-integration.md
- Protocol docs: https://contro1.com/docs/audit-records-and-cases

## Governance readiness

For teams operating under EU or US AI governance requirements, see:
- https://contro1.com/guides/eu-ai-act-readiness
- https://contro1.com/guides/us-ai-governance-readiness
