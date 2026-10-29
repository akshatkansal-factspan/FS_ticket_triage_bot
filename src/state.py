
from typing import Annotated, TypedDict
import operator


class TicketState(TypedDict, total=False):
    # Input
    ticket_id: str
    customer_tier: str
    ticket_text: str

    # Classification
    category: str
    priority: str
    sentiment: str

    # Knowledge-base retrieval
    kb_articles: list[dict]

    # Draft and review loop
    draft_response: str
    draft_count: int
    critique: str
    review_passed: bool

    # Human review
    human_decision: dict

    # Final outcome
    final_response: str
    outcome: str
    escalation_reason: str

    # Audit log: each node appends its own entries
    audit_log: Annotated[list[str], operator.add]
