"""[추출 파이프라인] 계약 13~14 — 코얼레싱 e2e + 이미지 턴 사슬.

계약 13: 연속 3턴을 빠르게 보내도 세션이 죽지 않고, 코얼레싱(dirty 재실행)으로
        추출 실행 횟수는 트리거 수보다 적으며, 최종 findings_update는 마지막
        상태(3개 관찰 전부)를 반영한다.
계약 14: /image 업로드 → ocr_status processing→done 순서 → 설명 ai_turn과
        문서 카드 ai_turn 분리 → sess.ocr_texts '[종류] ' 접두 → /end 리포트
        findings에 사기_노출(스미싱 목) 포함.
"""
from test_functional_helpers import (
    drain_until,
    handshake,
    install_llm_spy,
    is_type,
    sess_of,
    user_turn,
)

from app.core import prompts_analysis


# ---- 계약 13: 코얼레싱 — 빠른 3턴에도 생존 + 최종 상태 완전 ----
def test_rapid_turns_coalesce_and_final_findings_complete(rag_client):
    # 추출만 0.3초 지연시켜 턴 간 겹침(dirty 경로)을 강제 — chat은 즉답 유지
    spy = install_llm_spy(rag_client, extract_delay=0.3)
    sid = rag_client.post("/api/sessions").json()["session_id"]
    with rag_client.websocket_connect(f"/ws/{sid}") as ws:
        handshake(ws)

        for text in ("요즘 잠을 통 못 자요", "무릎이 아파", "생활비가 부담돼서 걱정이야"):
            ws.send_json({"type": "user_message", "text": text})  # 응답 대기 없이 연속 전송

        # 세 턴 모두 정상 응답 (추출 지연이 대화 턴을 막지 않는다)
        for _ in range(3):
            drain_until(ws, is_type("ai_turn"))

        # 최종 findings_update가 마지막 상태를 반영: 3개 관찰 전부
        want = ("수면의 어려움", "신체적 통증", "경제적 어려움")

        def complete(m):
            if m.get("type") != "findings_update":
                return False
            joined = " ".join(f["content"] for f in m["findings"])
            return all(w in joined for w in want)

        _, seen = drain_until(ws, complete)
        assert all(m.get("type") != "error" for m in seen)

        # 코얼레싱 증거: 트리거 3회가 '첫 실행 + dirty 재실행' 이하로 접혔다
        runs = sum(1 for s in spy.extract_systems() if s == prompts_analysis.EXTRACT_SYSTEM)
        assert 1 <= runs <= 2, f"extract runs={runs} (coalescing 미동작?)"

        # 세션 생존 — 다음 턴도 정상
        b, _ = user_turn(ws, "고향 생각이 나네")
        assert b and b[0]["text"].strip()


# ---- 계약 14: 이미지 턴 사슬 — OCR 상태·이중 턴·접두·리포트 ----
def test_image_turn_chain_smishing_to_report(client):
    sid = client.post("/api/sessions").json()["session_id"]
    with client.websocket_connect(f"/ws/{sid}") as ws:
        handshake(ws)

        files = {"file": ("의심문자.png", b"\x89PNG\r\n\x1a\nfake-bytes", "image/png")}
        r = client.post(f"/api/sessions/{sid}/image", files=files)
        assert r.status_code == 202
        uid = r.json()["upload_id"]

        def is_card_turn(m):
            return m.get("type") == "ai_turn" and any(
                b.get("kind") == "card" for b in m.get("bubbles", [])
            )

        _, seen = drain_until(ws, is_card_turn)

        # ocr_status: 같은 upload_id로 processing → done 순서, 첫 ai_turn보다 앞
        oc = [m for m in seen if m["type"] == "ocr_status"]
        assert [m["status"] for m in oc] == ["processing", "done"]
        assert all(m["upload_id"] == uid for m in oc)
        i_done = next(i for i, m in enumerate(seen) if m["type"] == "ocr_status" and m["status"] == "done")
        i_first_turn = next(i for i, m in enumerate(seen) if m["type"] == "ai_turn")
        assert i_done < i_first_turn

        # 설명 턴과 문서 카드 턴은 '별도' ai_turn
        turns = [m for m in seen if m["type"] == "ai_turn"]
        assert len(turns) == 2
        expl, card_turn = turns
        assert expl["bubbles"] and all(b.get("kind") != "card" for b in expl["bubbles"])
        cb = card_turn["bubbles"]
        assert len(cb) == 1 and cb[0].get("kind") == "card"
        assert "문자·메시지" in cb[0]["text"]
        assert "사기" in cb[0]["text"] and "링크" in cb[0]["text"]

        # 추출까지 완료 대기 → ocr_texts에 '[종류] ' 접두 문맥이 적재됨
        drain_until(
            ws,
            lambda m: m.get("type") == "findings_update"
            and any(f["category"] == "사기_노출" for f in m["findings"]),
        )
        sess = sess_of(client, sid)
        assert sess.ocr_texts and sess.ocr_texts[-1].startswith("[문자·메시지] ")
        assert "Web발신" in sess.ocr_texts[-1]  # 원문 보존(접두 + 원문)

    # /end 리포트 findings에도 사기_노출 반영 (flush_extract가 최신 상태 보장)
    rep = client.post(f"/api/sessions/{sid}/end").json()["report"]
    assert any(f["category"] == "사기_노출" for f in rep["findings"])
