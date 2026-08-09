from typing import Dict

import json
import socket
import time
from http.client import RemoteDisconnected
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency
    OpenAI = None

try:
    from anthropic import Anthropic
except ImportError:  # pragma: no cover - optional dependency
    Anthropic = None

_openai_client = None
_anthropic_client = None


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        if OpenAI is None:
            raise RuntimeError("OpenAI provider requested but openai package is not installed.")
        _openai_client = OpenAI()
    return _openai_client


def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        if Anthropic is None:
            raise RuntimeError("Anthropic provider requested but anthropic package is not installed.")
        _anthropic_client = Anthropic()
    return _anthropic_client


def generate_code(prompt: str, model_config: Dict) -> str:
    provider = model_config["provider"]
    model_name = model_config["name"]
    temperature = model_config.get("temperature", 0.2)
    max_tokens = model_config.get("max_tokens", 1200)

    if provider == "openai":
        client = _get_openai_client()
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    if provider == "anthropic":
        client = _get_anthropic_client()
        response = client.messages.create(
            model=model_name,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        chunks = []
        for block in response.content:
            if getattr(block, "type", "") == "text":
                chunks.append(block.text)
        return "\n".join(chunks)

    if provider == "ollama":
        base_url = model_config.get("base_url", "http://localhost:11434")
        endpoint = f"{base_url.rstrip('/')}/api/chat"
        timeout_sec = int(model_config.get("timeout_sec", 180))
        retry_attempts = int(model_config.get("retry_attempts", 6))
        retry_base_delay_sec = float(model_config.get("retry_base_delay_sec", 1.0))
        retry_max_delay_sec = float(model_config.get("retry_max_delay_sec", 20.0))
        payload_body = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        request = Request(
            endpoint,
            data=json.dumps(payload_body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        for attempt in range(retry_attempts):
            try:
                with urlopen(request, timeout=timeout_sec) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                return payload.get("message", {}).get("content", "")
            except HTTPError as error:
                # 4xx errors are generally non-retriable request problems.
                if 400 <= error.code < 500:
                    raise RuntimeError(f"Ollama HTTP error: {error.code}") from error
                if attempt == retry_attempts - 1:
                    raise RuntimeError(f"Ollama HTTP error: {error.code}") from error
            except (URLError, TimeoutError, socket.timeout, RemoteDisconnected) as error:
                if attempt == retry_attempts - 1:
                    raise RuntimeError(f"Ollama connection error: {error}") from error
            delay = min(retry_max_delay_sec, retry_base_delay_sec * (2 ** attempt))
            jitter = delay * 0.2
            sleep_for = max(0.0, delay + ((time.time() % 1) * 2 - 1) * jitter)
            time.sleep(sleep_for)
        raise RuntimeError("Ollama request failed after retries.")

    raise ValueError(f"Unsupported provider: {provider}")