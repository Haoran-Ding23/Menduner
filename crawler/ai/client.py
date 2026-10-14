"""DeepSeek client for evidence enrichment.

The API key is read from ``DEEPSEEK_API_KEY`` and never logged, never returned, and never
shipped to the frontend.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

API_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"
ENV_FILE = Path(__file__).resolve().parent.parent / "frontend" / ".env.local"


class DeepSeekError(RuntimeError):
    """A call failed in a way the caller must see, not swallow."""


def load_api_key() -> str | None:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key.strip()
    # Local development convenience; the server sets the environment variable instead.
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    failures: int = 0
    last_error: str | None = None

    def add(self, payload: dict) -> None:
        self.calls += 1
        self.prompt_tokens += int(payload.get("prompt_tokens") or 0)
        self.completion_tokens += int(payload.get("completion_tokens") or 0)

    def as_dict(self) -> dict:
        return {
            "calls": self.calls,
            "failures": self.failures,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
            "last_error": self.last_error,
        }


@dataclass
class DeepSeek:
    """Minimal chat client. Retries transient failures and never retries a 4xx."""

    api_key: str
    model: str = DEFAULT_MODEL
    timeout: float = 120.0
    attempts: int = 3
    usage: Usage = field(default_factory=Usage)

    def __post_init__(self) -> None:
        self._client = httpx.Client(
            base_url=API_BASE,
            timeout=self.timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "DeepSeek":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 2000,
        json_object: bool = True,
    ) -> str:
        body: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # Extraction must be repeatable: the same page has to yield the same fields, so
            # sampling is off rather than merely low.
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_object:
            body["response_format"] = {"type": "json_object"}

        delay = 2.0
        for attempt in range(1, self.attempts + 1):
            try:
                response = self._client.post("/chat/completions", json=body)
            except httpx.HTTPError as exc:
                self.usage.failures += 1
                self.usage.last_error = f"{type(exc).__name__}: {exc}"
                if attempt == self.attempts:
                    raise DeepSeekError(self.usage.last_error) from exc
                time.sleep(delay)
                delay *= 2
                continue

            if response.status_code == 200:
                document = response.json()
                self.usage.add(document.get("usage") or {})
                try:
                    return document["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as exc:
                    self.usage.failures += 1
                    self.usage.last_error = "malformed response envelope"
                    raise DeepSeekError("DeepSeek returned an unexpected envelope") from exc

            # 4xx is a configuration or quota problem: retrying cannot fix it.
            detail = response.text[:300]
            self.usage.failures += 1
            self.usage.last_error = f"HTTP {response.status_code}: {detail}"
            if response.status_code in (401, 402, 403, 404, 422):
                raise DeepSeekError(
                    f"DeepSeek rejected the request ({response.status_code}): {detail}"
                )
            if attempt == self.attempts:
                raise DeepSeekError(self.usage.last_error)
            time.sleep(delay)
            delay *= 2
        raise DeepSeekError(self.usage.last_error or "DeepSeek call failed")

    def complete_json(self, **kwargs) -> dict:
        """``complete`` in JSON-object mode.

        Two failure modes seen in practice on real Chinese government pages:
          * the response is truncated mid-object when the model runs long (``finish_reason ==
            "length"``), which yields invalid JSON;
          * the model wraps the object in a markdown fence.
        Both are repaired where possible instead of thrown away, because the reading is still
        usable and a retry costs tokens.
        """
        raw = self.complete(**kwargs)
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
            text = re.sub(r"\s*```$", "", text).strip()
        try:
            return json.loads(text)
        except ValueError:
            pass
        # Salvage a truncated object by closing whatever brackets are still open. A value cut
        # off mid-string is dropped rather than guessed at, so the recovered object can carry
        # fewer fields but never an invented one.
        start = text.find("{")
        if start >= 0:
            body = text[start:]
            stack: list[str] = []
            in_string = False
            escaped = False
            for character in body:
                if in_string:
                    if escaped:
                        escaped = False
                    elif character == "\\":
                        escaped = True
                    elif character == '"':
                        in_string = False
                    continue
                if character == '"':
                    in_string = True
                elif character in "{[":
                    stack.append("}" if character == "{" else "]")
                elif character in "}]" and stack:
                    stack.pop()
            if in_string:
                cut = body.rfind(",")
                body = body[:cut] if cut > 0 else body
            body = body.rstrip().rstrip(",")
            try:
                return json.loads(body + "".join(reversed(stack)))
            except ValueError:
                pass
        raise DeepSeekError(f"DeepSeek did not return usable JSON: {raw[:200]!r}")
