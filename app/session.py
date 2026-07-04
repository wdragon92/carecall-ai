"""세션 모델 + 인메모리 스토어 (session §5). 세션별 완전 격리, DB 없음, TTL 폐기."""
from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from collections import OrderedDict
from datetime import datetime, timezone

from app.models import Finding, Message


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def finding_id(category: str, content: str) -> str:
    return hashlib.sha1(f"{category}|{content[:20]}".encode("utf-8")).hexdigest()[:8]


class Session:
    def __init__(self, sid: str) -> None:
        self.id = sid
        self.created_at = _utcnow()
        self.last_active = time.monotonic()
        self.messages: list[Message] = []
        self.findings: list[Finding] = []
        self.welfare_matched: list[str] = []
        self.ocr_texts: list[str] = []
        self.tts_cache: "OrderedDict[str, bytes]" = OrderedDict()
        self.extract_lock = asyncio.Lock()
        self.extract_dirty = False
        self.voice_on = True
        self.ws = None  # 활성 WebSocket (있으면)
        self._mcount = 0

    def touch(self) -> None:
        self.last_active = time.monotonic()

    def add_message(self, role: str, text: str, via: str = "text") -> Message:
        self._mcount += 1
        msg = Message(id=f"m{self._mcount}-{secrets.token_hex(3)}", role=role, text=text, via=via)
        self.messages.append(msg)
        self.touch()
        return msg

    def cache_tts(self, message_id: str, audio: bytes, cap: int = 20) -> None:
        self.tts_cache[message_id] = audio
        self.tts_cache.move_to_end(message_id)
        while len(self.tts_cache) > cap:
            self.tts_cache.popitem(last=False)

    def history_for_llm(self, limit: int = 40) -> list[dict]:
        msgs = [m for m in self.messages if m.role in ("user", "assistant")][-limit:]
        return [{"role": m.role, "content": m.text} for m in msgs]

    def transcript_text(self, max_chars: int = 6000) -> str:
        lines = []
        for m in self.messages:
            if m.role == "system":
                continue
            who = "어르신" if m.role == "user" else "상담원"
            lines.append(f"{who}: {m.text}")
        for t in self.ocr_texts:
            lines.append(f"[첨부문서]: {t}")
        text = "\n".join(lines)
        return text[-max_chars:]


class SessionStore:
    def __init__(self, ttl_min: int = 120, max_sessions: int = 200) -> None:
        self._sessions: "OrderedDict[str, Session]" = OrderedDict()
        self._ttl = ttl_min * 60
        self._max = max_sessions
        self._lock = asyncio.Lock()

    async def create(self) -> Session:
        async with self._lock:
            sid = secrets.token_urlsafe(16)
            sess = Session(sid)
            self._sessions[sid] = sess
            self._sessions.move_to_end(sid)
            # 용량 초과 시 가장 오래 활동 없는 세션 축출
            while len(self._sessions) > self._max:
                self._sessions.popitem(last=False)
            return sess

    def get(self, sid: str) -> Session | None:
        sess = self._sessions.get(sid)
        if sess is not None:
            sess.touch()
            self._sessions.move_to_end(sid)
        return sess

    async def drop(self, sid: str) -> None:
        async with self._lock:
            self._sessions.pop(sid, None)

    async def sweep(self) -> int:
        now = time.monotonic()
        async with self._lock:
            expired = [sid for sid, s in self._sessions.items() if now - s.last_active > self._ttl]
            for sid in expired:
                self._sessions.pop(sid, None)
        return len(expired)

    def count(self) -> int:
        return len(self._sessions)
