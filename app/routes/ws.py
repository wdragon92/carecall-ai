"""WebSocket 엔드포인트 (routes §6.2): 연결→선인사→사용자 턴 루프."""
from __future__ import annotations

import asyncio
import logging
import unicodedata

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

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
    # 재접속(새 연결): 보낸 배너 dedup 집합을 초기화 — 새 화면에는 위기 배너가
    # 다시 뜨도록(중복억제로 재접속 시 배너가 영구 소실되던 문제 방지).
    sess.sent_alerts = set()
    await sess.send({"type": "session_ready", "session_id": session_id, "providers": providers.modes})
    if not sess.messages:  # 재연결 시 인사 중복 방지
        # 접속하자마자 말을 걸면 브라우저 오디오 정책(제스처 전 자동재생 차단)에 첫 인사
        # 음성이 먹히기 쉽다 — 화면이 자리 잡고 첫 터치가 들어올 시간을 준다.
        await asyncio.sleep(max(0.0, settings.greet_delay_seconds))
        await conversation.greet(sess)

    try:
        while True:
            # 프레임 수신을 루프 '안'에서 방어 — 잘못된/비-JSON/비-dict 프레임 하나가
            # 턴 루프를 영구 종료시키지 않게 한다. 끊김(WebSocketDisconnect)만 break.
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                raise
            except Exception as exc:  # noqa: BLE001
                # 살아있는 소켓의 '잘못된 프레임'(비-JSON 등)만 무시하고 계속한다.
                # 소켓이 이미 끊김/종료 중이면 재수신해도 같은 예외가 영구 반복되어
                # 이벤트 루프를 점유하는 busy-loop이 된다(실측: receive가 WebSocketDisconnect가
                # 아니라 RuntimeError('WebSocket is not connected')로 나는 비정상 종료 경로).
                # 따라서 CONNECTED가 아니면 잘못된 프레임이 아니라 종료로 보고 루프를 끝낸다.
                if websocket.client_state != WebSocketState.CONNECTED:
                    log.info("ws recv on %s → close: %s", websocket.client_state.name, session_id)
                    break
                log.warning("ws bad frame ignored: %s", exc)
                continue
            if not isinstance(data, dict):  # 배열·문자열 등 비-dict 프레임 방어
                log.warning("ws non-dict frame ignored: %s", type(data).__name__)
                continue
            mtype = data.get("type")
            if mtype == "user_message":
                # ingress NFC 정규화 — 조합형/완성형 혼입을 통일(안전망·복지매칭 우회 방지).
                text = unicodedata.normalize("NFC", data.get("text") or "").strip()
                if not text:
                    continue
                sess.add_message("user", text, via=data.get("via", "text"))
                store.bump(session_id)  # 활동 시 LRU 갱신 — 대화 중 활성 세션 축출 방지
                try:
                    await conversation.handle_turn(sess, providers, settings)
                except Exception as exc:  # noqa: BLE001 — 한 턴 실패가 루프를 죽이지 않음
                    log.exception("ws turn error: %s", exc)
                    await sess.send(
                        {"type": "error", "code": "internal", "message": "일시적인 오류가 있었어요."}
                    )
    except WebSocketDisconnect:
        log.info("ws disconnected: %s", session_id)
    except Exception as exc:  # noqa: BLE001 — 최후 안전망(세션은 절대 죽이지 않음)
        log.exception("ws error: %s", exc)
        try:
            await sess.send({"type": "error", "code": "internal", "message": "일시적인 오류가 있었어요."})
        except Exception:  # noqa: BLE001 — 이미 끊긴 소켓엔 전송 불가, 무시
            pass
    finally:
        # 정상 끊김·busy-loop 차단 break·예외 어느 경로로 빠져나오든 세션의 소켓 참조를
        # 반드시 해제(다음 재접속이 stale 소켓으로 send하지 않도록).
        if sess.ws is websocket:
            sess.ws = None
