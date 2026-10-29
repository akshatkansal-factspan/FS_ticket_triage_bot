
from src.llm import get_classifier, get_llm, get_reviewer
from src.retrieval import retrieve_articles
import json
from langgraph.types import interrupt



def classify(state: dict) -> dict:
    """Classify a ticket using Groq and enforce exercise business rules."""
    classifier = get_classifier()

    text = state["ticket_text"].lower()
    tier = state["customer_tier"].lower()

    result = classifier.invoke(
        f"""
        Classify this customer support ticket using these exact rules.

        Ticket ID: {state['ticket_id']}
        Customer tier: {tier}
        Ticket text: {state['ticket_text']}

        Categories:
        - legal: lawyer, GDPR, or lawsuit
        - billing: refund, charged, or invoice
        - account: password, login, or 2FA
        - technical: API, crash, error, down, or outage
        - other: none of the above

        Sentiment:
        - negative: contains strong complaint signals such as
          terrible, unacceptable, angry, or !!!
        - positive: contains thanks or great
        - neutral: otherwise

        Priority:
        - urgent: contains urgent, down, production, or immediately
        - high: negative sentiment or enterprise customer
        - medium: ordinary billing or account question
        - low: otherwise

        Follow these rules exactly. Do not treat every complaint
        about a billing issue as negative without a strong signal.
        Return the required structured output.
        """
    )

    # Enforce the exercise's explicit keyword rules consistently.
    words = text.lower().split()
    if any(word in words for word in ["lawyer", "gdpr", "sue", "lawsuit"]):
        category = "legal"
    elif any(word in words for word in ["refund", "charged", "invoice"]):
        category = "billing"
    elif any(word in words for word in ["password", "login", "2fa"]):
        category = "account"
    elif any(word in words for word in [
        "api", "crash", "error", "down", "outage"
    ]):
        category = "technical"
    else:
        category = result.category

    #print("DEBUG ticket text:", repr(text))
   
    # Priority: use ticket urgency and severity, not customer tier alone.
    if any(word in words for word in [
        "urgent", "down", "production", "immediately",
        "immediate", "outage", "production system"
    ]):
        priority = "urgent"
    elif any(phrase in words for phrase in [
        "terrible", "unacceptable", "angry",
        "very unhappy", "unhappy", "poor experience"
    ]):
        priority = "high"
    elif category in ["billing", "account"]:
        priority = "medium"
    else:
        priority = "low"

    # Sentiment
    if any(phrase in words for phrase in [
        "terrible", "unacceptable", "angry",
        "very unhappy", "unhappy", "frustrated"
    ]):
        sentiment = "negative"
    elif any(phrase in words for phrase in [
        "thanks", "thank you", "great",
        "working perfectly", "looks great"
    ]):
        sentiment = "positive"
    else:
        sentiment = "neutral"


    return {
        "category": category,
        "priority": priority,
        "sentiment": sentiment,
        "audit_log": [
            f"classify: category={category}, "
            f"priority={priority}, sentiment={sentiment}"
        ],
    }


def retrieve_kb(state: dict) -> dict:
    """Retrieve relevant knowledge-base articles."""
    articles = retrieve_articles(
        ticket_text=state["ticket_text"],
        category=state["category"],
        limit=2,
    )

    article_ids = [article["article_id"] for article in articles]

    return {
        "kb_articles": articles,
        "audit_log": [
            f"retrieve_kb: retrieved {len(articles)} articles: {article_ids}"
        ],
    }



def draft_reply(state: dict) -> dict:
    """Generate a grounded draft response for a support ticket."""

    ticket_id = state["ticket_id"]
    ticket_text = state["ticket_text"]
    category = state.get("category", "other")
    sentiment = state.get("sentiment", "neutral")
    articles = state.get("kb_articles", [])
    previous_count = state.get("draft_count", 0)
    critique = state.get("critique", "")

    # Handle positive feedback without requiring a KB article.
    if category == "other" and sentiment == "positive":
        response = (
            f"Hello,\n\n"
            f"Thank you for your feedback! We're glad to hear "
            f"everything is working well.\n\n"
            f"Best regards,\n"
            f"Customer Support\n"
            f"Ticket ID: {ticket_id}"
        )

        return {
            "draft_response": response,
            "draft_count": previous_count + 1,
            "audit_log": [
                "draft_reply: generated positive-feedback acknowledgement"
            ],
        }

    # Do not invent a factual answer when no relevant KB article exists.
    if not articles:
        return {
            "draft_response": "",
            "draft_count": previous_count + 1,
            "audit_log": [
                "draft_reply: no relevant KB articles available"
            ],
        }

    # Build context from the retrieved knowledge-base articles.
    kb_context = "\n\n".join(
        f"Article ID: {article['article_id']}\n"
        f"Title: {article['title']}\n"
        f"Content: {article['content']}"
        for article in articles
    )

    prompt = f"""
You are a professional customer support agent.

Write a concise, polite response to the customer.

Ticket ID: {ticket_id}
Customer message: {ticket_text}
Category: {category}
Sentiment: {sentiment}

Available knowledge-base articles:
{kb_context}

Previous reviewer feedback:
{critique or "No previous feedback."}

Requirements:
1. Include the exact ticket ID: {ticket_id}.
2. Use only facts supported by the provided articles.
3. Cite the most relevant article using [Source: ARTICLE_ID].
4. Do not invent policies, guarantees, refunds, or timelines.
5. Keep the response under 150 words.
6. Address the customer's actual question.
7. Return only the response text.
"""

    response = get_llm().invoke(prompt).content

    # Handle models that return content as a list of text blocks.
    if isinstance(response, list):
        response = "\n".join(
            item.get("text", "")
            for item in response
            if isinstance(item, dict) and item.get("type") == "text"
        )

    response = str(response).strip()

    return {
        "draft_response": response,
        "draft_count": previous_count + 1,
        "audit_log": [
            f"draft_reply: generated draft attempt {previous_count + 1}"
        ],
    }



