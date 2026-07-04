# 철수 가이드 (프로젝트 종료 시)

이 프로젝트는 **NCP 인프라(서버·VPC·스토리지)를 하나도 만들지 않는다.**
로컬에서 앱을 돌리고 NCP는 API 호출만 사용하므로, 철수는 아래 체크리스트로 끝난다.

## 1. NCP 콘솔에서 삭제 (5분)
- [ ] **CLOVA OCR**: 생성한 도메인 삭제
- [ ] **AI·NAVER API**: 등록한 Application 삭제 (CSR·CLOVA Voice 키 무효화)
- [ ] **CLOVA Studio**: 발급한 API 키 삭제
- [ ] (발급했다면) **메인 API 인증키** 삭제: 마이페이지 → 인증키 관리
- [ ] 서브 계정 자체는 관리자 소관 — 반납만 알리면 됨

## 2. 로컬 PC 정리
- [ ] NCP CLI 삭제 + PATH 제거 (선택 — 남겨도 무해):
  ```powershell
  Remove-Item -Recurse -Force "C:\Users\samsung-user\ncloud-cli"
  $p = [Environment]::GetEnvironmentVariable("Path","User")
  $new = ($p -split ';' | Where-Object { $_ -notlike '*ncloud-cli*' }) -join ';'
  [Environment]::SetEnvironmentVariable("Path", $new, "User")
  ```
- [ ] 프로젝트의 `.env` 삭제 (키 흔적 제거)
- [ ] `ncloud configure`를 실행했었다면: `Remove-Item -Recurse -Force "$HOME\.ncloud"`
- [ ] 레포는 로컬 전용(원격 없음) — 보관하든 삭제하든 자유

## 참고
- 이 머신에 이 프로젝트가 남긴 전역 변경은 **PATH 항목 1개 + ncloud-cli 폴더 1개**뿐.
- Python venv·의존성은 전부 프로젝트 폴더 안(`.venv/`)에만 존재.
