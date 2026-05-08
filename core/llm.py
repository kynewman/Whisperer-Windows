"""LLM provider registry for optional dictation post-processing."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from core.providers import LLMProvider


log = logging.getLogger("whisperer.llm")

BUILTIN_PROMPT_TEMPLATES: dict[str, str] = {
    "email": "Rewrite the following dictated text as a polished professional email body. Preserve the meaning exactly. Output only the rewritten text.\n\n{text}",
    "note": "Clean up the following dictated text into clear, well-punctuated prose. Output only the cleaned text.\n\n{text}",
    "coding": "Reformat the following dictated text as a code comment or docstring. Output only the result.\n\n{text}",
    "meeting": "Rewrite the following dictated notes as structured meeting notes with bullet points. Output only the result.\n\n{text}",
    "message": "Clean up the following dictated message for sending in a chat app. Keep it conversational and concise. Output only the cleaned text.\n\n{text}",
    "plain": "{text}",
}


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout_s: int) -> dict[str, Any]:
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


class LocalOllamaProvider:
    def __init__(self, model: str, base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url.rstrip("/")

    def complete(self, prompt: str, timeout_s: int = 10) -> str:
        result = _post_json(f"{self.base_url}/api/generate", {"model": self.model, "prompt": prompt, "stream": False}, {}, timeout_s)
        return result.get("response", "")


class LocalOpenAICompatProvider:
    def __init__(self, model: str, base_url: str, api_key: str | None = None):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def complete(self, prompt: str, timeout_s: int = 10) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant that rewrites dictated text."},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
        result = _post_json(f"{self.base_url}/v1/chat/completions", payload, headers, timeout_s)
        return result["choices"][0]["message"]["content"]


class OpenAIProvider:
    def __init__(self, model: str = "gpt-4o-mini", api_key: str = ""):
        self.model = model
        self.api_key = api_key

    def complete(self, prompt: str, timeout_s: int = 10) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant that rewrites dictated text."},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
        result = _post_json("https://api.openai.com/v1/chat/completions", payload, {"Authorization": f"Bearer {self.api_key}"}, timeout_s)
        return result["choices"][0]["message"]["content"]


class AnthropicProvider:
    def __init__(self, model: str = "claude-3-haiku-20240307", api_key: str = ""):
        self.model = model
        self.api_key = api_key

    def complete(self, prompt: str, timeout_s: int = 10) -> str:
        payload = {"model": self.model, "max_tokens": 1024, "messages": [{"role": "user", "content": prompt}]}
        result = _post_json(
            "https://api.anthropic.com/v1/messages",
            payload,
            {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            timeout_s,
        )
        return result["content"][0]["text"]


class GroqProvider:
    def __init__(self, model: str = "llama3-8b-8192", api_key: str = ""):
        self.model = model
        self.api_key = api_key

    def complete(self, prompt: str, timeout_s: int = 10) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant that rewrites dictated text."},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
        result = _post_json("https://api.groq.com/openai/v1/chat/completions", payload, {"Authorization": f"Bearer {self.api_key}"}, timeout_s)
        return result["choices"][0]["message"]["content"]


def get_provider(provider_name: str, model: str, base_url: str = "", api_key: str | None = None) -> LLMProvider:
    if provider_name == "ollama":
        return LocalOllamaProvider(model, base_url=base_url or "http://localhost:11434")
    if provider_name in {"openai_compat", "openai-compatible"}:
        return LocalOpenAICompatProvider(model, base_url=base_url or "http://localhost:8000", api_key=api_key)
    if provider_name == "openai":
        return OpenAIProvider(model=model or "gpt-4o-mini", api_key=api_key or "")
    if provider_name == "anthropic":
        return AnthropicProvider(model=model or "claude-3-haiku-20240307", api_key=api_key or "")
    if provider_name == "groq":
        return GroqProvider(model=model or "llama3-8b-8192", api_key=api_key or "")
    raise ValueError(f"Unknown LLM provider: {provider_name}")


def process(
    text: str,
    prompt_template: str = "{text}",
    provider_name: str = "ollama",
    model: str = "llama3.1",
    timeout_s: int = 10,
    base_url: str = "",
    api_key: str | None = None,
) -> str:
    if not text.strip():
        return text
    if not prompt_template.strip():
        prompt_template = "{text}"
    if "{text}" not in prompt_template:
        prompt_template = prompt_template + "\n\n{text}"
    prompt = prompt_template.format(text=text)

    try:
        provider = get_provider(provider_name, model, base_url=base_url, api_key=api_key)
        result = provider.complete(prompt, timeout_s=timeout_s)
        return result.strip() if result.strip() else text
    except urllib.error.URLError as exc:
        log.warning("LLM connection failed (%s): %s", provider_name, exc)
    except Exception as exc:
        log.warning("LLM processing failed (%s): %s", provider_name, exc)
    return text
