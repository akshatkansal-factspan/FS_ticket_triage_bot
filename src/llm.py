
import os
from typing import Literal

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field


load_dotenv()


class Classification(BaseModel):
    category: Literal[
        "billing", "technical", "account", "legal", "other"
    ]
    priority: Literal["low", "medium", "high", "urgent"]
    sentiment: Literal["negative", "neutral", "positive"]


class ReviewResult(BaseModel):
    passed: bool
    feedback: str = Field(
        description="Explain any problems the draft must fix."
    )


def get_llm() -> ChatGroq:
    """Create the configured Groq chat model."""
    api_key = os.getenv("GROQ_API_KEY")
    model_name = os.getenv(
        "GROQ_MODEL",
        "llama-3.3-70b-versatile",
    )

    if not api_key:
        raise ValueError(
            "GROQ_API_KEY is missing. Check your .env file."
        )

    return ChatGroq(
        model=model_name,
        api_key=api_key,
        temperature=0,
    )


def get_classifier():
    """Return a Groq model that produces Classification objects."""
    return get_llm().with_structured_output(Classification)


def get_reviewer():
    """Return a Groq model that produces ReviewResult objects."""
    return get_llm().with_structured_output(ReviewResult)
