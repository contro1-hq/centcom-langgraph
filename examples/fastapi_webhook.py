"""FastAPI webhook receiver - bridges CENTCOM webhooks to LangGraph resume.

Run this alongside your LangGraph graph to automatically resume
paused threads when operators respond.

Requires: pip install centcom-langgraph[webhook]
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from centcom_langgraph import create_webhook_handler

# Your compiled LangGraph graph (import from your graph module)
# from my_graph import app as langgraph_app
langgraph_app = None  # Replace with your compiled graph

app = FastAPI()

handler = create_webhook_handler(
    webhook_secret="whsec_your_secret_here",
    get_graph=lambda: langgraph_app,
    # Default: extracts thread_id from payload.metadata.langgraph_thread_id
    # Custom: get_thread_id=lambda p: p["metadata"]["my_custom_thread_key"],
)


@app.post("/centcom-webhook")
async def centcom_webhook(request: Request):
    result = await handler(request)
    status = result.get("status", 500)
    if isinstance(status, int) and status >= 400:
        return JSONResponse(content=result, status_code=status)
    return JSONResponse(content=result, status_code=200)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
