# 돌봄콜 AI — 노인 안부 상담 데모 (NCP 학습 프로젝트)

독거노인 대상 AI 안부 상담 웹 데모. AI가 먼저 안부를 묻고, 대화에서 특이사항(건강·정서·사기 노출 등)을
실시간 추출해 패널에 정리하며, 자격에 맞는 복지 정보 안내와 사기 예방 코칭, 서류 사진 OCR 설명까지 제공.
**국내 리전에서 처리되는 소버린 AI 스택(NCP CLOVA)** 기반.

## 문서 지도
| 문서 | 내용 |
|---|---|
| [care-call-ai-claude-code-prompt.md](care-call-ai-claude-code-prompt.md) | 요구사항 (무엇을 만드나) |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | **실행 설계서** (어떻게 만드나 — 구현은 이 문서를 따라 진행) |
| [TEARDOWN.md](TEARDOWN.md) | 프로젝트 종료 시 철수 체크리스트 |

## 진행 상태
- [x] 로컬 환경: git, Python 3.14, Node 24, NCP CLI v1.1.30(PATH 등록)
- [x] 요구사항 + 실행 설계서 확정
- [ ] **NCP 키 발급 (아래 §키 발급 — 사용자 작업)**
- [ ] 구현 0~7단계 (설계서 §13)

## 키 발급 (콘솔 작업 — 없어도 MOCK_MODE로 개발은 진행됨)
> 서브 계정 권한에 따라 일부 메뉴가 안 보일 수 있음 → 그 서비스는 mock으로 진행하고 관리자에게 권한 요청.
> 콘솔 상단 검색창에 상품명을 치면 메뉴를 빨리 찾을 수 있다.

1. **CLOVA Studio** (LLM): 콘솔에서 이용 신청 → CLOVA Studio 콘솔 → **API 키 발급** (`nv-…`)
   - 겸사겸사 플레이그라운드에서 사용 가능한 모델 목록(HCX-007 등) 확인해두면 좋음
2. **AI·NAVER API** (STT+TTS): Application 등록 → 상품에 **CSR**과 **CLOVA Voice Premium** 체크 → **Client ID / Secret**
3. **CLOVA OCR**: 도메인 생성(**General**) → **Secret Key** 발급 + **APIGW Invoke URL** 확인
4. 발급값을 `.env`에 입력:
   ```powershell
   Copy-Item .env.example .env
   notepad .env   # 발급받은 값 채우기 (MOCK_MODE는 true 그대로 둬도 됨)
   ```

## 실행 (구현 후 갱신 예정)
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py   # → http://127.0.0.1:8000
```

## NCP CLI (참고 — 이 앱 실행에는 불필요)
- 설치 경로: `C:\Users\samsung-user\ncloud-cli\CLI_1.1.30_20260625\cli_windows` (PATH 등록됨, 새 터미널에서 `ncloud`)
- 한글 출력이 깨지면: `chcp 949`
