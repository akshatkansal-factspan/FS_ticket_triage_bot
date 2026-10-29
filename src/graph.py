
from langgraph.graph import StateGraph, START, END

from langgraph.checkpoint.memory import MemorySaver

from src.state import TicketState
from src.nodes import (
    classify,
    retrieve_kb,
    draft_reply,
    review_draft,
    human_review,
    send_reply,
    escalate,
)


MAX_DRAFTS = 3


def route_after_classify(state: TicketState) -> str:
    """Route high-risk tickets directly to escalation."""
    if state.get("category") == "legal":
        return "escalate"

    if (
        state.get("priority") == "urgent"
        and state.get("sentiment") == "negative"
    ):
        return "escalate"

    return "retrieve_kb"


def route_after_review(state: TicketState) -> str:
    if not state.get("review_passed", False):
        if state.get("draft_count", 0) < MAX_DRAFTS:
            return "draft_reply"
        return "escalate"

    if (
        state.get("priority") in ["high", "urgent"]
        or state.get("customer_tier") == "enterprise"
    ):
        return "human_review"

    return "send_reply"


def route_after_human_review(state: TicketState) -> str:
    decision = state.get("human_decision", {})
    action = decision.get("action", "").lower()

    if action in ["approve", "approve_with_edit"]:
        return "send_reply"

    return "escalate"


def build_graph():
    builder = StateGraph(TicketState)

    builder.add_node("classify", classify)
    builder.add_node("retrieve_kb", retrieve_kb)
    builder.add_node("draft_reply", draft_reply)
    builder.add_node("review_draft", review_draft)
    builder.add_node("send_reply", send_reply)
    builder.add_node("escalate", escalate)
    builder.add_node("human_review", human_review)

    builder.add_edge(START, "classify")

    builder.add_conditional_edges(
        "classify",
        route_after_classify,
        {
            "escalate": "escalate",
            "retrieve_kb": "retrieve_kb",
        },
    )

    builder.add_edge("retrieve_kb", "draft_reply")
    builder.add_edge("draft_reply", "review_draft")

    builder.add_conditional_edges(
        "review_draft",
        route_after_review,
        {
            "draft_reply": "draft_reply",
            "escalate": "escalate",
            "human_review": "human_review",
            "send_reply": "send_reply",
        },
    )
    builder.add_conditional_edges(
        "human_review",
        route_after_human_review,
        {
            "send_reply": "send_reply",
            "escalate": "escalate",
        },
    )
    
    builder.add_edge("send_reply", END)
    builder.add_edge("escalate", END)

    return builder.compile(checkpointer=MemorySaver())
    #return builder.compile()
