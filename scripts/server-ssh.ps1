# ============================================================
# server-ssh.ps1 — carecall 서버 비대화형 SSH 헬퍼
#
# 사용 (리포 루트에서):
#   .\scripts\server-ssh.ps1 "free -m"                        # 원격 명령
#   .\scripts\server-ssh.ps1 -Put -From .\deploy\x -To /opt/x # 파일 업로드
#
# 접속 정보는 리포 루트 .env에서 읽음:
#   SERVER_SSH_HOST / SERVER_SSH_USER / SERVER_SSH_KEY  (키 인증)
#   SERVER_SSH_PASSWORD는 비상용 기록일 뿐 이 스크립트는 키만 사용
#
# ⚠ 반드시 비대화형(BatchMode=yes)으로만 접속할 것.
#   대화형 프롬프트(비밀번호·호스트키 y/n)는 파이프가 아닌 실제 콘솔에
#   그려져서 Claude Code 등 TUI 화면·입력 상태를 깨뜨린다.
#   이 스크립트는 프롬프트 대신 "실패"하도록 강제한다.
# ============================================================
[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$CommandParts,
    [switch]$Put,
    [string]$From,
    [string]$To
)

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Command = ($CommandParts -join " ").Trim()

if (-not $Put -and -not $Command) {
    Write-Output "usage: server-ssh.ps1 `"<remote command>`""
    Write-Output "       server-ssh.ps1 -Put -From <local> -To <remote>"
    exit 2
}
if ($Put -and (-not $From -or -not $To)) {
    Write-Output "ERROR: -Put requires -From <local> and -To <remote>"
    exit 2
}

# ---- .env 파싱 (KEY=VALUE, # 주석 무시) ----
$envPath = Join-Path $RepoRoot ".env"
if (-not (Test-Path $envPath)) {
    Write-Output "ERROR: .env not found: $envPath"
    exit 2
}
$envMap = @{}
foreach ($line in [IO.File]::ReadAllLines($envPath, [Text.Encoding]::UTF8)) {
    if ($line -match '^\s*#') { continue }
    $idx = $line.IndexOf('=')
    if ($idx -lt 1) { continue }
    $envMap[$line.Substring(0, $idx).Trim()] = $line.Substring($idx + 1).Trim().Trim('"')
}
function Get-EnvVal([string]$key, [string]$default) {
    if ($envMap.ContainsKey($key) -and $envMap[$key]) { return $envMap[$key] }
    return $default
}

$tgtHost = Get-EnvVal "SERVER_SSH_HOST" "101.79.26.62"
$user    = Get-EnvVal "SERVER_SSH_USER" "root"
$key     = (Get-EnvVal "SERVER_SSH_KEY" "~/.ssh/carecall_ed25519") -replace '^~', $env:USERPROFILE
$sshOpts = @("-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new", "-i", $key)
if ($Put) {
    & scp @sshOpts $From "$user@${tgtHost}:$To"
} else {
    & ssh @sshOpts "$user@$tgtHost" $Command
}
exit $LASTEXITCODE
