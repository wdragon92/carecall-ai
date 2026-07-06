"""어르신 적합성 필터(senior)와 카드 링크 폴백 체인, 제안 수락 흐름의 결정적 검증."""
from types import SimpleNamespace

from app.core import welfare
from app.core.conversation import _accepts_offer, _offered_service, _situation_memo
from app.rag.cards import BOKJIRO_HOME, card_url, fixture_cards
from app.rag.schema import DocChunk
from app.rag.senior import chunk_senior_relevant, senior_relevant


# ---- 연령 필터 ----
def test_senior_keeps_elderly_and_universal():
    assert senior_relevant("기초연금", "만 65세 이상 소득 하위 70%")
    assert senior_relevant("노인맞춤돌봄서비스", "")
    assert senior_relevant("긴급복지 생계지원", "갑작스러운 위기로 생계가 곤란한 가구")  # 전연령 유지
    assert senior_relevant("조손가족 지원", "조손가족의 아동 양육 지원")  # 조부모 양육 = 어르신 시나리오


def test_senior_drops_youth_and_worker():
    assert not senior_relevant("청년 월세 한시 특별지원", "만 19세~34세 청년")
    assert not senior_relevant("주거안정 월세대출", "무주택 세대주")  # 금융상품(대출)
    assert not senior_relevant("근로·자녀장려금", "일하는 저소득 가구")
    assert not senior_relevant("자활근로(기초, 차상위)", "근로능력 있는 수급자")


def test_senior_hard_excludes_sanjae_over_yoyang():
    # '요양급여'의 요양 표지에 걸려 살아남던 산재 제도 — 하드 배제가 이긴다
    assert not senior_relevant("요양급여(보조기)-산재보험급여", "산재근로자를 지원합니다")
    assert not senior_relevant("산재근로자 사회심리재활지원", "요양하고 있는 산재노동자")


def test_senior_age_cap_in_target():
    assert not senior_relevant("어떤 지원", "만 39세 이하 대상")
    assert senior_relevant("어떤 지원", "만 65세 이상 대상")


def test_chunk_filter_defaults_keep():
    assert chunk_senior_relevant(DocChunk(text="x", source="s", fields=None))


# ---- 링크 폴백 체인 ----
def test_card_url_chain():
    assert card_url(DocChunk(text="", source="", url="https://a.b/c")) == "https://a.b/c"
    wlf = card_url(DocChunk(text="", source="", serv_id="WLF00000102"))
    assert wlf.startswith("https://www.bokjiro.go.kr") and "WLF00000102" in wlf
    assert card_url(DocChunk(text="", source="", serv_id="fixture-x")) == BOKJIRO_HOME


def test_fixture_cards_carry_links():
    for c in fixture_cards():
        assert c.url.startswith("https://www.bokjiro.go.kr"), c.serv_id


def test_panel_items_carry_links():
    items = welfare.by_ids(["basic-pension", "care-service"])
    assert len(items) == 2
    for it in items:
        assert it["url"].startswith("https://www.bokjiro.go.kr")
    matched = welfare.match([], "무릎이 아파서 장 보러 가기가 힘들어요 돌봄")
    assert all(m["url"] for m in matched)


# ---- 제안 수락 흐름 (HCX-007 감지 → 보미 제안 → "응" → 근거 안내) ----
def _sess(ai_text: str, matched=None, cards=None):
    return SimpleNamespace(
        messages=[SimpleNamespace(role="assistant", text=ai_text)],
        welfare_matched=list(matched or []),
        welfare_cards=dict(cards or {}),
        slots={},
        findings=[],
    )


def test_accepts_offer():
    assert _accepts_offer("응")
    assert _accepts_offer("그래 알려줘")
    assert _accepts_offer("궁금하네")
    assert not _accepts_offer("아니 괜찮아")
    assert not _accepts_offer("우리 손주가 어제 왔다 갔어")  # 길이 초과·무관 발화


def test_offered_service_from_last_ai_message():
    sess = _sess("어르신, 혹시 '노인맞춤돌봄서비스'라고 들어보셨어요? 도움되는 제도가 있는데 알려드릴까요?")
    assert _offered_service(sess) == "노인맞춤돌봄서비스"
    # 제안 문형이 아니면 None
    assert _offered_service(_sess("오늘 날씨가 참 좋네요.")) is None


def test_situation_memo_mentions_offer_hint():
    sess = _sess("네, 듣고 있어요.", matched=["care-service"])
    memo = _situation_memo(sess)
    assert "노인맞춤돌봄서비스" in memo and "알려드릴까요" in memo
    # 이미 안내한 복지는 제안 힌트에서 빠진다
    sess2 = _sess("네.", matched=["care-service"],
                  cards={"x": {"이름": "노인맞춤돌봄서비스"}})
    assert "제안 힌트" not in _situation_memo(sess2)
