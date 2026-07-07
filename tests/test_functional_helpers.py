"""기능 계약(functional invariant) 테스트 공용 헬퍼 + 소스 수준 계약.

원칙 (tests/test_functional_*.py 공통):
- app/ 소스 무수정. 스파이 주입은 app.state.providers의 '속성 교체'로만 한다
  (mock 모드에선 providers.llm is providers.mllm 이므로 두 자리 모두 갈아끼운다).
- 입력 멘트의 '내용'이 아니라 컴포넌트 간 배선·타이밍·상태 계약을 검증한다.
- 전부 MOCK 모드 (conftest가 강제). client/rag_client 픽스처 재사용.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"

# 목 인덱스(12장 픽스처)에서 게이트를 확실히 통과/거부하는 결정적 질의
GROUNDING_Q = "치매 약값이 걱정이에요"          # → found + 카드 (test_rag_flow와 동일 근거)
ALIEN_Q = "asdf qwer zxcv 1234"                # → 게이트 거부 (문서 밖 토큰)


# ---------- WS 수신 유틸 ----------
def drain_until(ws, pred, max_msgs: int = 120):
    """pred가 참이 되는 메시지까지 수신. (그 메시지, 지금까지 전부) 반환."""
    seen = []
    for _ in range(max_msgs):
        m = ws.receive_json()
        seen.append(m)
        if pred(m):
            return m, seen
    raise AssertionError("message not received; types=" + str([x.get("type") for x in seen]))


def is_type(t: str):
    return lambda m: m.get("type") == t


def handshake(ws) -> dict:
    """session_ready + 선인사 ai_turn까지 소화하고 선인사 턴을 반환."""
    assert ws.receive_json()["type"] == "session_ready"
    greet, _ = drain_until(ws, is_type("ai_turn"))
    return greet


def user_turn(ws, text: str):
    """사용자 발화 1턴: 전송 → 이 턴의 ai_turn까지 수신.
    반환: (bubbles, 전송 후 ai_turn까지 수신한 전체 메시지 목록 — ai_turn 포함)."""
    ws.send_json({"type": "user_message", "text": text})
    turn, seen = drain_until(ws, is_type("ai_turn"))
    return turn["bubbles"], seen


def typing_flags(seen: list[dict]) -> list[bool]:
    return [m["on"] for m in seen if m.get("type") == "ai_typing"]


def rag_statuses(seen: list[dict]) -> list[dict]:
    return [m for m in seen if m.get("type") == "rag_status"]


def card_bubbles(bubbles: list[dict]) -> list[dict]:
    return [b for b in bubbles if b.get("kind") == "card"]


def sess_of(client, sid: str):
    """스토어에서 세션 객체 화이트박스 조회 (TestClient.app == FastAPI 앱)."""
    return client.app.state.store.get(sid)


# ---------- 프로바이더 스파이 ----------
class SpyLLM:
    """providers.llm 자리에 끼우는 스파이 — 원본에 위임하며 호출·메시지를 기록.
    extract_delay로 추출(extract_json)만 늦출 수 있다(코얼레싱 경로 강제용)."""

    def __init__(self, inner, extract_delay: float = 0.0) -> None:
        self._inner = inner
        self._delay = extract_delay
        self.chat_calls: list[list[dict]] = []      # 호출별 messages 스냅숏
        self.extract_calls: list[list[dict]] = []

    async def chat(self, messages, **opts):
        self.chat_calls.append([dict(m) for m in messages])
        return await self._inner.chat(messages, **opts)

    async def extract_json(self, messages, schema):
        self.extract_calls.append([dict(m) for m in messages])
        if self._delay:
            await asyncio.sleep(self._delay)
        return await self._inner.extract_json(messages, schema)

    def chat_system(self, i: int = -1) -> str:
        msgs = self.chat_calls[i]
        assert msgs and msgs[0]["role"] == "system", msgs[:1]
        return msgs[0]["content"]

    def extract_systems(self) -> list[str]:
        return [c[0]["content"] for c in self.extract_calls if c and c[0]["role"] == "system"]


class SpyTTS:
    """providers.tts 자리 스파이 — 서버가 합성 엔진에 '실제로 넘긴 텍스트'를 기록."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.texts: list[str] = []

    async def synthesize(self, text: str) -> bytes:
        self.texts.append(text)
        return await self._inner.synthesize(text)


class BoomEmbed:
    """임베딩 장애 주입 — _rag_lookup이 조용히 수다 경로로 폴백해야 한다."""

    async def embed(self, texts):
        raise RuntimeError("embed down (functional test)")


class NegationChatLLM:
    """chat만 '없다' 정직 답변으로 고정, 추출은 원본에 위임 — 게이트는 통과했지만
    카드가 부정 게이트(answer.pick_card)로 빠지는 소문성 턴을 결정적으로 재현한다."""

    def __init__(self, inner) -> None:
        self._inner = inner

    async def chat(self, messages, **opts):
        # 금액을 일부러 되뇐다 — 카드 없는 턴의 T2 치환이 '화면 카드'를 헛가리키지 않는지까지 고정
        return "그런 매월 100만 원씩 드리는 제도는 자료에서 확인되지 않아요. 대신 도움이 될 만한 게 있는지 같이 찾아볼게요."

    async def extract_json(self, messages, schema):
        return await self._inner.extract_json(messages, schema)


def install_llm_spy(client, extract_delay: float = 0.0) -> SpyLLM:
    p = client.app.state.providers
    spy = SpyLLM(p.llm, extract_delay=extract_delay)
    p.llm = spy
    p.mllm = spy  # real 실패 폴백 경로까지 동일 스파이로 — chat 미호출 검증의 빈틈 제거
    return spy


def install_tts_spy(client) -> SpyTTS:
    p = client.app.state.providers
    spy = SpyTTS(p.tts)
    p.tts = spy
    p.mtts = spy
    return spy


# ---------- 소스 수준 계약: rag_status 상태 리터럴은 3종뿐 ----------
def test_source_contract_rag_status_literals():
    """rag_status 전송 지점의 상태는 searching(게이트 통과) → found(카드 확정) /
    no_match(카드 미부착 해소) 3종뿐 — 그 외 리터럴('none' 등) 전송 지점이 없어야 한다.
    (동적 검증은 test_functional_turn_orchestration이 경로별로 함께 수행)"""
    statuses: list[str] = []
    for p in APP_DIR.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        for m in re.finditer(r'"rag_status"', text):
            window = text[m.start(): m.start() + 250]
            statuses += re.findall(r'"status"\s*:\s*"([a-z_]+)"', window)
    assert statuses, "rag_status 전송 지점을 소스에서 찾지 못함 — 계약 테스트 갱신 필요"
    assert set(statuses) == {"searching", "found", "no_match"}, statuses
