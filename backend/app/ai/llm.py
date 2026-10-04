"""Talking to the AI model.

This is the only place that knows how the model is reached. It speaks the
widely used "OpenAI-compatible" chat format, which is understood by Ollama
(open models running on this computer, the default) and by most hosted
services, so the model can be changed in .env without changing code.

Nothing here knows about sources or summaries: it sends a question and
returns the model's answer as data.
"""

import json
import logging
import os
import re
import time

import requests

logger = logging.getLogger(__name__)

# LLM_V1

# Reasons reported together with FAILED.
AI_UNAVAILABLE = "AI_UNAVAILABLE"        # nothing answers at AI_BASE_URL
AI_MODEL_MISSING = "AI_MODEL_MISSING"    # the service does not have AI_MODEL
AI_FAILED = "AI_FAILED"                  # the service answered with an error
AI_BAD_ANSWER = "AI_BAD_ANSWER"          # the answer was not usable data


class LLMError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def base_url() -> str:
    return (os.getenv("AI_BASE_URL") or "http://127.0.0.1:11434/v1").rstrip("/")


def model_name() -> str:
    # Three open models were run through the app on a Persian study text.
    # All gave usable summaries. gemma3:4b is the default because it is
    # about three times faster than gemma3:12b on an ordinary processor and
    # needs far less memory; gemma3:12b writes a little more carefully.
    return os.getenv("AI_MODEL") or "gemma3:4b"


def _timeout() -> float:
    # Open models on an ordinary processor can take minutes per answer.
    return float(os.getenv("AI_TIMEOUT_SECONDS") or 600)


def _max_output_tokens() -> int:
    # Bounds how long one answer can get, so that a model that starts
    # repeating itself cannot run on.
    return int(os.getenv("AI_MAX_OUTPUT_TOKENS") or 2000)


# An answer larger than this is not a summary of a few thousand characters.
MAX_ANSWER_CHARS = 60_000


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = (os.getenv("AI_API_KEY") or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


_reachable_cache: dict[str, float | bool] = {"at": 0.0, "value": False}
REACHABLE_CACHE_SECONDS = 15


def is_reachable() -> bool:
    """Whether the AI service answers properly at AI_BASE_URL.

    The answer is remembered for a few seconds, so that asking often does
    not mean calling the service often.
    """
    now = time.monotonic()
    if now - float(_reachable_cache["at"]) < REACHABLE_CACHE_SECONDS:
        return bool(_reachable_cache["value"])

    try:
        response = requests.get(
            f"{base_url()}/models", headers=_headers(), timeout=3
        )
        value = response.status_code == 200
    except requests.RequestException:
        value = False

    _reachable_cache.update(at=now, value=value)
    return value


_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")


def parse_json_answer(text: str) -> dict:
    """Read the JSON object in a model's answer.

    Models sometimes wrap the object in a code fence or add a sentence
    around it; the object itself is what counts.
    """
    if not isinstance(text, str) or len(text) > MAX_ANSWER_CHARS:
        raise LLMError(AI_BAD_ANSWER)

    text = _FENCE.sub("", text).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise LLMError(AI_BAD_ANSWER)

    try:
        data = json.loads(text[start:end + 1])
    except (ValueError, RecursionError):
        raise LLMError(AI_BAD_ANSWER)

    if not isinstance(data, dict):
        raise LLMError(AI_BAD_ANSWER)

    return data


def _post(body: dict) -> requests.Response:
    try:
        return requests.post(
            f"{base_url()}/chat/completions",
            headers=_headers(),
            json=body,
            timeout=_timeout(),
        )
    except requests.ConnectionError:
        raise LLMError(AI_UNAVAILABLE)
    except requests.RequestException:
        raise LLMError(AI_FAILED)


def chat_json(system: str, user: str) -> dict:
    """Ask the model and return its answer as a JSON object.

    Raises LLMError when the model cannot be reached, fails, or does not
    answer with usable data.
    """
    body = {
        "model": model_name(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "max_tokens": _max_output_tokens(),
        # Asks the service to return nothing but a JSON object.
        "response_format": {"type": "json_object"},
    }

    response = _post(body)

    if response.status_code == 400:
        # A service that does not know "response_format": ask without it.
        body.pop("response_format")
        response = _post(body)

    if response.status_code == 404:
        raise LLMError(AI_MODEL_MISSING)

    if response.status_code != 200:
        logger.error(
            "The AI service answered %s: %s",
            response.status_code, response.text[:500],
        )
        raise LLMError(AI_FAILED)

    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError, RecursionError):
        raise LLMError(AI_BAD_ANSWER)

    if isinstance(content, list):
        # Some services give the answer as a list of text pieces.
        content = "".join(
            piece.get("text", "") for piece in content
            if isinstance(piece, dict) and isinstance(piece.get("text"), str)
        )

    return parse_json_answer(content)
