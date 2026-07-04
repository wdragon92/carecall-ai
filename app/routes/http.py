"""REST 엔드포인트 (routes §6.1). 단계별로 확장."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request

router = APIRouter()
log = logging.getLogger("http")


@router.get("/health")
async def health(request: Request) -> dict:
    app = request.app
    return {
        "status": "ok",
        "mock_mode": app.state.settings.mock_mode,
        "providers": app.state.providers.modes,
        "sessions": app.state.store.count(),
    }


@router.post("/api/sessions")
async def create_session(request: Request) -> dict:
    sess = await request.app.state.store.create()
    log.info("session created: %s", sess.id)
    return {"session_id": sess.id}
