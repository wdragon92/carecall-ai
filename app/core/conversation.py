"""채팅/OCR 오케스트레이션 (conversation §8). real 실패 시 mock 폴백.
모든 WS 전송은 sess.send()로 직렬화된다."""
from __future__ import annotations

import logging
from datetime import datetime

from app.core import prompts, welfare
from app.services.base import ProviderError

log = logging.getLogger("conv")


def _period_now() -> str:
    return prompts.period_of_hour(datetime.now().hour)


async def _stream(sess, providers, messages, max_tokens: int = 350) -> str:
    """AI 응답을 스트리밍하며 말풍선으로 push. real 실패 시 mock 폴백."""
    msg = sess.add_message("assistant", "")
    await sess.send({"type": "ai_message_start", "id": msg.id})
    parts: list[str] = []
    sent = 0

    async def run(provider) -> None:
        nonlocal sent
        async for chunk in provider.chat_stream(
            messages, temperature=0.5, top_p=0.8, max_tokens=max_tokens
        ):
            parts.append(chunk)
            sent += 1
            await sess.send({"type": "ai_message_delta", "id": msg.id, "text": chunk})

    try:
        await run(providers.llm)
        if sent == 0:
            raise ProviderError("empty response")
    except ProviderError as exc:
        log.warning("stream real failed (%s)", exc)
        if sent == 0:
            try:
                await run(providers.mllm)
            except Exception as exc2:  # noqa: BLE001
                log.error("mock stream failed too: %s", exc2)
                fb = "죄송해요, 지금 잠시 문제가 있었어요. 다시 한 번 말씀해 주시겠어요?"
                parts.append(fb)
                await sess.send({"type": "ai_message_delta", "id": msg.id, "text": fb})

    full = "".join(parts).strip()
    msg.text = full
    await sess.send({"type": "ai_message_end", "id": msg.id, "full_text": full})
    return full


def _spawn_extract(sess, providers) -> None:
    try:
        from app.core.extraction import trigger_extract
    except ImportError:
        return
    sess.spawn(trigger_extract(sess, providers))


async def greet(sess) -> None:
    text = prompts.greeting(_period_now())
    msg = sess.add_message("assistant", text, via="system")
    await sess.send({"type": "ai_message_start", "id": msg.id})
    await sess.send({"type": "ai_message_delta", "id": msg.id, "text": text})
    await sess.send({"type": "ai_message_end", "id": msg.id, "full_text": text})


async def handle_turn(sess, providers, settings) -> None:
    system = prompts.chat_system(welfare.get_digest())
    messages = [{"role": "system", "content": system}] + sess.history_for_llm()
    await _stream(sess, providers, messages, max_tokens=300)
    _spawn_extract(sess, providers)  # 비동기 추출


async def handle_image(sess, providers, image_bytes: bytes, fmt: str, name: str, upload_id: str) -> None:
    """이미지 → OCR → 쉬운 말 설명 + 사기 판별 → 특이사항 반영. 이미지 바이트는 즉시 폐기."""
    await sess.send({"type": "ocr_status", "upload_id": upload_id, "status": "processing"})
    try:
        ocr_text = await providers.ocr.extract_text(image_bytes, fmt, name)
    except ProviderError as exc:
        log.warning("ocr real failed (%s) → mock", exc)
        try:
            ocr_text = await providers.mocr.extract_text(image_bytes, fmt, name)
        except Exception as exc2:  # noqa: BLE001
            log.error("ocr mock failed: %s", exc2)
            await sess.send({"type": "ocr_status", "upload_id": upload_id, "status": "error"})
            await sess.send({"type": "error", "code": "ocr", "message": "사진에서 글자를 읽지 못했어요. 다시 찍어 주시겠어요?"})
            return
    finally:
        image_bytes = b""  # 디스크 저장 안 함, 참조도 폐기

    ocr_text = (ocr_text or "").strip()
    await sess.send({"type": "ocr_status", "upload_id": upload_id, "status": "done"})

    if not ocr_text:
        await _stream(
            sess, providers,
            [
                {"role": "system", "content": "어르신이 사진을 보내셨지만 글자를 읽지 못했어요. 존댓말로 2문장 이내로, 더 밝은 곳에서 또렷하게 다시 찍어달라고 부드럽게 안내하세요."},
                {"role": "user", "content": "(인식된 글자가 없습니다)"},
            ],
            max_tokens=150,
        )
        return

    sess.ocr_texts.append(ocr_text)
    messages = [
        {"role": "system", "content": prompts.OCR_EXPLAIN + ocr_text},
        {"role": "user", "content": "이 내용을 쉽게 설명해 주세요."},
    ]
    await _stream(sess, providers, messages, max_tokens=500)
    _spawn_extract(sess, providers)  # OCR 내용 반영해 특이사항 갱신
