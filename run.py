"""로컬 실행 편의 스크립트: python run.py → http://127.0.0.1:8000"""
from app.config import get_settings

if __name__ == "__main__":
    import uvicorn

    s = get_settings()
    uvicorn.run("app.main:app", host=s.app_host, port=s.app_port, reload=False)
