"""키 유무·MOCK_MODE를 보고 provider를 조립 (services §4, §7).
실 provider 모듈은 각 단계에서 추가되며, 없으면 자동으로 mock 폴백한다.
또한 real provider가 런타임에 실패할 때 쓰도록 mock 인스턴스를 항상 함께 보관한다."""
from __future__ import annotations

import importlib
import logging

from app.config import Settings
from app.services.mock import MockLLM, MockOCR, MockSTT, MockTTS

log = logging.getLogger("providers")


class Providers:
    def __init__(self, llm, stt, tts, ocr, modes: dict[str, str], mocks) -> None:
        self.llm = llm
        self.stt = stt
        self.tts = tts
        self.ocr = ocr
        self.modes = modes  # {"llm": "real|mock", ...}
        # 런타임 폴백용 mock (real 호출 실패 시 호출부에서 사용)
        self.mllm, self.mstt, self.mtts, self.mocr = mocks


def _build_one(kind, use_real, real_ref, mock_inst, settings):
    if use_real:
        try:
            mod_name, cls_name = real_ref
            mod = importlib.import_module(mod_name)
            inst = getattr(mod, cls_name)(settings)
            return inst, "real"
        except Exception as exc:  # 실 모듈 미구현/초기화 실패 → mock 폴백
            log.warning("provider '%s' real init failed (%s) → mock", kind, exc)
    return mock_inst, "mock"


def build_providers(s: Settings) -> Providers:
    m = s.mock_mode
    mllm, mstt, mtts, mocr = MockLLM(s), MockSTT(s), MockTTS(s), MockOCR(s)
    llm, m_llm = _build_one("llm", not m and s.llm_available(),
                            ("app.services.clova_llm", "ClovaLLM"), mllm, s)
    stt, m_stt = _build_one("stt", not m and s.stt_available(),
                            ("app.services.clova_stt", "ClovaSTT"), mstt, s)
    tts, m_tts = _build_one("tts", not m and s.tts_available(),
                            ("app.services.clova_tts", "ClovaTTS"), mtts, s)
    ocr, m_ocr = _build_one("ocr", not m and s.ocr_available(),
                            ("app.services.clova_ocr", "ClovaOCR"), mocr, s)
    modes = {"llm": m_llm, "stt": m_stt, "tts": m_tts, "ocr": m_ocr}
    log.info("MOCK_MODE=%s | provider modes: %s", s.mock_mode, modes)
    return Providers(llm, stt, tts, ocr, modes, (mllm, mstt, mtts, mocr))
