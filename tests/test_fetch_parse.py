"""P0: 실 API 샘플(XML) 파싱·카드 매핑 검증 — knowledge/samples/* 는 실제 응답 저장본."""
from pathlib import Path

from app.rag.cards import service_to_card
from app.rag.fetch import _parse_detail, parse_items_central, parse_items_local

SAMPLES = Path(__file__).resolve().parents[1] / "knowledge" / "samples"


def _read(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8")


def test_parse_central_list():
    rows, total = parse_items_central(_read("central_list.xml"))
    assert total == 461 and len(rows) == 3
    r = rows[0]
    assert r["servId"].startswith("WLF") and r["servNm"]
    assert "bokjiro.go.kr" in r["servDtlLink"]


def test_parse_local_list_region_fields():
    rows, total = parse_items_local(_read("local_list.xml"))
    assert total > 4000 and rows[0]["ctpvNm"]  # 시도명 → 대구·경북 필터 근거
    assert rows[0]["servId"].startswith("WLF")


def test_central_detail_to_card():
    rows, _ = parse_items_central(_read("central_list.xml"))
    detail = _parse_detail(_read("central_detail.xml"))
    merged = {**rows[0], **detail}
    card = service_to_card(merged, "central", "2026-07-06")
    assert card.serv_id == "WLF00000024" and card.source_type == "api"
    assert "서비스명: 아이돌봄서비스" in card.text
    assert "지원대상:" in card.text and "지원내용:" in card.text
    assert card.fields["_scope"] == "central"
    assert card.fields["문의처"]  # 대표문의 or 문의 리스트
    assert card.url.startswith("https://www.bokjiro.go.kr")
    assert len(card.text) < 2000  # 상세 전문(5KB+)이 카드에 통째로 들어가지 않음


def test_local_detail_to_card():
    detail = _parse_detail(_read("local_detail.xml"))
    card = service_to_card(detail, "local", "2026-07-06")
    assert card.fields["지역"].startswith("부산광역시")
    assert card.fields["_scope"] == "local"
    assert "신청방법:" in card.text  # aplyMtdCn 전문 요약
    assert card.fields["신청방법"]
