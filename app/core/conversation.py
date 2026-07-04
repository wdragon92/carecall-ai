"""채팅 오케스트레이션 (conversation §8): 선인사, 사용자 턴 처리, 응답 스트리밍.
real 실패 시 mock 폴백으로 데모가 끊기지 않게 한다."""
from __future__ import annotations

import logging
from datetime import datetime

from app.core import prompts, welfare
from app.services.base import ProviderError

log = logging.getLogger("conv")


def _period_now() -> str:
    return prompts.period_of_hour(datetime.now().hour)


async def greet(sess, ws) -> None:
    text = prompts.greeting(_period_now())
    msg = sess.add_message("assistant", text, via="system")
    await ws.send_json({"type": "ai_message_start", "id": msg.id})
    await ws.send_json({"type": "ai_message_delta", "id": msg.id, "text": text})
    await ws.send_json({"type": "ai_message_end", "id": msg.id, "full_text": text})


async def handle_turn(sess, ws, providers, settings) -> None:
    await stream_reply(sess, ws, providers)
    # stage 2: 특이사항 추출 트리거 (모듈 있으면)
    try:
        from app.core.extraction import trigger_extract
    except ImportError:
        return
    await trigger_extract(sess, ws, providers)


async def stream_reply(sess, ws, providers):
    system = prompts.chat_system(welfare.get_digest())
    messages = [{"role": "system", "content": system}] + sess.history_for_llm()
    msg = sess.add_message("assistant", "")
    await ws.send_json({"type": "ai_message_start", "id": msg.id})

    parts: list[str] = []
    sent = 0

    async def run(provider) -> None:
        nonlocal sent
        async for chunk in provider.chat_stream(
            messages, temperature=0.5, top_p=0.8, max_tokens=300
        ):
            parts.append(chunk)
            sent += 1
            await ws.send_json({"type": "ai_message_delta", "id": msg.id, "text": chunk})

    try:
        await run(providers.llm)
        if sent == 0:
            raise ProviderError("empty response")
    except ProviderError as exc:
        log.warning("chat real failed (%s)", exc)
        if sent == 0:  # 아직 아무것도 못 보냈으면 mock으로 폴백
            try:
                await run(providers.mllm)
            except Exception as exc2:  # noqa: BLE001
                log.error("mock chat failed too: %s", exc2)
                fb = "죄송해요, 지금 잠시 문제가 있었어요. 다시 한 번 말씀해 주시겠어요?"
                parts.append(fb)
                await ws.send_json({"type": "ai_message_delta", "id": msg.id, "text": fb})

    full = "".join(parts).strip()
    msg.text = full
    await ws.send_json({"type": "ai_message_end", "id": msg.id, "full_text": full})
    return msg
