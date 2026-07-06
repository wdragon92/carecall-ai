"""[격리·수명] 계약 15~16 — 세션 간 상태 격리 + /end 이후 세션 수명.

계약 15: 세션 2개를 인터리브해도 A의 카드 산출물(welfare_cards/last_rag)이나
        슬롯이 B로 새지 않는다 (스토어 화이트박스 + B 채널 메시지 무오염).
계약 16: /end 후에도 세션은 스토어에 남고 messages가 보존되며,
        같은 sid로 WS 재연결 시 선인사가 중복되지 않는다.
"""
from test_functional_helpers import (
    GROUNDING_Q,
    card_bubbles,
    drain_until,
    handshake,
    is_type,
    rag_statuses,
    sess_of,
    user_turn,
)


# ---- 계약 15: 두 세션 인터리브 — 오염 없음 ----
def test_interleaved_sessions_do_not_cross_pollute(rag_client):
    sid_a = rag_client.post("/api/sessions").json()["session_id"]
    sid_b = rag_client.post("/api/sessions").json()["session_id"]

    with rag_client.websocket_connect(f"/ws/{sid_a}") as wsa, \
            rag_client.websocket_connect(f"/ws/{sid_b}") as wsb:
        handshake(wsa)
        handshake(wsb)

        # 인터리브: A(카드 발생 질의)와 B(잡담)를 응답 대기 없이 교차 전송
        wsa.send_json({"type": "user_message", "text": GROUNDING_Q})
        wsb.send_json({"type": "user_message", "text": "오늘 날씨가 좋네요"})

        turn_a, seen_a = drain_until(wsa, is_type("ai_turn"))
        turn_b, seen_b = drain_until(wsb, is_type("ai_turn"))

        # A에는 카드가 붙는다
        assert turn_a["bubbles"][-1].get("kind") == "card"
        title = turn_a["bubbles"][-1]["card"]["title"]
        assert rag_statuses(seen_a)

        # B 채널에는 A의 산출물이 전혀 새지 않는다
        assert rag_statuses(seen_b) == []
        assert all(m["type"] != "welfare_update" for m in seen_b)
        assert card_bubbles(turn_b["bubbles"]) == []

        # B의 추출까지 끝낸 뒤 상태 비교 (경합 배제)
        fu_b, _ = drain_until(wsb, is_type("findings_update"))
        assert fu_b["findings"] == []  # 잡담은 관찰 없음

        sess_a = sess_of(rag_client, sid_a)
        sess_b = sess_of(rag_client, sid_b)

        # A: 카드 사슬 상태 보유
        assert sess_a.last_rag and sess_a.last_rag["서비스명"] == title
        assert sess_a.welfare_cards

        # B: 화이트박스 무오염 — 카드·RAG·슬롯·패키지·OCR 전부 깨끗
        assert dict(sess_b.welfare_cards) == {}
        assert sess_b.last_rag is None
        assert sess_b.slots == {}
        assert sess_b.apply_packages == {}
        assert sess_b.ocr_texts == []
        assert all(m.text != GROUNDING_Q for m in sess_b.messages)  # 발화 자체도 격리


# ---- 계약 16: /end 후 세션 유지 + 재연결 인사 미중복 ----
def test_end_keeps_session_then_reconnect_skips_greeting(client):
    sid = client.post("/api/sessions").json()["session_id"]
    with client.websocket_connect(f"/ws/{sid}") as ws:
        handshake(ws)
        user_turn(ws, "무릎이 아파")

    rep = client.post(f"/api/sessions/{sid}/end")
    assert rep.status_code == 200 and rep.json()["report"]["summary"]

    # /end는 세션을 폐기하지 않는다 — 스토어 유지 + messages 보존
    sess = sess_of(client, sid)
    assert sess is not None
    n_before = len(sess.messages)
    assert n_before >= 3  # 선인사 + 사용자 + 응답
    assert sum(1 for m in sess.messages if m.via == "system") == 1  # 선인사 1회

    # 같은 sid 재연결 — 인사 미중복: 첫 ai_turn은 (typing을 동반한) 내 턴의 응답이어야 함
    with client.websocket_connect(f"/ws/{sid}") as ws:
        assert ws.receive_json()["type"] == "session_ready"
        _, seen = user_turn(ws, "고향 생각이 나네")
        i_turn = [m["type"] for m in seen].index("ai_turn")
        assert any(m["type"] == "ai_typing" and m["on"] for m in seen[:i_turn]), (
            "typing 없이 온 첫 ai_turn — 재연결 인사가 중복된 것"
        )

    assert sum(1 for m in sess.messages if m.via == "system") == 1  # 여전히 인사 1회
    assert len(sess.messages) > n_before  # 대화가 이어져 쌓였다 (초기화 아님)
