"""Constants and enums for the CENTCOM LangGraph connector."""

from __future__ import annotations

# Interaction types supported by CENTCOM
INTERACTION_TYPES = {"yes_no", "free_text", "approval"}

# Request states that indicate the lifecycle is complete
TERMINAL_STATES = {
    "answered", "callback_pending", "callback_delivered",
    "callback_failed", "closed", "expired", "cancelled",
}

# Metadata keys injected by the connector for thread correlation
THREAD_ID_KEY = "langgraph_thread_id"
NODE_NAME_KEY = "langgraph_node"
