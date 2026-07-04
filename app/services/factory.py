"""키 유무·MOCK_MODE를 보고 provider를 조립 (services §4, §7).
실 provider 모듈은 각 단계에서 추가되며, 없으면 자동으로 mock 폴백한다."""
from __future__ import annotations

import importlib
import logging

from app.config import Settings
from app.services.mock import MockLLM, MockOCR, MockSTT, MockTTS

log = logging.getLogger("providers")


class Providers:
    def __init__(self, llm, stt, tts, ocr, modes: dict[str, str]) -> None:
        self.llm = llm
        self.stt = stt
        self.tts = tts
        self.ocr = ocr
        self.modes = modes  # {"llm": "real|mock", ...}


def _build_one(kind, use_real, real_ref, mock_ctor, settings):
    if use_real:
        try:
            mod_name, cls_name = real_ref
            mod = importlib.import_module(mod_name)
            inst = getattr(mod, cls_name)(settings)
            return inst, "real"
        except Exception as exc:  # 실 모듈 미구현/초기화 실패 → mock 폴백
            log.warning("provider '%s' real init failed (%s) → mock", kind, exc)
    return mock_ctor(settings), "mock"


def build_providers(s: Settings) -> Providers:
    m = s.mock_mode
    llm, m_llm = _build_one("llm", not m and s.llm_available(),
                            ("app.services.clova_llm", "ClovaLLM"), MockLLM, s)
    stt, m_stt = _build_one("stt", not m and s.stt_available(),
                            ("app.services.clova_stt", "ClovaSTT"), MockSTT, s)
    tts, m_tts = _build_one("tts", not m and s.tts_available(),
                            ("app.services.clova_tts", "ClovaTTS"), MockTTS, s)
    ocr, m_ocr = _build_one("ocr", not m and s.ocr_available(),
                            ("app.services.clova_ocr", "ClovaOCR"), MockOCR, s)
    modes = {"llm": m_llm, "stt": m_stt, "tts": m_tts, "ocr": m_ocr}
    log.info("MOCK_MODE=%s | provider modes: %s", s.mock_mode, modes)
    return Providers(llm, stt, tts, ocr, modes)
