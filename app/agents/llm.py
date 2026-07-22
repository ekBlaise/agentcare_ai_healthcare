"""
LLM access for the agents.

Wraps Groq (via langchain-groq). Each agent supplies its OWN system prompt.

To keep the whole graph runnable and testable without a network/API key
(e.g. in CI or local dev), an offline "fake" mode is available: set
AGENTCARE_FAKE_LLM=1 or leave GROQ_API_KEY unset. In fake mode, agents fall
back to deterministic heuristics (see each agent). With a real key, the same
agents call the real model.
"""
import os

from app.config import get_settings

settings = get_settings()

_UNSET = {"", "not_set", "your_groq_api_key_here", None}


def llm_available() -> bool:
    """True when a real Groq key is configured and fake mode is off."""
    if os.environ.get("AGENTCARE_FAKE_LLM", "").lower() in ("1", "true", "yes"):
        return False
    return settings.groq_api_key not in _UNSET


def chat(system_prompt: str, user_prompt: str, temperature: float = 0.0) -> str:
    """Single-turn chat with a system + user message. Returns the text reply."""
    if not llm_available():
        raise RuntimeError(
            "LLM not available (offline/fake mode). Agents should guard LLM calls "
            "with llm_available() and provide a deterministic fallback."
        )
    from langchain_groq import ChatGroq
    from langchain_core.messages import SystemMessage, HumanMessage

    model = ChatGroq(
        model=settings.llm_model,
        api_key=settings.groq_api_key,
        temperature=temperature,
        max_retries=2,          # built-in retry (error-handling requirement)
    )
    resp = model.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ])
    return (resp.content or "").strip()
