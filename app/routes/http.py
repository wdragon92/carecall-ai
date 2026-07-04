"""REST 엔드포인트 (routes §6.1). 단계별로 확장."""
from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from app.core.conversation import handle_image

router = APIRouter()
log = logging.getLogger("http")

_EXT = ("jpg", "jpeg", "png", "pdf", "tif", "tiff")


def _fmt_from(filename: str | None, content_type: str | None) -> str:
    name = (filename or "").lower()
    for ext in _EXT:
        if name.endswith("." + ext):
            return "jpg" if ext == "jpeg" else ext
    ct = (content_type or "").lower()
    if "png" in ct:
        return "png"
    if "pdf" in ct:
        return "pdf"
    return "jpg"


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


@router.post("/api/sessions/{sid}/image")
async def upload_image(sid: str, request: Request, file: UploadFile = File(...)):
    store = request.app.state.store
    providers = request.app.state.providers
    settings = request.app.state.settings

    sess = store.get(sid)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"file too large (>{settings.max_upload_mb}MB)")

    fmt = _fmt_from(file.filename, file.content_type)
    upload_id = secrets.token_hex(6)
    # OCR→설명→추출은 비동기. 결과는 WS로 push. 이미지 바이트는 처리 후 폐기.
    sess.spawn(handle_image(sess, providers, data, fmt, file.filename or "doc", upload_id))
    return JSONResponse({"upload_id": upload_id}, status_code=202)
