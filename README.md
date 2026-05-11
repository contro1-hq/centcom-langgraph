# centcom-langgraph

Human approval nodes for [LangGraph](https://github.com/langchain-ai/langgraph) workflows, powered by [CENTCOM](https://contro1.com).

Drop a CENTCOM approval node into any LangGraph graph. The connector uses LangGraph's native `interrupt()` to pause graphs and resume them when operators respond in the CENTCOM dashboard. The operator response is delivered back to your app via webhook and used to resume the graph - no thread blocked, fully persistent.

This connector normalizes requests through **Contro1 Integration Protocol v1**.

## Install

```bash
pip install centcom-langgraph

# With webhook handler (FastAPI)
pip install centcom-langgraph[webhook]
```

## Environment variables

```bash
CENTCOM_API_KEY=cc_live_your_key
CENTCOM_BASE_URL=https://api.contro1.com/api/centcom/v1
CENTCOM_WEBHOOK_SECRET=whsec_your_signing_secret
```

## Quick Start

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from centcom_langgraph import centcom_approval, CentcomState

class MyState(CentcomState):
    order_id: str
    approved: bool

graph = StateGraph(MyState)
graph.add_node("approve", centcom_approval(
    type="approval",
    question=lambda s: f"Approve order {s['order_id']}?",
    context=lambda s: f"Order {s['order_id']} needs approval",
    callback_url="https://my-app.com/centcom-webhook",
))

graph.add_edge(START, "approve")
graph.add_edge("approve", END)

app = graph.compile(checkpointer=MemorySaver())
result = app.invoke(
    {"order_id": "ORD-42", "approved": False},
    config={"configurable": {"thread_id": "order-42"}},  # LangGraph's own state key
)
```

## Runtime Flow

1. Your graph reaches `centcom_approval(...)` and sends a request to CENTCOM.
2. The node calls `interrupt(...)`, so execution pauses and state is checkpointed.
3. An operator answers in the CENTCOM dashboard.
4. CENTCOM sends the signed response payload to your webhook endpoint.
5. Your webhook handler verifies the signature and resumes LangGraph with `Command(resume=payload)`.

## Case continuity

LangGraph's `config.configurable.thread_id` is LangGraph's own state key. The connector maps it to Contro1's `correlation_id` automatically. Every approval node and audit log entry in the same LangGraph run shares one case timeline in the CENTCOM dashboard.

Use `client.log_action` to record autonomous actions in the same case:

```python
client.log_action(
    action="langgraph.email_sent",
    summary="Sent policy-approved customer follow-up email",
    source={"integration": "langgraph", "workflow_id": "refund_flow", "run_id": langgraph_thread_id},
    outcome="success",
    correlation_id=case_id,          # provided by the connector from LangGraph thread
    in_reply_to={"type": "request", "id": request_id},  # links back to the approval
)
```

## Control Map preview

Before adding a high-risk approval node, verify that routing is satisfiable - the required reviewers are mapped and available. Cache this for 5–15 minutes; do not call it on every graph invocation.

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
    # preview["suggested_action"] describes the admin fix
    raise RuntimeError(f"Routing not ready: {preview['warnings']}")
```

Response fields: `satisfiable` (bool), `status` (`ready` | `needs_mapping` | `needs_capacity`), `warnings`, `suggested_action`.

## API

### `centcom_approval(**kwargs)`

Factory returning a LangGraph node. Parameters accept static values or `(state) -> value` callables.
Supports `continuation_mode="decision" | "instruction"` and protocol routing metadata propagation.

### `centcom_tool(**kwargs)`

LangChain `@tool` for agent graphs where the LLM decides when to request approval.

### `create_webhook_handler(**kwargs)`

Async handler that verifies CENTCOM webhooks and resumes LangGraph threads.

### `CentcomState`

TypedDict mixin adding `centcom_request_id`, `centcom_response`, `centcom_status` to your graph state.

## Production pattern: Agent Plugin

For teams running multiple graphs with overlapping governance requirements, a thin plugin reduces token overhead and keeps policy consistent:

```python
from datetime import datetime, timedelta
from centcom import CentcomClient

class Contro1Plugin:
    """Wraps Contro1 calls. preview_policy is TTL-cached."""

    def __init__(self, client: CentcomClient, cache_ttl_minutes: int = 10):
        self._client = client
        self._cache: dict = {}
        self._ttl = timedelta(minutes=cache_ttl_minutes)

    def preview_policy(self, approval_requirements: dict, approval_policy: dict) -> dict:
        key = str(sorted(approval_requirements.items()))
        cached = self._cache.get(key)
        if cached and datetime.utcnow() < cached["expires"]:
            return cached["data"]
        result = self._client.post("/requests/control-map", {
            "approval_requirements": approval_requirements,
            "approval_policy": approval_policy,
        })
        self._cache[key] = {"data": result, "expires": datetime.utcnow() + self._ttl}
        return result

    def request_human_review(self, payload: dict) -> dict:
        return self._client.create_protocol_request(payload)

    def log_audit_action(self, payload: dict) -> dict:
        return self._client.log_action(**payload)

    def resume_from_decision(self, case_id: str) -> dict:
        return self._client.get(f"/cases/{case_id}")
```

## Official Resources

- SDK repository: [github.com/contro1-hq/centcom-langgraph](https://github.com/contro1-hq/centcom-langgraph)
- Core Python SDK (`centcom`): [github.com/contro1-hq/centcom](https://github.com/contro1-hq/centcom)
- Official skill file: [skills/centcom-langgraph.md](https://github.com/contro1-hq/centcom-langgraph/blob/main/skills/centcom-langgraph.md)
- Full docs: [contro1.com/docs](https://contro1.com/docs)

## Governance readiness

For teams operating AI in regulated environments:
- [EU AI Act readiness guide](https://contro1.com/guides/eu-ai-act-readiness)
- [US AI Governance readiness guide](https://contro1.com/guides/us-ai-governance-readiness)
