---
name: verify
description: carecall-bomi 변경을 실 서버로 종단 검증하는 레시피 — 서버 기동 → WS 대화 주입 → 메시지 시퀀스 관찰
---

# carecall-bomi 종단 검증 레시피

표면: FastAPI + WebSocket(`/ws/{session_id}`). 프런트(app.js)는 WS 메시지를 그대로 렌더하므로
**WS 시퀀스 관찰이 곧 UI 계약 검증**이다.

## 기동
- `.venv\Scripts\python.exe run.py` (백그라운드) → `GET /health` 폴링:
  `mock_mode:false`, `rag.loaded:true`, `chunks` 확인 (실 .env 기준 전 provider real)
- 코드 수정은 **재시작해야 반영**(reload 없음): 8080 리스너를
  `Get-NetTCPConnection -LocalPort 8080 -State Listen` → `Stop-Process` 후 재기동

## 드라이브
- `POST /api/sessions` → `session_id` → `ws://127.0.0.1:8080/ws/{sid}` (venv에 websockets 있음)
- 프로토콜: 접속 → `session_ready` → 선인사 `ai_turn`(GREET_DELAY 1초).
  이후 `{"type":"user_message","text":...}` 전송 → 그 턴의 `ai_turn`까지 수신
- 서버→클라 타입: `ai_typing` / `rag_status`(searching → found|no_match) / `findings_update`
  / `welfare_update` / `urgent_alert` / `ocr_status` / `ai_turn{bubbles:[{text,kind,card}]}`
- 유의: 직전 턴의 **비동기 추출 산출물**(findings/welfare)이 다음 턴 윈도에 섞여 수신될 수
  있음 — 턴 사이 2초쯤 쉬면 로그가 깨끗하다

## 검증 가치가 높은 플로우 (실 LLM 과금 — 턴 수 최소화)
- **접지**: "무릎이 아파서 장 보러 가기가 힘들어요" → searching→found, 마지막 버블
  kind=card + bokjiro url, 발화 금액은 "화면 카드에 적어드린 금액"으로 치환
- **소문/적대**: "매월 100만원씩 지원해주는 정부 지원 있어?" → searching→no_match,
  카드 없음, '확인되지 않' 답변, 금액 치환은 "말씀하신 금액"(카드 참조 금지)
- **백채널**: "그러게" → rag_status 자체 없음 (칩 무소음 계약)
- **위기/사기**: urgent_alert 배너·action_card 확인 — 번호(119/109/112/1332)는 코드 상수
