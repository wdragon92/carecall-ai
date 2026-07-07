"""[턴 오케스트레이션] 계약 1~3 — WS 메시지 배선·순서·횟수 (화이트박스, 전부 목).

계약 1: 접지 턴은 rag_status 2단(searching→found)·ai_typing on/off 각 1회·ai_turn 정확히 1회.
        카드 버블은 bubbles의 마지막 요소.
        ※ 실제 배선: searching은 검색(생성 이전) 시점이라 ai_typing(on)보다 먼저,
          found는 카드 확정(생성 이후) 시점이라 typing(on)과 typing(off) 사이에 도착한다.
계약 2: 게이트 미달 경로엔 칩 자체가 없다 — 거부 질의·백채널·임베딩 장애 어느 경로에서도
        rag_status가 전송되지 않는다 (소음 없는 폴백). 게이트를 통과했지만 카드가 안 붙는
        턴(부정 답변·이름 불일치)은 searching→no_match로 해소된다 — '찾았어요' 칩과
        '없어요' 답변이 모순되는 실측 사례("매월 100만원씩 주는 지원 있어?") 방지.
계약 3: 스크리닝(기초연금) 턴은 ai_typing·rag_status 미전송 + LLM chat 미호출
        (슬롯 extract_json만) — 그래도 턴 끝 추출은 스폰되어 findings_update가 온다.
계약 1-보강: 송금 정황 턴의 결정적 행동 카드(action_card)도 같은 턴 '마지막' 버블 —
        112·은행 지급정지·1332를 LLM 변주와 무관하게 코드가 보장한다.
"""
from test_functional_helpers import (
    ALIEN_Q,
    GROUNDING_Q,
    BoomEmbed,
    NegationChatLLM,
    card_bubbles,
    drain_until,
    handshake,
    install_llm_spy,
    is_type,
    rag_statuses,
    sess_of,
    typing_flags,
    user_turn,
)

from app.core import prompts_analysis
from app.rag import rules


# ---- 계약 1: 접지 턴 메시지 순서·횟수 + 카드 버블 위치 ----
def test_grounded_turn_message_order_and_single_ai_turn(rag_client):
    sid = rag_client.post("/api/sessions").json()["session_id"]
    with rag_client.websocket_connect(f"/ws/{sid}") as ws:
        handshake(ws)

        # 첫 사용자 턴(이전 턴의 비동기 추출 없음) → 윈도가 이 턴의 전송만 담는다
        bubbles, seen = user_turn(ws, GROUNDING_Q)
        types = [m["type"] for m in seen]

        # ai_turn 정확히 1회, 윈도의 마지막
        assert types.count("ai_turn") == 1 and types[-1] == "ai_turn"

        # 타이핑 인디케이터 on→off 정확히 한 쌍
        assert typing_flags(seen) == [True, False]

        # 접지 칩 2단: searching(검색 시점) → found(카드 확정 시점, 근거 메타 포함)
        rs = rag_statuses(seen)
        assert [s["status"] for s in rs] == ["searching", "found"]
        assert rs[1]["hits"] >= 1 and rs[1]["sources"]

        # 전체 순서: searching < typing(on) < found < typing(off) < ai_turn
        i_on = types.index("ai_typing")
        i_off = len(types) - 1 - types[::-1].index("ai_typing")
        i_s = types.index("rag_status")
        i_f = len(types) - 1 - types[::-1].index("rag_status")
        assert i_s < i_on < i_f < i_off < types.index("ai_turn")

        # 카드 버블은 항상 마지막 요소, 그리고 딱 1장
        assert len(bubbles) >= 2, bubbles
        assert bubbles[-1].get("kind") == "card"
        assert len(card_bubbles(bubbles)) == 1

        # 턴 이후엔 비동기 추출 산출물만 — 두 번째 ai_turn/typing/rag_status가 없어야 '정확히 1회'
        _, post = drain_until(ws, is_type("findings_update"))
        assert all(
            m["type"] in ("findings_update", "welfare_update", "urgent_alert") for m in post
        ), [m["type"] for m in post]


# ---- 계약 2: 어떤 경로에서도 rag_status는 found 외 미전송 ----
def test_no_rag_status_on_reject_backchannel_and_embed_failure(rag_client):
    sid = rag_client.post("/api/sessions").json()["session_id"]
    with rag_client.websocket_connect(f"/ws/{sid}") as ws:
        handshake(ws)

        # (a) 거부 질의 턴 — 게이트 미달이어도 'searching'/'none' 칩 없이 조용히 수다 경로
        bubbles, seen = user_turn(ws, ALIEN_Q)
        assert rag_statuses(seen) == []
        assert card_bubbles(bubbles) == []

        # (b) 백채널 턴 — 검색 자체를 타지 않는다
        bubbles, seen = user_turn(ws, "그러게")
        assert rag_statuses(seen) == []
        assert card_bubbles(bubbles) == []

        # (c) 임베딩 장애 — 접지됐을 질의도 조용히 폴백, 턴은 살아서 ai_turn 도착
        providers = rag_client.app.state.providers
        providers.embed = BoomEmbed()
        bubbles, seen = user_turn(ws, GROUNDING_Q)
        assert rag_statuses(seen) == []
        assert card_bubbles(bubbles) == []
        assert bubbles and bubbles[0]["text"].strip()  # 수다 응답은 정상 생성


