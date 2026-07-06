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
    # 가족상담 도메인은 '조손' 한 단어로 통과 금지 (온가족보듬사업 실사례)
    assert not senior_relevant("온가족보듬사업", "한부모‧조손가족, 1인가구, 다문화가족 등 위기가족")
    assert not senior_relevant("조손가족 지원", "조손가족의 아동 양육 지원")  # 가족 도메인으로 분류


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


def test_senior_drops_other_target_domains():
    """실사례: '밥을 잘 못 먹어' → 문경시 재가장애인 밑반찬지원 매칭 사고.
    장애인·임산부·다문화 등 전용 대상 도메인은 노인 표지 없으면 배제."""
    assert not senior_relevant("재가장애인 밑반찬지원사업", "재가장애인을 지원합니다")
    assert not senior_relevant("임산부 영양제 지원", "")
    assert not senior_relevant("다문화가족 정착 지원", "결혼이민자")
    # 노인·장애인 겸용은 유지(노인 표지 우선)
    assert senior_relevant("독거노인·장애인 응급안전안심서비스", "")
    # 전연령 저소득은 유지
    assert senior_relevant("저소득층 밑반찬 지원사업", "저소득 가구")


def test_senior_tag_category_exclusion():
    """XML 대상특성 태그(관련어)에 전용 카테고리만 있으면 배제 — 단 검색 키워드의
    일반어('보증금')는 태그 배제에 걸리면 안 됨(주거급여 오배제 실사례)."""
    disabled = DocChunk(
        text="서비스명: 이동지원 바우처\n지원대상: 등록자\n관련어: 장애인",
        source="s", fields={"서비스명": "이동지원 바우처", "지원대상": "등록자"},
    )
    assert not chunk_senior_relevant(disabled)
    housing = DocChunk(
        text="서비스명: 주거급여\n지원대상: 중위소득 48% 이하 가구\n관련어: 월세 집세 전세 주거 수리 보증금",
        source="s", fields={"서비스명": "주거급여", "지원대상": "중위소득 48% 이하 가구"},
    )
    assert chunk_senior_relevant(housing)
    tagged_senior = DocChunk(
        text="서비스명: 무릎수술 지원\n지원대상: 등록자\n관련어: 노년 장애인",
        source="s", fields={"서비스명": "무릎수술 지원", "지원대상": "등록자"},
    )
    assert chunk_senior_relevant(tagged_senior)  # 노년 공존 태그는 유지


def test_region_gate_default_daegu():
    from app.rag.search import region_ok

    mun_gyeong = DocChunk(text="", source="s", fields={"지역": "경상북도 문경시"})
    daegu = DocChunk(text="", source="s", fields={"지역": "대구광역시 달서구"})
    national = DocChunk(text="", source="s", fields={})
    q = "요즘 밥을 잘 못 먹어"
    assert not region_ok(mun_gyeong, "대구", q)  # 타 지역 지자체 — 기본 차단
    assert region_ok(daegu, "대구", q)
    assert region_ok(national, "대구", q)  # 중앙부처(전국)
    assert region_ok(mun_gyeong, "대구", "문경 사는 동생 얘긴데")  # 지역 직접 언급 시 허용
    assert region_ok(mun_gyeong, "대구", "경북에도 이런 게 있나")  # 광역 약칭


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
