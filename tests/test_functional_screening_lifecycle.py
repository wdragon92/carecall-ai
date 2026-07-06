"""[스크리닝 수명] 계약 11~12 — _pending 수명 종단 + 판정 후 리포트 (화이트박스).

계약 11: 판정 질문 → 나이 되묻기(_pending=2) → 백채널 '응'(pending 유지)
        → '일흔둘이야'(가구 되묻기, _pending 재충전) → '혼자 살아'(패키지 카드
        + apply_packages 등재, _pending=0) → 이후 일반 턴은 수다 경로로 정상 복귀.
계약 12: 판정 완료 후 /end 리포트 — apply_packages에 기초연금 정확히 1건,
        welfare에도 기초연금 포함.
"""
from test_functional_helpers import (
    card_bubbles,
    handshake,
    sess_of,
    typing_flags,
    user_turn,
)


def _pending(sess) -> int:
    return int(sess.slots.get("_pending", 0) or 0)


# ---- 계약 11: _pending 수명 종단 ----
def test_pending_lifecycle_survives_backchannel_and_completes(rag_client):
    sid = rag_client.post("/api/sessions").json()["session_id"]
    with rag_client.websocket_connect(f"/ws/{sid}") as ws:
        handshake(ws)
        sess = sess_of(rag_client, sid)

        # T1 판정 질문 → 룰엔진이 나이 되묻기, 되묻기 문맥 2턴 장전
        b1, s1 = user_turn(ws, "기초연금 나도 받을 수 있나?")
        assert "연세" in b1[0]["text"]
        assert typing_flags(s1) == []  # 스크리닝 턴은 typing 미사용(즉답)
        assert _pending(sess) == 2

        # T2 백채널 '응' — 판정 문맥을 소모하지 않고 유지(수다 경로로 짧게 응답)
        b2, s2 = user_turn(ws, "응")
        assert typing_flags(s2) == [True, False]  # 일반(백채널) 발화 경로
        assert card_bubbles(b2) == []
        assert _pending(sess) == 2  # ★ 백채널이 되묻기 카운터를 갉아먹지 않는다

        # T3 나이 답 → 슬롯 적재 + 가구 되묻기(문맥 재장전)
        b3, s3 = user_turn(ws, "올해 일흔둘이야")
        assert "혼자" in b3[0]["text"] or "배우자" in b3[0]["text"]
        assert typing_flags(s3) == []
        assert sess.slots.get("age") == 72
        assert _pending(sess) == 2

        # T4 가구 답 → 판정 + 신청 패키지 카드(마지막 버블) + 상태 등재
        b4, s4 = user_turn(ws, "혼자 살아")
        assert sess.slots.get("household") == "single"
        assert _pending(sess) == 0
        assert b4[-1].get("kind") == "card"
        assert b4[-1]["text"].startswith("📝") and "신분증" in b4[-1]["text"]
        assert "기초연금" in sess.apply_packages
        assert "fixture-basic-pension" in sess.welfare_cards
        assert any(m["type"] == "welfare_update" for m in s4)  # 패널도 같은 턴 갱신

        # T5 이후 일반 턴 — 스크리닝 문맥이 남지 않고 수다 경로(typing 동반)로 복귀
        b5, s5 = user_turn(ws, "고향 생각이 나네")
        assert typing_flags(s5) == [True, False]
        assert card_bubbles(b5) == []
        assert _pending(sess) == 0


# ---- 계약 12: 판정 완료 후 리포트 연계 ----
def test_report_after_verdict_has_exactly_one_package(rag_client):
    sid = rag_client.post("/api/sessions").json()["session_id"]
    with rag_client.websocket_connect(f"/ws/{sid}") as ws:
        handshake(ws)
        user_turn(ws, "기초연금 나도 받을 수 있나?")
        user_turn(ws, "올해 일흔둘이야")
        b, _ = user_turn(ws, "혼자 살아")
        assert b[-1].get("kind") == "card"  # 패키지 카드까지 나간 상태

    rep = rag_client.post(f"/api/sessions/{sid}/end").json()["report"]

    # apply_packages: 기초연금 정확히 1건 (재판정에도 dict 키로 중복 방지)
    names = [p["서비스명"] for p in rep["apply_packages"]]
    assert names == ["기초연금"]
    pkg = rep["apply_packages"][0]
    assert "신분증" in pkg["필요서류"]
    assert pkg["온라인신청"].startswith("http")

    # welfare 패널 병합에도 기초연금 포함
    assert any(w.get("이름") == "기초연금" for w in rep["welfare"])