# ---- 계약 2-보강: 게이트 통과 + 부정 답변(소문성 질문) → searching이 no_match로 해소 ----
def test_rumor_turn_resolves_searching_to_no_match(rag_client):
    """실측 사례("매월 100만원씩 지원해주는 정부 지원 있어?"): 어휘·의미 우연으로 게이트는
    넘지만 LLM이 정직하게 '확인되지 않는다'고 답해 카드가 빠지는 턴(적대 방어) —
    '찾았어요' 칩이 남아 '없어요' 답변과 모순되지 않아야 한다."""
    p = rag_client.app.state.providers
    neg = NegationChatLLM(p.llm)
    p.llm = neg
    p.mllm = neg
    sid = rag_client.post("/api/sessions").json()["session_id"]
    with rag_client.websocket_connect(f"/ws/{sid}") as ws:
        handshake(ws)
        bubbles, seen = user_turn(ws, GROUNDING_Q)  # 목 인덱스에서 게이트 통과가 보장된 질의
        assert [s["status"] for s in rag_statuses(seen)] == ["searching", "no_match"]
        assert card_bubbles(bubbles) == []  # 무관 카드 없음 (부정 게이트 — answer.pick_card)
        assert any("확인되지 않" in b["text"] for b in bubbles)  # 정직한 부정 답변은 그대로
        # T2 금액 치환도 카드 유무와 일치 — 카드 없는 턴이 '화면 카드'를 가리키면 안 된다
        assert all("화면 카드" not in b["text"] for b in bubbles)
        assert any("말씀하신 금액" in b["text"] for b in bubbles)


# ---- 계약 3: 스크리닝 턴 — typing/rag_status 없음, chat 미호출, 추출은 스폰됨 ----
def test_screening_turn_skips_typing_and_chat_but_spawns_extract(rag_client):
    spy = install_llm_spy(rag_client)
    sid = rag_client.post("/api/sessions").json()["session_id"]
    with rag_client.websocket_connect(f"/ws/{sid}") as ws:
        handshake(ws)  # 선인사는 고정문 — chat 미사용

        ws.send_json({"type": "user_message", "text": "기초연금 나도 받을 수 있나?"})
        turn, seen = drain_until(ws, is_type("ai_turn"))

        # 첫 턴이라 이 윈도는 스크리닝 턴의 전송만: ai_turn 단독 (typing·rag_status 없음)
        assert [m["type"] for m in seen] == ["ai_turn"]
        assert "연세" in turn["bubbles"][0]["text"]  # 나이 되묻기 멘트(룰엔진 산출)

        # LLM 역할 분리: chat은 한 번도 안 불리고, 슬롯 추출(extract_json)만 이 턴에 쓰였다
        assert spy.chat_calls == []
        systems = spy.extract_systems()
        assert systems and systems[0] == rules.SLOT_SYSTEM

        # 그래도 턴 끝 특이사항 추출은 스폰된다 → findings_update 도착 + EXTRACT 프롬프트 호출
        _, post = drain_until(ws, is_type("findings_update"))
        assert all(m["type"] != "ai_typing" and m["type"] != "rag_status" for m in post)
        assert prompts_analysis.EXTRACT_SYSTEM in spy.extract_systems()
        assert spy.chat_calls == []  # 추출 파이프라인도 chat은 쓰지 않는다


# ---- 계약 1-보강: 송금 정황의 결정적 행동 카드가 같은 턴 마지막 버블 ----
def test_fraud_sent_turn_appends_action_card_last(rag_client):
    sid = rag_client.post("/api/sessions").json()["session_id"]
    with rag_client.websocket_connect(f"/ws/{sid}") as ws:
        handshake(ws)

        bubbles, _ = user_turn(ws, "모르는 사람이 시켜서 은행에서 돈을 보냈어. 사기당한 것 같아")
        last = bubbles[-1]
        assert last.get("kind") == "card", bubbles  # RAG 카드가 함께 붙어도 행동 카드가 맨 뒤
        for tok in ("112", "지급정지", "1332"):
            assert tok in last["text"], last["text"]

        # 화이트박스: 행동 카드도 tts_text(짧은 안내문)를 갖는 card 메시지로 저장됨
        sess = sess_of(rag_client, sid)
        msg = next(m for m in reversed(sess.messages) if m.role == "assistant")
        assert msg.kind == "card" and msg.id == last["id"]
        assert msg.tts_text and "지급정지" in msg.tts_text
