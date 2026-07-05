"""CLOVA Studio (HyperCLOVA X) 실 구현 — Chat Completions v3.
스펙: POST {BASE}/v3/chat-completions/{model}, Bearer 인증,
스트리밍은 Accept: text/event-stream, SSE `event: token`의 message.content 증분."""
from __future__ import annotations

import json
import logging
import uuid
from typing import AsyncIterator

import httpx

from app.config import Settings
from app.services.base import ProviderError

log = logging.getLogger("clova_llm")
BASE = "https://clovastudio.stream.ntruss.com"


def _parse_json(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t[:4].lower() == "json":
            t = t[4:]
    i, j = t.find("{"), t.rfind("}")
    if i != -1 and j != -1 and j > i:
        t = t[i : j + 1]
    return json.loads(t)


class ClovaLLM:
    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.model = (settings.clova_llm_model or "HCX-007").strip()       # 분석용(reasoning)
        self.chat_model = (settings.clova_chat_model or "HCX-005").strip()  # 채팅용(빠름)
        self.key = settings.clova_studio_api_key.strip()
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))

    def _headers(self, stream: bool) -> dict:
        return {
            "Authorization": f"Bearer {self.key}",
            "X-NCP-CLOVASTUDIO-REQUEST-ID": uuid.uuid4().hex,
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
        }

    def _body(self, messages: list[dict], **opts) -> dict:
        # HCX-007 등 reasoning 계열은 maxTokens 대신 maxCompletionTokens 사용
        body = {
            "messages": messages,
            "maxCompletionTokens": int(opts.get("max_tokens", 1024)),
            "temperature": float(opts.get("temperature", 0.5)),
            "topP": float(opts.get("top_p", 0.8)),
            "repetitionPenalty": float(opts.get("repetition_penalty", 1.1)),
        }
        if opts.get("stop"):
            body["stop"] = opts["stop"]
        return body

    async def chat_stream(self, messages: list[dict], **opts) -> AsyncIterator[str]:
        url = f"{BASE}/v3/chat-completions/{self.chat_model}"
        body = self._body(messages, **opts)
        try:
            async with self._client.stream("POST", url, headers=self._headers(True), json=body) as resp:
                if resp.status_code != 200:
                    detail = (await resp.aread())[:300]
                    raise ProviderError(f"CLOVA LLM {resp.status_code}: {detail!r}")
                event = None
                async for line in resp.aiter_lines():
                    if not line:
                        event = None
                        continue
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:") and event == "token":
                        data = line[5:].strip()
                        if not data:
                            continue
                        try:
                            chunk = json.loads(data).get("message", {}).get("content", "")
                        except json.JSONDecodeError:
                            continue
                        if chunk:
                            yield chunk
        except httpx.HTTPError as exc:
            raise ProviderError(f"CLOVA LLM stream error: {exc}") from exc

    async def chat(self, messages: list[dict], *, model: str | None = None, **opts) -> str:
        url = f"{BASE}/v3/chat-completions/{model or self.chat_model}"
        body = self._body(messages, **opts)
        try:
            resp = await self._client.post(url, headers=self._headers(False), json=body)
        except httpx.HTTPError as exc:
            raise ProviderError(f"CLOVA LLM error: {exc}") from exc
        if resp.status_code != 200:
            raise ProviderError(f"CLOVA LLM {resp.status_code}: {resp.text[:300]}")
        try:
            data = resp.json()
        except ValueError as exc:  # 200인데 본문이 JSON이 아님
            raise ProviderError(f"CLOVA LLM non-JSON response: {resp.text[:200]!r}") from exc
        content = ""
        if isinstance(data, dict):
            content = (data.get("result") or {}).get("message", {}).get("content", "") or ""
        if not content:
            raise ProviderError(f"CLOVA LLM empty response: {resp.text[:200]}")
        return content

    async def extract_json(self, messages: list[dict], schema: dict) -> dict:
        # 분석용 reasoning 모델 사용 (thinking 여유 위해 토큰 넉넉히)
        text = await self.chat(
            messages, model=self.model, temperature=0.1, top_p=0.8, max_tokens=2048
        )
        try:
            return _parse_json(text)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProviderError(f"CLOVA LLM JSON parse failed: {exc}: {text[:200]!r}") from exc
