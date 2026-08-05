"""FastAPI app: chat endpoint + static UI."""

import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent import AgentResult, run_agent

app = FastAPI(title="SpendIQ Copilot")

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/vendor", StaticFiles(directory=STATIC_DIR / "vendor"), name="vendor")


class ChatRequest(BaseModel):
    messages: list[dict]
    thread_id: str | None = None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict:
    from .db import DB_PATH
    return {"status": "ok", "db_exists": DB_PATH.exists()}


@app.post("/api/chat")
def chat(req: ChatRequest) -> AgentResult:
    """Run the agent over the conversation. Sync def -> FastAPI threadpool,
    so the blocking LLM call does not stall the event loop."""
    messages = [{"role": m["role"], "content": m["content"]} for m in req.messages if m.get("content")]
    if not messages:
        return {"answer": "Ask me anything about spend, contracts, or policies.", "tools": [], "sources": []}
    thread_id = req.thread_id or uuid.uuid4().hex[:12]
    return run_agent(messages, thread_id)
