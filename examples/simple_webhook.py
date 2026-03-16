"""Minimal webhook-only example.

This example starts a graph that pauses at a CENTCOM approval node.
When an operator answers in the dashboard, CENTCOM sends a webhook
to your endpoint. Your webhook handler resumes the same thread.
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from centcom_langgraph import CentcomState, centcom_approval


class OrderState(CentcomState):
    order_id: str
    order_total: float
    approved: bool


def prepare_order(state: dict) -> dict:
    print(f"Prepared order {state['order_id']} total=${state['order_total']}")
    return {}


def process_result(state: dict) -> dict:
    response = state.get("centcom_response", {})
    approved = bool(response.get("approved")) if isinstance(response, dict) else False
    print(f"Operator decision: {'APPROVED' if approved else 'REJECTED'}")
    return {"approved": approved}


graph = StateGraph(OrderState)
graph.add_node("prepare_order", prepare_order)
graph.add_node(
    "human_approval",
    centcom_approval(
        type="approval",
        question=lambda s: f"Approve order #{s['order_id']} for ${s['order_total']}?",
        context=lambda s: (
            f"Order #{s['order_id']}\n"
            f"Total: ${s['order_total']}\n"
            "Requires manager approval."
        ),
        callback_url="https://your-app.com/centcom-webhook",
        priority="urgent",
        required_role="manager",
    ),
)
graph.add_node("process_result", process_result)

graph.add_edge(START, "prepare_order")
graph.add_edge("prepare_order", "human_approval")
graph.add_edge("human_approval", "process_result")
graph.add_edge("process_result", END)

app = graph.compile(checkpointer=MemorySaver())

if __name__ == "__main__":
    thread_id = "order-42"
    result = app.invoke(
        {"order_id": "ORD-42", "order_total": 750.00, "approved": False},
        config={"configurable": {"thread_id": thread_id}},
    )
    print(
        "Graph paused at human approval. "
        "Wait for CENTCOM dashboard response and webhook resume."
    )
    print(f"Pending request id: {result.get('centcom_request_id')}")
