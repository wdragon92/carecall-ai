"""WebSocket 엔드포인트 (routes §6.2): 연결→선인사→사용자 턴 루프."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core import conversation

router = APIRouter()
log = logging.getLogger("ws")


@router.websocket("/ws/{session_id}")
async def ws_endpoint(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    store = websocket.app.state.store
    providers = websocket.app.state.providers
    settings = websocket.app.state.settings

    sess = store.get(session_id)
    if sess is None:
        await websocket.send_json(
            {"type": "error", "code": "no_session", "message": "세션을 찾을 수 없어요. 새로고침 해주세요."}
        )
        await websocket.close()
        return

    sess.ws = websocket
    await sess.send({"type": "session_ready", "session_id": session_id, "providers": providers.modes})
    if not sess.messages:  # 재연결 시 인사 중복 방지
        # 접속하자마자 말을 걸면 브라우저 오디오 정책(제스처 전 자동재생 차단)에 첫 인사
        # 음성이 먹히기 쉽다 — 화면이 자리 잡고 첫 터치가 들어올 시간을 준다.
        await asyncio.sleep(max(0.0, settings.greet_delay_seconds))
        await conversation.greet(sess)

    try:
        while True:
            data = await websocket.receive_json()
            mtype = data.get("type")
            if mtype == "user_message":
                text = (data.get("text") or "").strip()
                if not text:
                    continue
                sess.add_message("user", text, via=data.get("via", "text"))
                await conversation.handle_turn(sess, providers, settings)
    except WebSocketDisconnect:
        if sess.ws is websocket:
            sess.ws = None
        log.info("ws disconnected: %s", session_id)
    except Exception as exc:  # noqa: BLE001 — 세션은 절대 죽이지 않음
        log.exception("ws error: %s", exc)
        await sess.send({"type": "error", "code": "internal", "message": "일시적인 오류가 있었어요."})
