# centcom-langgraph

Human approval nodes for [LangGraph](https://github.com/langchain-ai/langgraph) workflows, powered by [CENTCOM](https://contro1.com).

Drop a CENTCOM approval node into any LangGraph graph. The connector uses LangGraph's native `interrupt()` to pause graphs and resume them when operators respond in the CENTCOM dashboard. The operator response is delivered back to your app via webhook and used to resume the graph - no thread blocked, fully persistent.

## Install

```bash
pip install centcom-langgraph

# With webhook handler (FastAPI)
pip install centcom-langgraph[webhook]
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
    config={"configurable": {"thread_id": "order-42"}},
)
```

## Runtime Flow

1. Your graph reaches `centcom_approval(...)` and sends a request to CENTCOM.
2. The node calls `interrupt(...)`, so execution pauses and state is checkpointed.
3. An operator answers in the CENTCOM dashboard.
4. CENTCOM sends the signed response payload to your webhook endpoint.
5. Your webhook handler verifies the signature and resumes LangGraph with `Command(resume=payload)`.

## Official Resources

- SDK repository: [github.com/contro1-hq/centcom-langgraph](https://github.com/contro1-hq/centcom-langgraph)
- Official skill file: [skills/centcom-langgraph.md](https://github.com/contro1-hq/centcom-langgraph/blob/main/skills/centcom-langgraph.md)

## API

### `centcom_approval(**kwargs)`

Factory returning a LangGraph node. Parameters accept static values or `(state) -> value` callables.

### `centcom_tool(**kwargs)`

LangChain `@tool` for agent graphs where the LLM decides when to request approval.

### `create_webhook_handler(**kwargs)`

Async handler that verifies CENTCOM webhooks and resumes LangGraph threads.

### `CentcomState`

TypedDict mixin adding `centcom_request_id`, `centcom_response`, `centcom_status` to your graph state.

## Docs

Full documentation at [contro1.com/docs](https://contro1.com/docs).
