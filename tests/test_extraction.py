def test_findings_preserved_when_llm_fails():
    """LLM 추출이 실패해도 기존 특이사항이 사라지지 않아야 한다(누적 보존)."""
    import asyncio

    from app.core import extraction
    from app.models import Finding
    from app.session import Session

    class _FailLLM:
        async def extract_json(self, messages, schema):
            raise RuntimeError("boom")

    class _P:
        llm = _FailLLM()
        mllm = _FailLLM()

    sess = Session("t")
    sess.add_message("user", "그냥 이런저런 얘기예요")  # 안전망 미매칭 발화
    sess.findings = [Finding(id="x", category="정서", content="외로움 표현", severity="보통")]

    asyncio.run(extraction._run_once(sess, _P()))

    cats = {f.category for f in sess.findings}
    assert "정서" in cats  # 기존 findings 보존


def _drain_until(ws, pred, max_msgs=90):
    seen = []
    for _ in range(max_msgs):
        m = ws.receive_json()
        seen.append(m)
        if pred(m):
            return m, seen
    return None, seen


def test_extraction_updates_findings(client):
    sid = client.post("/api/sessions").json()["session_id"]
    with client.websocket_connect(f"/ws/{sid}") as ws:
        ws.send_json({"type": "user_message", "text": "요즘 밤에 잠을 통 못 자요"})
        found, _ = _drain_until(ws, lambda m: m.get("type") == "findings_update")
        assert found is not None
        cats = {f["category"] for f in found["findings"]}
        assert "건강" in cats


def test_urgent_triggers_alert(client):
    sid = client.post("/api/sessions").json()["session_id"]
    with client.websocket_connect(f"/ws/{sid}") as ws:
        ws.send_json({"type": "user_message", "text": "이제 다 그만두고 죽고 싶어요"})
        alert, seen = _drain_until(ws, lambda m: m.get("type") == "urgent_alert")
        assert alert is not None
        # 긴급 finding도 함께 있어야 함
        fu = [m for m in seen if m.get("type") == "findings_update"][-1]
        assert any(f["category"] == "긴급" for f in fu["findings"])


def test_two_sessions_isolated(client):
    s1 = client.post("/api/sessions").json()["session_id"]
    s2 = client.post("/api/sessions").json()["session_id"]
    with client.websocket_connect(f"/ws/{s1}") as w1, client.websocket_connect(f"/ws/{s2}") as w2:
        w1.send_json({"type": "user_message", "text": "모르는 번호로 보이스피싱 문자를 받았어요"})
        f1, _ = _drain_until(w1, lambda m: m.get("type") == "findings_update")
        w2.send_json({"type": "user_message", "text": "무릎이 아파서 걷기가 힘들어요"})
        f2, _ = _drain_until(w2, lambda m: m.get("type") == "findings_update")

        cats1 = {f["category"] for f in f1["findings"]}
        cats2 = {f["category"] for f in f2["findings"]}
        assert "사기_노출" in cats1 and "사기_노출" not in cats2
        assert "건강" in cats2 and "건강" not in cats1
