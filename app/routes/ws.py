"""WebSocket 엔드포인트 (routes §6.2). stage 0: 연결/세션검증/선인사 자리만.
채팅 오케스트레이션은 stage 1에서 확장."""
from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()
log = logging.getLogger("ws")


@router.websocket("/ws/{session_id}")
async def ws_endpoint(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    store = websocket.app.state.store
    providers = websocket.app.state.providers
    sess = store.get(session_id)
    if sess is None:
        await websocket.send_json(
            {"type": "error", "code": "no_session", "message": "세션을 찾을 수 없어요. 새로고침 해주세요."}
        )
        await websocket.close()
        return

    sess.ws = websocket
    await websocket.send_json(
        {"type": "session_ready", "session_id": session_id, "providers": providers.modes}
    )

    try:
        while True:
            await websocket.receive_json()  # stage 1에서 user_message 처리
    except WebSocketDisconnect:
        if sess.ws is websocket:
            sess.ws = None
        log.info("ws disconnected: %s", session_id)
