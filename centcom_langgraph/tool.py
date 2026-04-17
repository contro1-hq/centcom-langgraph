"""LangChain tool variant for agent-style graphs where the LLM decides when to request approval."""

from __future__ import annotations

import os
from typing import Optional

from centcom import CentcomClient
from langchain_core.tools import tool as langchain_tool
from langgraph.types import interrupt

from .types import CONTINUATION_MODES, NODE_NAME_KEY


def centcom_tool(
    *,
    api_key: Optional[str] = None,
    base_url: str = "https://contro1.com/api/centcom/v1",
    callback_url: str,
    continuation_mode: str = "decision",
):
    """Create a LangChain tool for CENTCOM human approval.

    Use this in agent-style graphs where the LLM decides when to request
    human approval. The tool uses interrupt() to pause the graph.

    Args:
        api_key: CENTCOM API key. Falls back to CENTCOM_API_KEY env var.
        base_url: CENTCOM API base URL.
        callback_url: Webhook URL for response delivery.
        continuation_mode: "decision" or "instruction" response mode.
    Returns:
        A LangChain tool function compatible with ToolNode.

    Example:
        tool = centcom_tool(api_key="cc_live_xxx", callback_url="https://...")
        graph.add_node("tools", ToolNode([tool, other_tools...]))
    """
    resolved_key = api_key or os.environ.get("CENTCOM_API_KEY", "")
    if continuation_mode not in CONTINUATION_MODES:
        supported_modes = ", ".join(sorted(CONTINUATION_MODES))
        raise ValueError(f"Invalid continuation_mode '{continuation_mode}'. Supported modes: {supported_modes}")

    @langchain_tool
    def request_human_approval(
        question: str,
        context: str,
        type: str = "approval",
        priority: str = "normal",
        required_role: str = "",
    ) -> dict:
        """Request human approval for an action. Use this when you need a human
        to review or approve something before proceeding.

        Args:
            question: The question for the human operator.
            context: Background info to help the operator decide.
            type: Interaction type - "yes_no", "free_text", or "approval".
            priority: "normal" (10 min SLA) or "urgent" (3 min SLA).
            required_role: Role required to answer (e.g. "manager"). Empty for any operator.
        """
        key = resolved_key
        if not key:
            raise ValueError(
                "CENTCOM API key required. Pass api_key= or set CENTCOM_API_KEY env var."
            )

        client = CentcomClient(api_key=key, base_url=base_url)
        try:
            protocol_request_type = "input" if type == "free_text" else ("decision" if type == "yes_no" else "review")
            protocol_priority = "urgent" if priority == "urgent" else "normal"
            req = client.create_protocol_request(
                {
                    "title": question,
                    "description": context,
                    "request_type": protocol_request_type,
                    "source": {
                        "integration": "langgraph-tool",
                        "framework": "langgraph",
                    },
                    "routing": {
                        "required_role": required_role or None,
                        "priority": protocol_priority,
                    },
                    "context": {
                        "tool_name": "centcom_tool",
                        "summary": context,
                    },
                    "continuation": {
                        "mode": continuation_mode,
                        "callback_url": callback_url,
                    },
                    "metadata": {NODE_NAME_KEY: "centcom_tool"},
                }
            )
            request_id = req["id"]
        finally:
            client.close()

        response = interrupt({
            "centcom_request_id": request_id,
            "type": type,
            "question": question,
        })
        if isinstance(response, dict):
            return {
                "request_id": request_id,
                "response": response.get("structured_response", response.get("response")),
                "status": response.get("status", response.get("state", "answered")),
            }
        return {"request_id": request_id, "response": response, "status": "answered"}

    return request_human_approval
