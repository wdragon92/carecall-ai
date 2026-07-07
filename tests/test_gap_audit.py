"""외부 감사(병행 세션)에서 지적된 테스트 갭 4건 보강.
① fetch._keep_age 분기 ② _offer_candidate 결정적 폴백 ③ flush_extract 경합 회귀
④ LLM 완전 실패 + 사기 발화 조합(결정망 생존)."""
import asyncio
from types import SimpleNamespace

from app.core import extraction
from app.core.conversation import _offer_candidate
from app.rag.fetch import REGIONS, _keep_age


# ---- ① _keep_age / REGIONS ----
def test_keep_age_branches():
    # 생애주기에 노년 포함 + 본문 무해 → 유지
    assert _keep_age({"lifeArray": "노년", "servNm": "어르신 건강지원", "servDgst": ""}, "lifeArray")
    # 노년 미포함 생애주기 → 제외
    assert not _keep_age({"lifeArray": "청년,중장년", "servNm": "취업 지원", "servDgst": ""}, "lifeArray")
    # 노년 공존 태그라도 서비스명이 비어르신 전용이면 제외 (v3: 다중 태그 구멍 봉합)
    assert not _keep_age({"lifeArray": "청년,노년", "servNm": "청년 월세 특별지원", "servDgst": ""}, "lifeArray")
    # 생애주기 미표기: 본문 판정 — 전연령성 유지 / 비어르신 제외
    assert _keep_age({"lifeArray": "", "servNm": "긴급복지 생계지원", "servDgst": "위기 가구 지원"}, "lifeArray")
    assert not _keep_age({"lifeArray": "", "servNm": "임산부 영양제 지원", "servDgst": ""}, "lifeArray")


def test_regions_constant_is_daegu_track():
    # 지자체 수집 트랙 상수 — 사용자 페르소나(대구) 계약의 데이터측 근거
    assert "대구광역시" in REGIONS and "경상북도" in REGIONS


# ---- ② _offer_candidate 결정적 폴백 ----
def test_offer_candidate_deterministic_fallback():
    """비동기 추출(welfare_matched)이 비어 있어도 발화 키워드 매칭으로 즉석 후보를 낸다."""
    sess = SimpleNamespace(
        welfare_matched=[],
        welfare_cards={},
        user_transcript=lambda: "어르신: 겨울엔 난방비가 무서워서 보일러도 못 틀어",
    )
    assert _offer_candidate(sess) == "에너지바우처"
    # 이미 안내한 서비스는 후보에서 제외
    sess.welfare_cards = {"x": {"이름": "에너지바우처"}}
    assert _offer_candidate(sess) != "에너지바우처"
    # 키워드도 없으면 None
    sess2 = SimpleNamespace(welfare_matched=[], welfare_cards={},
                            user_transcript=lambda: "어르신: 오늘 날씨 참 좋네")
    assert _offer_candidate(sess2) is None


# ---- 공용: 추출용 가짜 세션/프로바이더 ----
class _Sess(SimpleNamespace):
    async def send(self, payload):
        self.sent.append(payload)
        return True


def _mk_sess(transcript: str) -> _Sess:
    return _Sess(
        sent=[], findings=[], welfare_matched=[], welfare_cards={},
        extract_lock=asyncio.Lock(), extract_dirty=False, last_alert=None,
        user_transcript=lambda: transcript,
    )


class _BoomLLM:
    async def extract_json(self, messages, schema):
        raise RuntimeError("real down")


# ---- ③ flush_extract 경합 회귀 ----
def test_flush_extract_waits_for_inflight_and_drains_dirty():
    """flush는 진행 중 추출이 끝나길 기다리고, 그 사이 낀 dirty까지 소화한다
    (실측: /end가 마지막 턴 사기_노출을 놓치던 경합)."""

    async def main():
        sess = _mk_sess("어르신: 보이스피싱 문자를 받았어")
        providers = SimpleNamespace(llm=_BoomLLM(), mllm=_BoomLLM())
        order: list[str] = []

        async def inflight():
            async with sess.extract_lock:
                order.append("inflight-start")
                await asyncio.sleep(0.15)
                order.append("inflight-end")

        t = asyncio.create_task(inflight())
        await asyncio.sleep(0.02)  # inflight가 락을 먼저 점유
        sess.extract_dirty = True  # flush 대기 중 끼어든 턴 시뮬레이션
        await extraction.flush_extract(sess, providers)
        order.append("flush-done")
        await t
        assert order == ["inflight-start", "inflight-end", "flush-done"]
        assert sess.extract_dirty is False  # dirty 루프 소화됨
        # 결정망이 사기_노출을 남겼는지 (LLM은 전부 실패)
        cats = {f.category for f in sess.findings}
        assert "사기_노출" in cats

    asyncio.run(main())


# ---- ④ LLM 완전 실패 + 사기 발화 → 결정망 생존 ----
def test_llm_total_failure_keeps_deterministic_fraud():
    """real·mock 추출이 모두 죽어도 사기 발화는 결정망이 findings·경보로 남긴다."""

    async def main():
        sess = _mk_sess("어르신: 아들인 줄 알고 돈을 보냈는데 아무래도 사기 같아")
        providers = SimpleNamespace(llm=_BoomLLM(), mllm=_BoomLLM())
        await extraction.trigger_extract(sess, providers)
        cats = {f.category for f in sess.findings}
        assert "사기_노출" in cats
        alerts = [m for m in sess.sent if m.get("type") == "urgent_alert"]
        assert alerts and alerts[0]["level"] == "warning" and "112" in alerts[0]["message"]
        finds = [m for m in sess.sent if m.get("type") == "findings_update"]
        assert finds  # 패널 갱신도 전송됨

    asyncio.run(main())
