# 철수 가이드 (프로젝트 종료 시)

기본 데모는 로컬 실행이지만, 공인 배포를 했다면 NCP 인프라(서버·공인IP·VPC·서브넷·ACG)가 생긴다.
**과금되는 건 서버·공인IP뿐**이고 VPC/서브넷/ACG는 무료다. 아래 순서로 정리한다.

## 0. NCP 인프라 삭제 (배포했을 때만)
`$ncloud = "C:\Users\samsung-user\ncloud-cli\CLI_1.1.30_20260625\cli_windows\ncloud.cmd"`

**과금 리소스부터 (중요):**
- [ ] **공인 IP 반납**:
  ```powershell
  $pips = (& $ncloud vserver getPublicIpInstanceList --regionCode KR | ConvertFrom-Json).getPublicIpInstanceListResponse.publicIpInstanceList
  foreach ($p in $pips) { & $ncloud vserver deletePublicIpInstance --regionCode KR --publicIpInstanceNo $p.publicIpInstanceNo }
  ```
  (서버에 연결돼 있으면 먼저 `disassociatePublicIpFromServerInstance` 또는 서버 반납이 선행)
- [ ] **서버 반납**:
  ```powershell
  $srv = (& $ncloud vserver getServerInstanceList --regionCode KR --vpcNo 142283 | ConvertFrom-Json).getServerInstanceListResponse.serverInstanceList
  foreach ($s in $srv) { & $ncloud vserver terminateServerInstances --regionCode KR --serverInstanceNoList $s.serverInstanceNo }
  ```

**무료 리소스 (선택 — 남겨도 과금 0. 재배포 예정이면 유지 권장):**
- [ ] 로그인키/init스크립트: `deleteLoginKeys --keyNameList carecall-key`, `deleteInitScripts --initScriptNoList <no>`
- [ ] 서브넷(309427 carecall-bomi)·VPC(142283)·ACG(365174): 콘솔에서 삭제하거나 유지. (서버 반납 후에만 서브넷→VPC 순으로 삭제 가능)

## 1. CLOVA API 키 정리 (콘솔)
- [ ] **CLOVA OCR**: 생성한 도메인 삭제
- [ ] **AI·NAVER API**: 등록한 Application 삭제 (CSR·CLOVA Voice 키 무효화)
- [ ] **CLOVA Studio**: 발급한 API 키 삭제
- [ ] (발급했다면) **메인 API 인증키** 삭제: 마이페이지 → 인증키 관리
- [ ] 서브 계정 자체는 관리자 소관 — 반납만 알리면 됨

## 2. 로컬 PC 정리
- [ ] NCP CLI 삭제 + PATH 제거 (선택):
  ```powershell
  Remove-Item -Recurse -Force "C:\Users\samsung-user\ncloud-cli"
  $p = [Environment]::GetEnvironmentVariable("Path","User")
  [Environment]::SetEnvironmentVariable("Path", (($p -split ';' | Where-Object { $_ -notlike '*ncloud-cli*' }) -join ';'), "User")
  ```
- [ ] 프로젝트 `.env` 삭제, `Remove-Item -Recurse -Force "$HOME\.ncloud"` (configure·PEM 제거), `~/.ssh/carecall_ed25519*` 삭제
- [ ] 방화벽 규칙 제거: `netsh advfirewall firewall delete rule name="carecall-8080"` (관리자 권한)
- [ ] GitHub 리포(`wdragon92/carecall-bomi`)는 보관/삭제 자유

## 참고
- 로컬 전역 변경: PATH 1개 + ncloud-cli 폴더 + 방화벽 규칙 1개. Python venv·의존성은 프로젝트 `.venv/`에만.
