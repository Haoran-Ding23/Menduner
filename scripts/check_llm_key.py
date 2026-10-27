"""验证服务器上的 LLM Key：列出模型 + 跑一次最小对话。不打印 key。"""
import json
import os
import urllib.request

key = os.environ.get("LLM_API_KEY", "")
base = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
if not key:
    raise SystemExit("  未读到 LLM_API_KEY")


def call(path: str, payload=None):
    data = json.dumps(payload).encode() if payload else None
    request = urllib.request.Request(
        base + path, data=data, method="POST" if data else "GET",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode())


models = call("/models")
print("  可用模型:", [item["id"] for item in models.get("data", [])])

for candidate in ("deepseek-chat", "deepseek-flash"):
    try:
        result = call("/chat/completions", {
            "model": candidate,
            "messages": [{"role": "user", "content": "只回两个字：可用"}],
            "max_tokens": 16,
        })
        text = result["choices"][0]["message"]["content"].strip()
        print(f"  {candidate} 对话返回: {text!r} | 用量: {result.get('usage')}")
        break
    except Exception as error:
        print(f"  {candidate} 失败: {error}")
