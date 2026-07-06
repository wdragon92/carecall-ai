"""[카드 사슬] 계약 8~10 — 카드 발생 턴 이후의 상태 사슬과 TTS 배선 (화이트박스).

계약 8: 카드 턴 → sess.welfare_cards 등재 + 같은 턴 welfare_update에 같은 이름·url
        + sess.last_rag 갱신 + /end 리포트 welfare에 포함 (한 사건이 네 곳에 일관 전파).
계약 9: 카드 메시지 TTS — /tts는 200 오디오를 주되, 합성 엔진에 넘어간 텍스트는
        카드 본문이 아니라 tts_text(짧은 안내문)여야 한다 (스파이 TTS로 캡처).
계약 10: 같은 message_id 재요청은 세션 캐시 히트 — 합성 엔진은 1회만 호출.
"""
import re

from test_functional_helpers import (
    GROUNDING_Q,
    handshake,
    install_tts_spy,
    sess_of,
    user_turn,
)


def _card_turn(client, ws):
    bubbles, seen = user_turn(ws, GROUNDING_Q)
    card = bubbles[-1]
    assert card.get("kind") == "card", bubbles
    return card, seen


# ---- 계약 8: 카드 → 세션 상태·패널·리포트 사슬 ----
def test_card_turn_propagates_to_session_panel_and_report(rag_client):
    sid = rag_client.post("/api/sessions").json()["session_id"]
    with rag_client.websocket_connect(f"/ws/{sid}") as ws:
        handshake(ws)
        card, seen = _card_turn(rag_client, ws)
        title = card["card"]["title"]
        assert title and card["card"]["url"].startswith("http")

        sess = sess_of(rag_client, sid)

        # last_rag 갱신 (후속 질문 보강의 근거)
        assert sess.last_rag == {"서비스명": title, "serv_id": sess.last_rag["serv_id"]}
        serv_id = sess.last_rag["serv_id"]

        # welfare_cards 등재 — 이름·url이 카드와 일치
        assert serv_id in sess.welfare_cards
        entry = sess.welfare_cards[serv_id]
        assert entry["이름"] == title
        assert entry["url"].startswith("http")

        # 같은 턴 welfare_update(패널)에도 같은 이름 + url
        wus = [m for m in seen if m["type"] == "welfare_update"]
        assert len(wus) == 1  # 카드 턴 안에서 정확히 1회 push
        assert any(
            it["이름"] == title and str(it.get("url", "")).startswith("http")
            for it in wus[0]["items"]
        ), wus[0]["items"]

    # /end 리포트 welfare에도 카드가 병합된다 (RAG 카드 우선)
    rep = rag_client.post(f"/api/sessions/{sid}/end").json()["report"]
    assert any(w.get("이름") == title for w in rep["welfare"]), rep["welfare"]


# ---- 계약 9: 카드 TTS는 본문이 아니라 tts_text를 합성한다 ----
def test_card_tts_synthesizes_guidance_not_card_body(rag_client):
    tts_spy = install_tts_spy(rag_client)
    sid = rag_client.post("/api/sessions").json()["session_id"]
    with rag_client.websocket_connect(f"/ws/{sid}") as ws:
        handshake(ws)
        card, _ = _card_turn(rag_client, ws)

    r = rag_client.post(f"/api/sessions/{sid}/tts", json={"message_id": card["id"]})
    assert r.status_code == 200
    assert r.content[:4] == b"RIFF"  # MockTTS WAV
    assert r.headers["content-type"] == "audio/wav"

    # 서버가 합성 엔진에 '실제로 넘긴' 텍스트 검증
    assert len(tts_spy.texts) == 1
    spoken = tts_spy.texts[0]
    assert "정보 카드로 정리해 드렸어요" in spoken  # tts_text 안내문
    assert card["card"]["title"] in spoken  # 어떤 카드인지 이름으로만
    assert "📌" not in spoken  # 카드 기호·본문 미낭독
    assert "· " not in spoken
    assert not re.search(r"\d+\s*원|\d+\s*만\s*원", spoken)  # 금액 미낭독 (T2: 수치는 화면만)
    assert "129" not in spoken  # 카드의 문의처 줄도 낭독 대상이 아님


# ---- 계약 10: 같은 message_id 재요청은 캐시 히트 ----
def test_card_tts_second_request_is_cache_hit(rag_client):
    tts_spy = install_tts_spy(rag_client)
    sid = rag_client.post("/api/sessions").json()["session_id"]
    with rag_client.websocket_connect(f"/ws/{sid}") as ws:
        handshake(ws)
        card, _ = _card_turn(rag_client, ws)

    r1 = rag_client.post(f"/api/sessions/{sid}/tts", json={"message_id": card["id"]})
    r2 = rag_client.post(f"/api/sessions/{sid}/tts", json={"message_id": card["id"]})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r2.content == r1.content  # 같은 오디오
    assert len(tts_spy.texts) == 1  # 합성은 1회 — 두 번째는 sess.tts_cache 히트

    # 화이트박스: 캐시에 해당 message_id 키가 실제로 존재
    sess = sess_of(rag_client, sid)
    assert card["id"] in sess.tts_cache
