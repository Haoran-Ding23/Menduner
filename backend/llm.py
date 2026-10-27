"""LLM 客户端（后端专用）。

安全约束（不可妥协）：
* key 只从环境变量读，绝不写进代码、日志或响应；
* 超时与错误一律向上抛，由调用方决定"不可用"，不允许静默降级成编造内容；
* 不打印 prompt 原文（可能含业务数据）。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class LLMError(RuntimeError):
    """调用失败；调用方必须把它展示为"暂不可用"，不能编内容。"""


def configured() -> bool:
    return bool(os.environ.get("LLM_API_KEY"))


def _endpoint() -> str:
    base = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
    return base + "/chat/completions"


def chat(messages: list[dict], *, temperature: float = 0.2, max_tokens: int = 1200,
         timeout: int = 60) -> str:
    key = os.environ.get("LLM_API_KEY")
    if not key:
        raise LLMError("未配置 LLM_API_KEY")
    model = os.environ.get("LLM_MODEL", "deepseek-chat")
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }).encode()
    request = urllib.request.Request(
        _endpoint(), data=payload, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        raise LLMError(f"模型返回 HTTP {error.code}") from error
    except Exception as error:  # 网络/超时/解析
        raise LLMError("模型调用失败") from error
    try:
        return body["choices"][0]["message"]["content"]
    except Exception as error:
        raise LLMError("模型返回结构异常") from error


def chat_json(messages: list[dict], **kwargs) -> dict:
    text = chat(messages, **kwargs)
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        # 允许模型包一层 ```json ``` 代码块
        stripped = text.strip()
        if stripped.startswith("```"):
            inner = stripped.split("```", 2)[1]
            inner = inner.split("\n", 1)[1] if "\n" in inner else inner
            try:
                return json.loads(inner)
            except json.JSONDecodeError:
                pass
        raise LLMError("模型未返回合法 JSON") from error
