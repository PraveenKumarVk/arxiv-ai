import json
import logging
from typing import Any, AsyncIterator, Dict, List

import httpx
from src.config import Settings
from src.exceptions import LLMException
from src.services.ollama.prompts import RAGPromptBuilder

logger = logging.getLogger(__name__)

# Maps Ollama model names to their closest Groq equivalent
_MODEL_MAP = {
    "llama3.2:1b": "llama-3.1-8b-instant",
    "llama3.2:3b": "llama-3.1-8b-instant",
    "llama3.1:8b": "llama-3.1-8b-instant",
    "llama3.2": "llama-3.1-8b-instant",
    "qwen2.5:7b": "llama-3.3-70b-versatile",
}
_DEFAULT_GROQ_MODEL = "llama-3.1-8b-instant"


def _resolve_model(model: str) -> str:
    return _MODEL_MAP.get(model, _DEFAULT_GROQ_MODEL)


class GroqClient:
    """Drop-in replacement for OllamaClient that calls the Groq cloud API.

    Exposes the same public methods so the rest of the codebase needs no changes.
    """

    def __init__(self, settings: Settings):
        self.api_key = settings.groq_api_key
        self.base_url = "https://api.groq.com/openai/v1"
        self.timeout = httpx.Timeout(float(settings.ollama_timeout))
        self.prompt_builder = RAGPromptBuilder()

    # ------------------------------------------------------------------
    # Health / introspection
    # ------------------------------------------------------------------

    async def health_check(self) -> Dict[str, Any]:
        """Ping the Groq models endpoint to verify the API key is valid."""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                response = await client.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                if response.status_code == 200:
                    return {"status": "healthy", "message": "Groq API reachable", "version": "cloud"}
                return {"status": "unhealthy", "message": f"Groq returned {response.status_code}"}
        except Exception as e:
            return {"status": "unhealthy", "message": str(e)}

    # ------------------------------------------------------------------
    # Core generation (OpenAI-compatible chat completions)
    # ------------------------------------------------------------------

    async def _chat(self, model: str, prompt: str, stream: bool = False) -> httpx.Response:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "stream": stream,
        }
        client = httpx.AsyncClient(timeout=self.timeout)
        if stream:
            return client, await client.send(
                client.build_request(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                ),
                stream=True,
            )
        async with client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
            return response

    # ------------------------------------------------------------------
    # RAG interface (mirrors OllamaClient exactly)
    # ------------------------------------------------------------------

    async def generate_rag_answer(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        model: str = "llama3.2:1b",
        use_structured_output: bool = False,
    ) -> Dict[str, Any]:
        groq_model = _resolve_model(model)
        prompt = self.prompt_builder.create_rag_prompt(query, chunks)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json={
                        "model": groq_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.7,
                    },
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                response.raise_for_status()
                answer = response.json()["choices"][0]["message"]["content"]

            sources = []
            seen: set = set()
            for chunk in chunks:
                arxiv_id = chunk.get("arxiv_id", "")
                if arxiv_id:
                    clean = arxiv_id.split("v")[0] if "v" in arxiv_id else arxiv_id
                    url = f"https://arxiv.org/pdf/{clean}.pdf"
                    if url not in seen:
                        sources.append(url)
                        seen.add(url)

            return {
                "answer": answer,
                "sources": sources,
                "confidence": "medium",
                "citations": list({c.get("arxiv_id") for c in chunks if c.get("arxiv_id")})[:5],
            }

        except Exception as e:
            logger.error(f"Groq generation error: {e}")
            raise LLMException(f"Groq failed to generate answer: {e}")

    async def generate_rag_answer_stream(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        model: str = "llama3.2:1b",
    ) -> AsyncIterator[Dict[str, Any]]:
        groq_model = _resolve_model(model)
        prompt = self.prompt_builder.create_rag_prompt(query, chunks)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    json={
                        "model": groq_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.7,
                        "stream": True,
                    },
                    headers={"Authorization": f"Bearer {self.api_key}"},
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data.strip() == "[DONE]":
                            yield {"response": "", "done": True}
                            return
                        try:
                            chunk_data = json.loads(data)
                            delta = chunk_data["choices"][0]["delta"].get("content", "")
                            if delta:
                                yield {"response": delta, "done": False}
                        except Exception:
                            continue

        except Exception as e:
            logger.error(f"Groq streaming error: {e}")
            raise LLMException(f"Groq streaming failed: {e}")
