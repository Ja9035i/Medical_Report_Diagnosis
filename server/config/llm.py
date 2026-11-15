import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

# Switch provider in .env:  LLM_PROVIDER=groq  or  LLM_PROVIDER=gemini
# Model names change over time; check the Groq console / Google AI Studio for current ones.
DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-120b",  # Llama 3.x models were removed from Groq; list current ones via /openai/v1/models
    "gemini": "gemini-3.6-flash",  # newer 3.7/3.8 were overloaded (503 / hanging) on the free tier
}


def _provider() -> str:
    provider = os.getenv("LLM_PROVIDER", "groq").strip().lower()
    if provider not in DEFAULT_MODELS:
        raise ValueError(f"LLM_PROVIDER must be one of {list(DEFAULT_MODELS)}, got '{provider}'")
    return provider


def _model(provider: str) -> str:
    return os.getenv(f"{provider.upper()}_MODEL", DEFAULT_MODELS[provider])


def get_model_label() -> str:
    """e.g. 'groq:llama-3.3-70b-versatile' — stored with each answer so models can be compared."""
    provider = _provider()
    return f"{provider}:{_model(provider)}"


@lru_cache(maxsize=1)
def get_llm():
    """Create the chat model once. Both are LangChain chat models, so `prompt | llm` works the same."""
    provider = _provider()
    model = _model(provider)

    # An overloaded model can hang; every call is bounded so a diagnosis fails cleanly instead
    timeout = float(os.getenv("LLM_TIMEOUT", "60"))

    if provider == "groq":
        from langchain_groq import ChatGroq
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("LLM_PROVIDER=groq but GROQ_API_KEY is not set in .env")
        return ChatGroq(temperature=0, model_name=model, groq_api_key=api_key,
                        timeout=timeout, max_retries=2)

    # gemini
    from langchain_google_genai import ChatGoogleGenerativeAI
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("LLM_PROVIDER=gemini but GOOGLE_API_KEY is not set in .env")
    return ChatGoogleGenerativeAI(model=model, temperature=0, google_api_key=api_key,
                                  timeout=timeout, max_retries=2)


def message_text(message) -> str:
    """
    Plain text of a chat model reply. Groq returns a string; Gemini 3 models return a
    list of parts like [{"type": "text", "text": "..."}, ...]. Always return a string.
    """
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type", "text") == "text":
                parts.append(part.get("text", ""))
        return "".join(parts)
    return str(content)
