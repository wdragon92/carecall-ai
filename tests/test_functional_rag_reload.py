"""[reload] 계약 17 — /api/rag/reload 무중단 교체 후에도 즉시 검색 가능.

검증: 런타임 객체가 '실제로' 교체되고(동일 객체 재사용 아님), health의 chunks가
유지되며(senior 가드 재적용 경로 포함), 교체 직후 REST·WS 양쪽에서 접지가 정상.
"""
from test_functional_helpers import (
    GROUNDING_Q,
    handshake,
    rag_statuses,
    user_turn,
)


def test_reload_swaps_runtime_and_search_stays_hot(rag_client):
    h0 = rag_client.get("/health").json()["rag"]
    assert h0["loaded"] is True and h0["chunks"] > 0
    rt0 = rag_client.app.state.providers.rag

    r = rag_client.post("/api/rag/reload").json()
    assert r["loaded"] is True
    assert r["chunks"] == h0["chunks"]  # 같은 인덱스 재로드 → 규모 불변

    # 런타임이 실제로 새 객체로 교체됨 (핫스왑 배선)
    rt1 = rag_client.app.state.providers.rag
    assert rt1 is not None and rt1 is not rt0

    # health도 교체된 런타임 기준으로 동일 chunks (senior 가드 재적용 후 유지)
    h1 = rag_client.get("/health").json()["rag"]
    assert h1["loaded"] is True and h1["chunks"] == h0["chunks"]
    assert h1["embed_mode"] == "mock"

    # 교체 직후 REST 단건 질의 즉시 정상 (거부 아님 + 카드 조립까지)
    d = rag_client.post("/api/rag/answer", json={"question": GROUNDING_Q}).json()
    assert d["rejected"] is False
    assert d["card"] and d["card"].startswith("📌")
    assert d["sources"]

    # WS 턴에서도 접지 정상 (searching→found 해소 + 카드 버블)
    sid = rag_client.post("/api/sessions").json()["session_id"]
    with rag_client.websocket_connect(f"/ws/{sid}") as ws:
        handshake(ws)
        bubbles, seen = user_turn(ws, GROUNDING_Q)
        assert [s["status"] for s in rag_statuses(seen)] == ["searching", "found"]
        assert bubbles[-1].get("kind") == "card"