def review_draft(state: dict) -> dict:
    """Validate the draft and use the LLM reviewer for factual replies."""

    ticket_id = state["ticket_id"]
    draft = state.get("draft_response", "").strip()
    articles = state.get("kb_articles", [])
    category = state.get("category", "other")
    sentiment = state.get("sentiment", "neutral")

    problems = []

    # Basic checks apply to every response.
    if not draft:
        problems.append("Draft is empty.")

    if ticket_id not in draft:
        problems.append(f"Draft must include ticket ID {ticket_id}.")

    if len(draft) > 1200:
        problems.append("Draft exceeds 1200 characters.")

    if len(draft.split()) > 150:
        problems.append("Draft exceeds 150 words.")

    # Positive feedback needs no KB citation when no article was retrieved.
    is_simple_positive_feedback = (
        category == "other"
        and sentiment == "positive"
        and not articles
    )

    if not is_simple_positive_feedback:
        if not articles:
            problems.append("No relevant knowledge-base article was retrieved.")
        elif articles[0]["article_id"] not in draft:
            problems.append(
                f"Draft must cite the top article {articles[0]['article_id']}."
            )

    # Only call the LLM reviewer when basic checks pass and the reply
    # is a factual response based on KB articles.
    if not problems and not is_simple_positive_feedback:
        article_context = "\n\n".join(
            f"{article['article_id']}: {article['title']}\n"
            f"{article['content']}"
            for article in articles
        )

        prompt = f"""
            Review this customer-support reply.

            Ticket ID: {ticket_id}
            Customer message: {state['ticket_text']}
            Draft response:
            {draft}

            Available knowledge-base articles:
            {article_context}

            Check that the reply:
            - Is polite and professional.
            - Is supported by the provided articles.
            - Makes no unsupported promises.
            - Answers the customer's question.

            Return passed=True only if all checks pass.
            Explain any problems in feedback.
            """

        try:
            result = get_reviewer().invoke(prompt)
            if not result.passed:
                problems.append(result.feedback or "LLM review failed.")
        except Exception as exc:
            problems.append(f"LLM review error: {exc}")

    passed = not problems
    critique = "; ".join(problems)

    return {
        "review_passed": passed,
        "critique": critique,
        "audit_log": [
            "review_draft: passed" if passed
            else f"review_draft: failed: {critique}"
        ],
    }


def escalate(state: dict) -> dict:
    """Escalate the ticket with a specific reason."""
    if state.get("category") == "legal":
        reason = "legal ticket"
    elif (
        state.get("priority") == "urgent"
        and state.get("sentiment") == "negative"
    ):
        reason = "urgent and angry customer"
    elif not state.get("review_passed", False):
        reason = "draft review failed after maximum attempts"
    else:
        reason = state.get(
            "escalation_reason",
            "Ticket requires escalation."
        )

    return {
        "outcome": "escalated",
        "escalation_reason": reason,
        "audit_log": [f"escalate: {reason}"],
    }


def send_reply(state: dict) -> dict:
    """Record the final reply. This does not send an actual email."""

    decision = state.get("human_decision", {})
    action = decision.get("action", "").lower()

    # Check whether a human approved the response.
    human_approved = action in ["approve", "approve_with_edit"]

    # Use the human-edited response when provided.
    response = (
        decision.get("edited_response")
        if action == "approve_with_edit"
        else None
    )

    # Fall back to the original draft if no edited response exists.
    response = response or state.get("draft_response", "")

    return {
        "final_response": response,
        "outcome": "human_approved" if human_approved else "auto_replied",
        "audit_log": [
            f"send_reply: reply prepared for ticket {state['ticket_id']}"
        ],
    }


def human_review(state: dict) -> dict:
    """Pause execution and wait for a human reviewer."""
    decision = interrupt({
        "ticket_id": state["ticket_id"],
        "customer_tier": state["customer_tier"],
        "category": state["category"],
        "priority": state["priority"],
        "draft_response": state["draft_response"],
        "message": "Approve, edit and approve, or reject this reply.",
    })

    action = decision.get("action", "").lower()

    if action in ["approve", "approve_with_edit"]:
        response = decision.get(
            "edited_response",
            state["draft_response"],
        )
        return {
            "human_decision": decision,
            "final_response": response,
            "audit_log": [f"human_review: {action}"],
        }

    return {
        "human_decision": decision,
        "escalation_reason": decision.get(
            "reason", "Human reviewer rejected the draft."
        ),
        "audit_log": ["human_review: rejected"],
    }