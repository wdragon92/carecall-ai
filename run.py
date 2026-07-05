"""로컬 실행 편의 스크립트: python run.py → http://127.0.0.1:8080
개발 중 코드 변경 자동 반영을 원하면: APP_RELOAD=true python run.py"""
import os

from app.config import get_settings

if __name__ == "__main__":
    import uvicorn

    s = get_settings()
    reload = os.getenv("APP_RELOAD", "").strip().lower() in ("1", "true", "yes", "on")
    uvicorn.run("app.main:app", host=s.app_host, port=s.app_port, reload=reload)
