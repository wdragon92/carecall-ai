"""애플리케이션 설정. .env → pydantic-settings 단일 로딩 지점 (config §4)."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # 실행 모드
    mock_mode: bool = True

    # CLOVA Studio (LLM)
    clova_studio_api_key: str = ""

    # AI·NAVER API (STT: CSR / TTS: CLOVA Voice Premium)
    ncp_apigw_client_id: str = ""
    ncp_apigw_client_secret: str = ""

    # CLOVA OCR
    clova_ocr_invoke_url: str = ""
    clova_ocr_secret: str = ""

    # ncloud CLI용 메인 키 (앱 런타임에는 미사용)
    ncp_access_key: str = ""
    ncp_secret_key: str = ""
    ncp_region: str = "KR"

    # 앱 파라미터
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    clova_llm_model: str = "HCX-007"
    clova_tts_voice: str = "vmikyung"
    max_upload_mb: int = 5
    session_ttl_min: int = 120
    log_level: str = "INFO"

    # ---- provider별 키 존재 판정 (real/mock 결정에 사용) ----
    def llm_available(self) -> bool:
        return bool(self.clova_studio_api_key.strip())

    def stt_available(self) -> bool:
        return bool(self.ncp_apigw_client_id.strip() and self.ncp_apigw_client_secret.strip())

    def tts_available(self) -> bool:
        return bool(self.ncp_apigw_client_id.strip() and self.ncp_apigw_client_secret.strip())

    def ocr_available(self) -> bool:
        return bool(self.clova_ocr_invoke_url.strip() and self.clova_ocr_secret.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
