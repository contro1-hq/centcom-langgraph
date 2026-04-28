"""Core approval node factory for LangGraph graphs."""

from __future__ import annotations

import os
import hashlib
from typing import Callable, Optional, Union

from centcom import CentcomClient
from langgraph.types import interrupt

from .types import CONTINUATION_MODES, INTERACTION_TYPES, NODE_NAME_KEY, THREAD_ID_KEY

# Type alias: static value or callable that receives state
Resolvable = Union[str, Callable[[dict], str]]
ResolvableDict = Union[dict, Callable[[dict], dict], None]


def _resolve(value: Resolvable, state: dict) -> str:
    """Resolve a static value or call it with state."""
    return value(state) if callable(value) else value


def _resolve_dict(value: ResolvableDict, state: dict) -> Optional[dict]:
    """Resolve a dict value or call it with state."""
    if value is None:
        return None
    return value(state) if callable(value) else value


def _to_contro1_thread_id(thread_id: str) -> str:
    if thread_id.startswith("thr_") and len(thread_id) <= 68:
        return thread_id
    return f"thr_lg_{hashlib.sha256(thread_id.encode('utf-8')).hexdigest()[:32]}"


def centcom_approval(
    *,
    type: Resolvable,
    question: Resolvable,
    context: Resolvable,
    callback_url: Resolvable,
    api_key: Optional[str] = None,
    base_url: str = "https://api.contro1.com/api/centcom/v1",
    priority: str = "normal",
    required_role: Optional[str] = None,
    continuation_mode: str = "decision",
    department: Optional[str] = None,
    metadata: ResolvableDict = None,
) -> Callable:
    """Factory that returns a LangGraph-compatible node function for CENTCOM approval.

    The node creates a CENTCOM approval request and then pauses the graph via
    interrupt(), waiting for external resume via Command(resume=webhook_payload).

    Args:
        type: Interaction type - "yes_no", "free_text", or "approval".
              Can be a callable (state) -> str for dynamic values.
        question: The question for the human operator.
        context: Background info displayed to the operator.
        callback_url: Webhook URL for response delivery.
        api_key: CENTCOM API key. Falls back to CENTCOM_API_KEY env var.
        base_url: CENTCOM API base URL.
        priority: "normal" (10 min SLA) or "urgent" (3 min SLA).
        required_role: Role required to answer (e.g. "manager").
        continuation_mode: "decision" or "instruction" response mode.
        department: Optional department id for routing metadata.
        metadata: Extra data returned in the callback. Can be callable.
                  thread_id is auto-injected for webhook correlation.
    Returns:
        A LangGraph node function with signature (state, config) -> dict.

    Example:
        graph.add_node("approve", centcom_approval(
            type="approval",
            question=lambda s: f"Approve refund for order {s['order_id']}?",
            context=lambda s: s["order_context"],
            callback_url="https://my-app.com/centcom-webhook",
        ))
    """
    resolved_api_key = api_key or os.environ.get("CENTCOM_API_KEY", "")

    def _node(state: dict, config: dict = None) -> dict:
        key = resolved_api_key
        if not key:
            raise ValueError(
                "CENTCOM API key required. Pass api_key= or set CENTCOM_API_KEY env var."
            )

        # Extract thread_id and node name from LangGraph config for correlation
        configurable = (config or {}).get("configurable", {})
        thread_id = configurable.get("thread_id", "")
        contro1_thread_id = _to_contro1_thread_id(str(thread_id)) if thread_id else ""
        node_name = configurable.get("langgraph_node", "centcom_approval")

        if not thread_id:
            raise ValueError(
                "LangGraph thread_id is required in config.configurable.thread_id "
                "for webhook correlation."
            )

        resolved_type = _resolve(type, state)
        resolved_context = _resolve(context, state)
        resolved_question = _resolve(question, state)
        resolved_callback_url = _resolve(callback_url, state)

        if resolved_type not in INTERACTION_TYPES:
            supported = ", ".join(sorted(INTERACTION_TYPES))
            raise ValueError(f"Invalid type '{resolved_type}'. Supported types: {supported}")

        if continuation_mode not in CONTINUATION_MODES:
            supported_modes = ", ".join(sorted(CONTINUATION_MODES))
            raise ValueError(f"Invalid continuation_mode '{continuation_mode}'. Supported modes: {supported_modes}")

        if not resolved_callback_url:
            raise ValueError("callback_url is required for webhook delivery.")

        # Build idempotency key from thread_id + node to prevent duplicate requests
        # (LangGraph re-runs the node from the top on resume).
        idempotency_key = f"lg:{thread_id}:{node_name}" if thread_id else None

        # Merge user metadata with correlation metadata
        user_meta = _resolve_dict(metadata, state) or {}
        full_metadata = {
            **user_meta,
            THREAD_ID_KEY: thread_id,
            "contro1_thread_id": contro1_thread_id,
            NODE_NAME_KEY: node_name,
        }

        # Create the CENTCOM request (idempotent - safe to call twice)
        client = CentcomClient(api_key=key, base_url=base_url)
        try:
            protocol_request_type = "input" if resolved_type == "free_text" else ("decision" if resolved_type == "yes_no" else "review")
            protocol_priority = "urgent" if priority == "urgent" else "normal"
            req = client.create_protocol_request(
                {
                    "title": resolved_question,
                    "description": resolved_context,
                    "request_type": protocol_request_type,
                    "source": {
                        "integration": "langgraph",
                        "framework": "langgraph",
                        "workflow_id": node_name,
                        "run_id": thread_id,
                        "session_id": thread_id,
                    },
                    "routing": {
                        "department": department,
                        "required_role": required_role,
                        "priority": protocol_priority,
                    },
                    "context": {
                        "tool_name": node_name,
                        "summary": resolved_context,
                    },
                    "continuation": {
                        "mode": continuation_mode,
                        "callback_url": resolved_callback_url,
                    },
                    "external_request_id": idempotency_key,
                    "thread_id": contro1_thread_id,
                    "metadata": full_metadata,
                }
            )
            request_id = req["id"]
        finally:
            client.close()

        # Pause the graph - checkpointer persists state.
        # On resume, interrupt() returns the value passed via Command(resume=...).
        response = interrupt({
            "centcom_request_id": request_id,
            "type": resolved_type,
            "question": resolved_question,
        })

        # response is the webhook payload passed by the resume caller
        return {
            "centcom_request_id": request_id,
            "centcom_response": (
                response.get("structured_response")
                if isinstance(response, dict) and response.get("structured_response") is not None
                else response.get("response")
                if isinstance(response, dict)
                else response
            ),
            "centcom_status": (
                response.get("status")
                if isinstance(response, dict) and response.get("status")
                else response.get("state", "answered")
                if isinstance(response, dict)
                else "answered"
            ),
        }

    return _node
