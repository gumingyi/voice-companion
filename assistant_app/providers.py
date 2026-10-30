"""Adapter boundary: only OpenAI Chat Completions wire protocol is implemented."""
import asyncio
import json
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
import httpx

class ProviderError(Exception):
    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable

class OpenAICompatible:
    def __init__(self, config, key, transport=None, shared_client=None):
        self.config, self.key, self.transport = config, key, transport
        self.shared_client = shared_client

    def timeout(self):
        seconds = float(self.config["timeout"])
        return httpx.Timeout(seconds, connect=min(seconds, 8), pool=min(seconds, 8))

    @asynccontextmanager
    async def _client_scope(self):
        if self.shared_client is not None:
            yield self.shared_client
        else:
            async with httpx.AsyncClient(timeout=self.timeout(), transport=self.transport, follow_redirects=False, trust_env=False) as client:
                yield client

    def client(self):
        return self._client_scope()

    def payload(self, messages):
        p = self.config
        extra = dict(p.get("extra", {}))
        # Only the official endpoint is known to understand this parameter.
        if p.get("fast_mode", False) and urlsplit(p["base_url"]).hostname == "api.deepseek.com":
            extra["thinking"] = {"type": "disabled"}
            extra.pop("reasoning_effort", None)
        return {"temperature": p["temperature"], "max_tokens": p["max_tokens"], **extra,
                "model": p["model"], "messages": messages, "stream": True}

    async def stream(self, messages):
        if not self.key:
            raise ProviderError("未配置 API Key，请在设置中保存到 Windows 凭据管理器")
        p = self.config
        payload = self.payload(messages)
        started = time.monotonic()
        for attempt in range(p["retries"] + 1):
            received = False
            accepted = False
            first_event = False
            first_text = False
            reasoning_seen = False
            try:
                yield {"phase": "request", "attempt": attempt + 1}
                async with self.client() as client:
                    async with client.stream("POST", p["base_url"].rstrip("/") + "/chat/completions", headers={"Authorization": "Bearer " + self.key}, json=payload, timeout=self.timeout()) as response:
                        code = response.status_code
                        if code != 200:
                            # Never surface untrusted response bodies (may echo credentials/prompts).
                            detail = {401: "API Key 无效", 403: "无访问权限", 404: "地址或模型不存在", 429: "限流或额度不足"}.get(code, "模型接口请求失败")
                            raise ProviderError(f"HTTP {code}：{detail}", code == 429 or code >= 500)
                        accepted = True
                        yield {"phase": "waiting_text", "timings": {"headers": round(time.monotonic() - started, 3)}}
                        done = False
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            value = line[5:].strip()
                            if value == "[DONE]":
                                done = True
                                break
                            try:
                                chunk = json.loads(value)
                                if not first_event:
                                    first_event = True
                                    yield {"timings": {"first_event": round(time.monotonic() - started, 3)}}
                                if chunk.get("error"):
                                    raise ProviderError("模型返回流式错误")
                                choices = chunk.get("choices", [])
                                delta = choices[0].get("delta", {}) if choices else {}
                                content = delta.get("content") or ""
                                if delta.get("reasoning_content") and not reasoning_seen:
                                    reasoning_seen = True
                                    yield {"phase": "reasoning"}
                                if content:
                                    received = True
                                    event = {"text": content, "elapsed": time.monotonic() - started, "phase": "streaming"}
                                    if not first_text:
                                        first_text = True
                                        event["timings"] = {"first_token": round(time.monotonic() - started, 3)}
                                    yield event
                                if chunk.get("usage"):
                                    usage = {k: v for k, v in chunk["usage"].items() if k in ("prompt_tokens", "completion_tokens", "total_tokens") and isinstance(v, (int, float))}
                                    yield {"usage": usage}
                                if choices and choices[0].get("finish_reason"):
                                    done = True
                            except (ValueError, TypeError, KeyError, IndexError):
                                raise ProviderError("模型返回了无效 SSE 数据") from None
                        if not done:
                            raise ProviderError("流式连接意外中断，请重试", not received)
                        if not received:
                            raise ProviderError("模型未返回正文；请检查模型思考参数或增大输出预算")
                        return
            except httpx.ConnectTimeout:
                error = ProviderError("模型连接超时", True)
            except httpx.TimeoutException:
                error = ProviderError("等待模型响应超时；未自动重复已发送的请求，请按需手动重试", False)
            except httpx.ConnectError:
                error = ProviderError("无法连接模型服务，请检查网络和 API 地址", True)
            except httpx.HTTPError:
                error = ProviderError("模型网络连接中断，请检查网络后手动重试", not accepted)
            except ProviderError as exc:
                error = exc
            if received or not error.retryable or attempt >= p["retries"]:
                raise error
            yield {"phase": "retrying", "attempt": attempt + 2}
            await asyncio.sleep(min(2 ** attempt, 4))

    async def models(self):
        if not self.key:
            raise ProviderError("未配置 API Key")
        try:
            async with self.client() as client:
                r = await client.get(self.config["base_url"].rstrip("/") + "/models", headers={"Authorization": "Bearer " + self.key}, timeout=self.timeout())
                if r.status_code != 200:
                    raise ProviderError(f"模型列表检查 HTTP {r.status_code}")
                return [x["id"] for x in r.json()["data"]]
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise ProviderError("模型列表检查失败：网络、超时或响应格式错误") from None

ADAPTERS = {"openai": OpenAICompatible}

def adapter(config, key, shared_client=None):
    try:
        return ADAPTERS[config["protocol"]](config, key, shared_client=shared_client)
    except KeyError:
        raise ProviderError("供应商协议尚未实现") from None
