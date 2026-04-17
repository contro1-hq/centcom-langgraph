"""Optional webhook handler helper - bridges CENTCOM webhooks to LangGraph resume."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Optional

from centcom import verify_webhook
from langgraph.types import Command

logger = logging.getLogger(__name__)

from .types import THREAD_ID_KEY


def create_webhook_handler(
    *,
    webhook_secret: str,
    get_graph: Callable[[], Any],
    get_thread_id: Optional[Callable[[dict], str]] = None,
):
    """Create a webhook handler that auto-resumes LangGraph threads on CENTCOM callbacks.

    The handler verifies the HMAC signature, extracts the thread_id from
    the payload metadata, and resumes the graph with the webhook payload.

    Args:
        webhook_secret: Your org's webhook signing secret (whsec_xxx).
        get_graph: Callable returning the compiled LangGraph graph instance.
        get_thread_id: Optional callable (payload) -> thread_id.
                       Defaults to extracting from payload.metadata.langgraph_thread_id.

    Returns:
        An async handler function compatible with FastAPI, or usable directly.

    Example (FastAPI):
        handler = create_webhook_handler(
            webhook_secret="whsec_xxx",
            get_graph=lambda: compiled_graph,
        )

        @app.post("/centcom-webhook")
        async def webhook(request: Request):
            return await handler(request)
    """
    def _extract_thread_id(payload: dict) -> str:
        meta = payload.get("metadata", {})
        return meta.get(THREAD_ID_KEY, "")

    resolve_thread_id = get_thread_id or _extract_thread_id

    async def handler(request: Any) -> dict:
        """Process incoming CENTCOM webhook and resume the LangGraph thread.

        Works with FastAPI Request objects or any object with:
        - async body() method returning bytes
        - headers dict-like with get()
        """
        # Read raw body
        if hasattr(request, "body"):
            raw_body = await request.body()
        else:
            raise TypeError("Expected a request object with an async body() method")

        raw_text = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else raw_body

        # Extract signature headers
        signature = request.headers.get("x-centcom-signature", "")
        timestamp = request.headers.get("x-centcom-timestamp", "")

        # Verify HMAC signature
        if not verify_webhook(raw_text, signature, timestamp, webhook_secret):
            logger.warning("Invalid webhook signature - rejecting")
            return {"error": "Invalid signature", "status": 401}

        # Parse payload
        payload = json.loads(raw_text)
        thread_id = resolve_thread_id(payload)

        if not thread_id:
            logger.warning("No thread_id in webhook payload metadata - cannot resume")
            return {"error": "Missing thread_id in metadata", "status": 400}

        # Resume the LangGraph thread
        try:
            graph = get_graph()
            await asyncio.to_thread(
                graph.invoke,
                Command(resume=payload),
                {"configurable": {"thread_id": thread_id}},
            )
            logger.info(f"Resumed LangGraph thread {thread_id} with CENTCOM response")
            return {"status": "resumed", "thread_id": thread_id}
        except Exception as e:
            logger.error(f"Failed to resume thread {thread_id}: {e}")
            # Return 200 anyway to prevent CENTCOM retries on already-resumed threads
            return {"status": "error", "message": str(e)}

    return handler
