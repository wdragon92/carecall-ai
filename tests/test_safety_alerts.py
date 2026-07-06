"""안전망 연계 분리: 건강 응급→119 전용, 자살예방 109는 심리 신호 전용."""
from app.core import safety


def test_breathing_difficulty_detected_as_medical_emergency():
    """'숨이 잘 안 쉬어져' 변형이 안전망에 걸려 즉시 119 배너."""
    for utter in ["숨이 잘 안 쉬어져", "숨쉬기가 힘들어", "숨을 잘 못 쉬겠어", "숨이 막혀"]:
        kinds = {d["_kind"] for d in safety.scan(utter)}
        assert "medical_emergency" in kinds, utter
        level, msg = safety.alert(kinds)
        assert level == "emergency"
        assert "119" in msg and "109" not in msg  # 몸 응급엔 109 미노출


def test_negation_not_matched():
    assert safety.scan("숨이 잘 안 쉬어지진 않아") == [] or all(
        d["_kind"] != "medical_emergency" for d in safety.scan("숨이 잘 안 쉬어지진 않아")
    )


def test_alert_split_by_llm_flags():
    # LLM이 건강 위급만 잡음 → 119 전용 문구
    level, msg = safety.alert(set(), {"medical"})
    assert level == "emergency" and "119" in msg and "109" not in msg
    # LLM이 심리 위급 → 109 포함 문구
    level, msg = safety.alert(set(), {"psych"})
    assert level == "emergency" and "109" in msg
    # 둘 다면 심리(109 포함) 우선 — 사람 연결이 가장 급한 케이스
    level, msg = safety.alert(set(), {"medical", "psych"})
    assert "109" in msg


def test_suicide_rules_keep_109():
    kinds = {d["_kind"] for d in safety.scan("요즘은 그만 살고 싶다는 생각이 들어")}
    level, msg = safety.alert(kinds)
    assert level in ("warning", "emergency") and "109" in msg


def test_medical_soon_mentions_guardian_not_109():
    kinds = {d["_kind"] for d in safety.scan("조금만 걸어도 숨이 차")}
    level, msg = safety.alert(kinds)
    assert level == "warning" and "109" not in msg and "보호자" in msg
