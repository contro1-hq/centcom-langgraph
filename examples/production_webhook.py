"""Production example - interrupt mode with webhook resume.

The graph pauses at the approval node and resumes when the
CENTCOM webhook fires to your endpoint.

Requires: pip install centcom-langgraph
"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from centcom_langgraph import centcom_approval, CentcomState
from typing_extensions import TypedDict


# 1. Define your graph state
class RefundState(CentcomState):
    customer_id: str
    refund_amount: float
    reason: str
    refund_processed: bool


# 2. Define your nodes
def prepare_refund(state: dict) -> dict:
    print(f"Preparing refund of ${state['refund_amount']} for customer {state['customer_id']}")
    return {}


def execute_refund(state: dict) -> dict:
    response = state.get("centcom_response", {})
    if isinstance(response, dict) and response.get("approved"):
        print(f"Refund APPROVED - processing ${state['refund_amount']}")
        return {"refund_processed": True}
    else:
        comment = response.get("comment", "") if isinstance(response, dict) else ""
        print(f"Refund REJECTED. Comment: {comment}")
        return {"refund_processed": False}


# 3. Build the graph
graph = StateGraph(RefundState)

graph.add_node("prepare", prepare_refund)
graph.add_node("approval", centcom_approval(
    type="approval",
    question=lambda s: f"Approve ${s['refund_amount']} refund for customer {s['customer_id']}?",
    context=lambda s: f"Customer: {s['customer_id']}\nAmount: ${s['refund_amount']}\nReason: {s['reason']}",
    callback_url="https://your-app.com/centcom-webhook",
    priority="urgent",
    required_role="manager",
    metadata=lambda s: {"customer_id": s["customer_id"]},
))
graph.add_node("execute", execute_refund)

graph.add_edge(START, "prepare")
graph.add_edge("prepare", "approval")
graph.add_edge("approval", "execute")
graph.add_edge("execute", END)

app = graph.compile(checkpointer=MemorySaver())


if __name__ == "__main__":
    thread_id = "refund-cust-99"

    # Step 1: Start the graph - it will pause at the approval node
    print("Starting graph...")
    result = app.invoke(
        {
            "customer_id": "CUST-99",
            "refund_amount": 450.00,
            "reason": "Defective product",
            "refund_processed": False,
        },
        config={"configurable": {"thread_id": thread_id}},
    )
    print(f"Graph paused. CENTCOM request: {result.get('centcom_request_id')}")

    # Step 2: Simulate webhook arrival (in production, your webhook handler does this)
    print("\nSimulating webhook response...")
    webhook_payload = {
        "request_id": result.get("centcom_request_id"),
        "state": "answered",
        "response": {"approved": True, "comment": "Approved - valid defect claim"},
        "responded_by": "Jane Manager",
        "metadata": {"customer_id": "CUST-99", "langgraph_thread_id": thread_id},
    }

    final = app.invoke(
        Command(resume=webhook_payload),
        config={"configurable": {"thread_id": thread_id}},
    )
    print(f"\nFinal state: refund_processed={final['refund_processed']}")
