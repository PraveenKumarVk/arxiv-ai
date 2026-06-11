from functools import lru_cache
from typing import Union

from src.config import get_settings
from src.services.ollama.client import OllamaClient
from src.services.ollama.groq_client import GroqClient

LLMClient = Union[OllamaClient, GroqClient]


@lru_cache(maxsize=1)
def make_ollama_client() -> LLMClient:
    """Return an OllamaClient or GroqClient depending on LLM_PROVIDER env var.

    Set LLM_PROVIDER=groq and GROQ_API_KEY=<key> to use Groq (cloud).
    Defaults to Ollama (local) when LLM_PROVIDER is unset or "ollama".
    """
    settings = get_settings()
    if settings.llm_provider.lower() == "groq":
        return GroqClient(settings)
    return OllamaClient(settings)
