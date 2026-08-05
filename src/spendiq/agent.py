"""LangGraph agent: free-zen LLM + two tools, with a trace of tool calls
and sources for the UI's "Sources & Tools" panel."""

import json
import re
from typing import TypedDict

from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import create_react_agent

from .config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, MOCK
from .db import REFERENCE_DATE
from .tools import build_tools

SYSTEM_PROMPT = f"""You are SpendIQ, a conversational spend copilot for Nimbus Retail Co.
You answer finance and procurement questions about vendors, contracts,
purchase orders, invoices, and company policies.

Today's date is {REFERENCE_DATE}. Treat all date questions ("YTD", "last 12
months", "next 90 days", "last six months") relative to this date.

You have two tools:
1. query_structured_data(sql) — read-only SQL over the spend database.
   The database schema and convenience views are described in the tool.
   Prefer the pre-built views when they match the question.
2. retrieve_documents(query, doc_filter) — search contract and policy
   documents (contracts CTR-0001..CTR-0015, policies POL-*). Use this for
   clauses, terms, notice periods, renewal language, and policy rules.

Rules:
- Use the right tool(s) for the job. Cross-source questions usually need
  both: structured numbers from SQL + clause text from documents.
- ALWAYS cite your sources in the answer: invoice IDs (INV-...), PO IDs
  (PO-...), contract IDs (CTR-...), vendor IDs (VEND-...), and document
  IDs (CTR-..._... or POL-...). When quoting a clause, name the document
  and section.
- Never invent numbers, invoice IDs, or contract terms. If a tool returns
  nothing relevant, say so explicitly instead of guessing.
- If the question is ambiguous (e.g. unclear date range or entity), ask a
  short clarifying question or state the assumption you made and answer
  under it.
- When the user refers back to an earlier exchange ("those", "them", "the
  above"), restrict the answer to the entities from that previous exchange
  — do not expand to the broader dataset.
- Be concise: answer the question, then cite. A short table is fine."""


class ChatMessage(TypedDict):
    role: str
    content: str


class AgentResult(TypedDict):
    answer: str
    tools: list
    sources: list


def _build_llm():
    return ChatOpenAI(
        model=LLM_MODEL,
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        temperature=0,
        max_retries=2,
    )


def build_graph():
    """Compile the agent graph with an in-memory checkpointer."""
    tools = build_tools()
    llm = _build_llm()
    return create_react_agent(
        llm, tools,
        prompt=SYSTEM_PROMPT,
        checkpointer=InMemorySaver(),
    )


_graph = None


def get_graph():
    """Module-level singleton so the checkpointer (conversation memory)
    survives across requests inside the server process."""
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


_DOC_ID_RE = re.compile(r"\[(CTR-\d+[_\w]*|POL-\w+)\]")
_SQL_TOOL = "query_structured_data"
_RETRIEVE_TOOL = "retrieve_documents"


def _trace(messages) -> tuple[list, list]:
    """Walk the message history, collecting tool calls and cited sources."""
    tools, sources = [], []
    for msg in messages:
        if getattr(msg, "type", "") == "ai" and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                args = tc.get("args", {})
                tools.append({
                    "name": tc.get("name"),
                    "args": {k: str(v)[:200] for k, v in args.items()},
                })
        elif getattr(msg, "type", "") == "tool":
            content = str(getattr(msg, "content", ""))
            if getattr(msg, "name", "") == _RETRIEVE_TOOL:
                for doc_id in _DOC_ID_RE.findall(content):
                    if doc_id not in sources:
                        sources.append(doc_id)
    return tools, sources


def run_agent(messages: list[ChatMessage], thread_id: str) -> AgentResult:
    """Run the agent over a conversation; returns answer + trace."""
    if MOCK:
        return {
            "answer": f"(mock mode) Echo: {messages[-1]['content']}",
            "tools": [],
            "sources": [],
        }
    graph = get_graph()
    config = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke(
        {"messages": [{"role": m["role"], "content": m["content"]} for m in messages]},
        config,
    )
    answer = result["messages"][-1].content or "(no answer)"
    tools, sources = _trace(result["messages"])
    return {"answer": answer, "tools": tools, "sources": sources}
