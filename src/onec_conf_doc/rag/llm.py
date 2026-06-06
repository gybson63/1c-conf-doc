"""LLM providers for RAG query endpoint."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from onec_conf_doc.config import LLMConfig


@runtime_checkable
class LLMProvider(Protocol):
    def generate(self, prompt: str) -> str: ...


class NoLLMProvider:
    def generate(self, prompt: str) -> str:
        return "LLM provider is disabled. Enable llm.provider in config.yaml."


class OpenAILLMProvider:
    def __init__(self, config: LLMConfig) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            msg = "Install openai: pip install '1c-conf-doc[openai]'"
            raise ImportError(msg) from exc

        import os

        api_key = config.openai_api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            msg = "OpenAI API key is required"
            raise ValueError(msg)
        self._client = OpenAI(api_key=api_key)
        self._model = config.model

    def generate(self, prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content or ""


class OllamaLLMProvider:
    def __init__(self, config: LLMConfig) -> None:
        import httpx

        self._base_url = config.ollama_base_url.rstrip("/")
        self._model = config.model
        self._client = httpx.Client(timeout=120.0)

    def generate(self, prompt: str) -> str:
        response = self._client.post(
            f"{self._base_url}/api/generate",
            json={"model": self._model, "prompt": prompt, "stream": False},
        )
        response.raise_for_status()
        data = response.json()
        return str(data.get("response", ""))


def create_llm_provider(config: LLMConfig) -> LLMProvider:
    if config.provider == "openai":
        return OpenAILLMProvider(config)
    if config.provider == "ollama":
        return OllamaLLMProvider(config)
    return NoLLMProvider()
