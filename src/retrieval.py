
import re

from src.config import get_knowledge_base


def _tokens(text):
    return {
        token
        for token in re.findall(
            r"[a-z0-9]+",
            (text or "").lower()
        )
        if len(token) > 2
    }


def retrieve_articles(ticket_text, category, limit=2):
    query_tokens = _tokens(ticket_text)

    articles = [
        article
        for article in get_knowledge_base()
        if article.get("category") == category
    ]

    scored = []

    for article in articles:
        content_tokens = _tokens(
            article.get("title", "")
            + " "
            + article.get("content", "")
        )

        score = len(query_tokens & content_tokens)

        scored.append((score, article))

    scored.sort(
        key=lambda item: (
            item[0],
            item[1].get("article_id", "")
        ),
        reverse=True
    )

    # Return only articles that have actual keyword overlap.
    # Do not fall back to unrelated articles.
    matches = [
        article
        for score, article in scored
        if score > 0
    ]

    return matches[:limit]
