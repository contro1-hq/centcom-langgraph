"""Graph state mixin for CENTCOM approval fields."""

from __future__ import annotations

from typing import Optional

from typing_extensions import TypedDict


class CentcomState(TypedDict, total=False):
    """Mixin for LangGraph state — add CENTCOM approval fields to your graph state.

    Usage:
        class MyState(CentcomState):
            messages: list
            order_id: str
    """

    centcom_request_id: Optional[str]
    """The CENTCOM request ID (set after request creation)."""

    centcom_response: Optional[dict]
    """The operator's response payload."""

    centcom_status: Optional[str]
    """Terminal status: 'answered', 'expired', 'cancelled', or 'timeout'."""
