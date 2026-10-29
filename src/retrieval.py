
import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KB_PATH = PROJECT_ROOT / "documents" / "knowledge_base.json"

STOP_WORDS = {
    "a", "an", "the", "i", "me", "my", "we", "our", "you",
    "your", "is", "are", "was", "were", "be", "been", "being",
    "to", "for", "of", "in", "on", "at", "and", "or", "but",
    "can", "could", "would", "should", "do", "does", "did",
    "it", "this", "that", "from", "with", "as", "after",
    "since", "under", "how", "where", "what", "when",
}

# Map words with similar meanings to a common keyword.
SYNONYMS = {
    "charged": "charge",
    "charges": "charge",
    "charging": "charge",
    "twice": "duplicate",
    "refunds": "refund",
    "refunded": "refund",
    "invoices": "invoice",
    "crashes": "crash",
    "crashing": "crash",
    "errors": "error",
    "keys": "key",
    "passwords": "password",
    "links": "link",
    "exports": "export",
}


def normalize_words(text: str) -> set[str]:
    """Extract meaningful, normalized words from text."""
    words = re.findall(r"[a-z0-9]+", text.lower())

    normalized = set()

    for word in words:
        if word in STOP_WORDS:
            continue

        word = SYNONYMS.get(word, word)
        normalized.add(word)

    return normalized


def load_knowledge_base() -> list[dict]:
    """Load knowledge-base articles from JSON."""
    with KB_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def retrieve_articles(
    ticket_text: str,
    category: str,
    limit: int = 2,
) -> list[dict]:
    """Return the most relevant articles in the specified category."""
    if limit <= 0:
        return []

    ticket_words = normalize_words(ticket_text)
    articles = load_knowledge_base()

    scored_articles = []

    for article in articles:
        # Never retrieve articles from a different category.
        if article["category"] != category:
            continue

        title_words = normalize_words(article["title"])
        content_words = normalize_words(article["content"])

        title_matches = ticket_words & title_words
        content_matches = ticket_words & content_words

        # A title match is a stronger signal than a content match.
        score = (len(title_matches) * 2) + len(content_matches)

        # Ignore articles with no meaningful keyword matches.
        if score > 0:
            scored_articles.append((score, article))

    # Sort by relevance score, highest first.
    scored_articles.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    return [
        article
        for _, article in scored_articles[:limit]
    ]
