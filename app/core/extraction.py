"""특이사항 추출 파이프라인 (extraction §8.3). 비동기·코얼레싱.
LLM 추출 결과에 결정적 안전망(safety)을 병합해, 위험신호를 놓치지 않는다.
결과는 findings_update / urgent_alert(level) / welfare_update 로 push."""
from __future__ import annotations

import logging

from app.core import prompts_analysis, safety, welfare
from app.models import Finding
from app.session import finding_id

log = logging.getLogger("extract")


def _dump(f: Finding) -> dict:
    return {
        "id": f.id,
        "category": f.category,
        "content": f.content,
        "severity": f.severity,
        "needs_human": f.needs_human,
    }


def _parse_findings(raw_list) -> list[Finding]:
    out: list[Finding] = []
    for item in raw_list or []:
        try:
            f = Finding.model_validate(item)  # 한글 키(alias) 흡수, 여분 키(_kind)는 무시
        except Exception:  # noqa: BLE001
            continue
        f.id = finding_id(f.category, f.content)
        out.append(f)
    return out


def _merge(safety_findings: list[Finding], llm_findings: list[Finding]) -> list[Finding]:
    # 안전망(위험신호) 먼저, 그 뒤 LLM. id 기준 중복 제거.
    merged: list[Finding] = []
    seen: set[str] = set()
    for f in safety_findings + llm_findings:
        if f.id in seen:
            continue
        seen.add(f.id)
        merged.append(f)
    return merged


async def trigger_extract(sess, providers) -> None:
    """코얼레싱: 실행 중이면 dirty만 세팅. 종료 시 dirty면 1회 더."""
    if sess.extract_lock.locked():
        sess.extract_dirty = True
        return
    async with sess.extract_lock:
        await _run_once(sess, providers)
        while sess.extract_dirty:
            sess.extract_dirty = False
            await _run_once(sess, providers)


async def _run_once(sess, providers) -> None:
    transcript = sess.user_transcript()
    if not transcript.strip():
        return

    # 1) 즉시: 결정적 안전망 먼저 (느린 LLM보다 앞서 위험신호를 바로 표시)
    safety_raw = safety.scan(transcript)
    kinds = {d["_kind"] for d in safety_raw}
    safety_findings = _parse_findings(safety_raw)
    if safety_findings:
        sess.findings = _merge(safety_findings, sess.findings)
        await sess.send({"type": "findings_update", "findings": [_dump(f) for f in sess.findings]})
    level, message = safety.alert(kinds)
    if level:
        await sess.send({"type": "urgent_alert", "level": level, "message": message})

    # 2) LLM 추출 (느림) → 안전망과 병합해 갱신
    messages = [
        {"role": "system", "content": prompts_analysis.EXTRACT_SYSTEM},
        {"role": "user", "content": transcript},
    ]
    data: dict = {}
    llm_ok = False
    try:
        data = await providers.llm.extract_json(messages, prompts_analysis.EXTRACT_SCHEMA)
        llm_ok = True
    except Exception as exc:  # noqa: BLE001
        log.warning("extract real failed (%s) → mock", exc)
        try:
            data = await providers.mllm.extract_json(messages, prompts_analysis.EXTRACT_SCHEMA)
            llm_ok = True
        except Exception as exc2:  # noqa: BLE001
            log.error("extract mock failed: %s", exc2)
            data = {}

    llm_findings = _parse_findings(data.get("findings") if isinstance(data, dict) else None)
    # LLM 성공 → 안전망+LLM 으로 갱신 / 실패 → 기존 findings 보존(안전망만 반영, 누적 유지)
    findings = _merge(safety_findings, llm_findings) if llm_ok else _merge(safety_findings, sess.findings)
    sess.findings = findings
    await sess.send({"type": "findings_update", "findings": [_dump(f) for f in findings]})

    # 경보 재평가 — LLM이 새 위험을 잡았으면 상향(하향은 안 함).
    # 연계 분리: 건강 위급 → 119 문구 / 심리(긴급·정서) 위급 → 109 문구 (109는 심리 전용)
    llm_flags: set[str] = set()
    for f in llm_findings:
        serious = f.category == "긴급" or (f.severity == "높음" and f.needs_human)
        if not serious:
            continue
        if f.category == "건강":
            llm_flags.add("medical")
        else:
            llm_flags.add("psych")
    level2, message2 = safety.alert(kinds, llm_flags)
    if level2 and level2 != level:
        await sess.send({"type": "urgent_alert", "level": level2, "message": message2})

    # 복지 매칭 — 패널 전송은 push_welfare 단일 지점(RAG 카드와 병합)
    signals = data.get("welfare_signals") if isinstance(data, dict) else None
    matched = welfare.match(signals or [], transcript)
    if matched:
        sess.welfare_matched = [m["id"] for m in matched]
    if matched or sess.welfare_cards:
        await welfare.push_welfare(sess)
