"""Small real requests using the local credential vault; never prints credentials,
prompt text, response text, account data or reasoning. Run explicitly for diagnosis.
"""
import asyncio
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
from assistant_app.settings import ConfigStore, Credentials
from assistant_app.prompts import assemble

async def measure(client, provider, key, messages, label):
    payload = {"model": provider["model"], "messages": messages, "stream": True, "temperature": provider["temperature"], "max_tokens": min(provider["max_tokens"], 256), **provider.get("extra", {})}
    start = time.monotonic()
    result = {"label": label, "model": provider["model"], "input_chars": sum(len(m["content"]) for m in messages), "diagnostic_max_tokens": payload["max_tokens"], "reasoning_chars": 0, "answer_chars": 0}
    try:
        async with client.stream("POST", provider["base_url"].rstrip("/") + "/chat/completions", headers={"Authorization": "Bearer " + key}, json=payload) as response:
            result["status"] = response.status_code
            result["headers_seconds"] = round(time.monotonic() - start, 3)
            if response.status_code != 200:
                return result
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                value = line[5:].strip()
                if value == "[DONE]": break
                chunk = json.loads(value)
                result.setdefault("first_event_seconds", round(time.monotonic() - start, 3))
                choices = chunk.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    reasoning = delta.get("reasoning_content") or ""
                    text = delta.get("content") or ""
                    if reasoning:
                        result.setdefault("first_reasoning_seconds", round(time.monotonic() - start, 3))
                        result["reasoning_chars"] += len(reasoning)
                    if text:
                        result.setdefault("first_answer_seconds", round(time.monotonic() - start, 3))
                        result["answer_chars"] += len(text)
                    if choices[0].get("finish_reason"):
                        result["finish_reason"] = choices[0]["finish_reason"]
            result["total_seconds"] = round(time.monotonic() - start, 3)
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        result["total_seconds"] = round(time.monotonic() - start, 3)
    return result

async def main():
    c = ConfigStore().load()
    provider = next(p for p in c["providers"] if p["id"] == c["default_provider"])
    if urlsplit(provider["base_url"]).hostname != "api.deepseek.com":
        raise SystemExit("This diagnosis is limited to the configured official DeepSeek endpoint")
    key = Credentials().get(provider["id"])
    if not key: raise SystemExit("No local credential configured")
    template = next(t for t in c["templates"] if t["id"] == c["template"])
    background = next(b["text"] for b in c["backgrounds"] if b["id"] == c["background_id"]) if c["use_background"] else ""
    messages = assemble(template, "请只用两句话解释闭环控制的基本原理。", [], background, c["context_chars"])
    results = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=8), trust_env=False, follow_redirects=False) as client:
        results.append(await measure(client, provider, key, messages, "baseline-cold-connection"))
        print(json.dumps(results[-1], ensure_ascii=True), flush=True)
        if "--compare" in sys.argv:
            provider = dict(provider)
            provider["extra"] = {**provider.get("extra", {}), "thinking": {"type": "disabled"}}
            provider["extra"].pop("reasoning_effort", None)
            for label in ("non-thinking-reused-connection", "non-thinking-reused-connection-repeat"):
                results.append(await measure(client, provider, key, messages, label))
                print(json.dumps(results[-1], ensure_ascii=True), flush=True)
    path = ROOT / "docs" / "verification" / "deepseek_latency.json"
    path.write_text(json.dumps({"real_api": True, "notes": "Small 256-token diagnostic, not full-session reproduction; no content or credentials saved. Provider variance and connection reuse affect results.", "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")

if __name__ == "__main__":
    asyncio.run(main())
