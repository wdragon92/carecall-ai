"""복지 지식 로딩 + 매칭 (welfare §10). welfare.json이 없으면 우아하게 빈 값 반환
(stage 6에서 welfare.json 작성 시 자동 활성화)."""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from app.models import WelfareItem

log = logging.getLogger("welfare")
_PATH = Path(__file__).resolve().parent.parent.parent / "knowledge" / "welfare.json"


@lru_cache
def load_items() -> list[WelfareItem]:
    if not _PATH.exists():
        return []
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        return [WelfareItem(**it) for it in data.get("items", [])]
    except Exception as exc:
        log.warning("welfare.json load failed: %s", exc)
        return []


def get_digest(max_items: int = 12) -> str:
    items = load_items()
    if not items:
        return ""
    lines = [f"- {it.이름}: {it.한줄} (대상 {it.대상}; 금액 {it.금액}; 신청 {it.신청처})" for it in items[:max_items]]
    return "\n".join(lines)


def by_ids(ids: list[str]) -> list[dict]:
    index = {it.id: it for it in load_items()}
    out: list[dict] = []
    for i in ids:
        it = index.get(i)
        if it:
            out.append({"id": it.id, "이름": it.이름, "한줄": it.한줄, "신청처": it.신청처})
    return out


async def push_welfare(sess, limit: int = 5) -> None:
    """복지 패널 갱신 단일 지점 — RAG 카드(근거·기준일 보유) 우선 + 정적 매칭 병합.
    추출/RAG 두 소스가 패널을 번갈아 덮어쓰는 깜빡임을 없앤다."""
    items: list[dict] = list(sess.welfare_cards.values())
    names = {it.get("이름") for it in items}
    for st in by_ids(sess.welfare_matched):
        if st["이름"] not in names:
            items.append(st)
            names.add(st["이름"])
    if items:
        await sess.send({"type": "welfare_update", "items": items[:limit]})


def merged_for_report(sess, limit: int = 6) -> list[dict]:
    """리포트용 병합 — 대화에서 실제 안내한 RAG 카드 먼저, 그 뒤 정적 매칭."""
    out: list[dict] = [dict(c) for c in sess.welfare_cards.values()]
    names = {o.get("이름") for o in out}
    for st in by_ids(sess.welfare_matched):
        if st["이름"] not in names:
            out.append(st)
            names.add(st["이름"])
    return out[:limit]


def match(signals: list[str], text: str, limit: int = 5) -> list[dict]:
    """추출 신호 + 사용자 발화 키워드로 복지 항목 매칭 후 관련도 상위 N개.
    키워드 매칭(구체적)을 신호 매칭(광범위)보다 높게 가중해 targeted하게 추린다."""
    items = load_items()
    if not items:
        return []
    sigset = set(signals or [])
    scored: list[tuple[int, object]] = []
    for it in items:
        kw = sum(1 for k in it.키워드 if k and k in text)
        sg = len(sigset & set(it.signals))
        score = kw * 3 + sg
        if score > 0:
            scored.append((score, it))
    scored.sort(key=lambda x: -x[0])
    return [
        {"id": it.id, "이름": it.이름, "한줄": it.한줄, "신청처": it.신청처}
        for _, it in scored[:limit]
    ]
