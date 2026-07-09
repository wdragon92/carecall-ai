# 공인 배포 런북 (NCP 서버)

> ⚠️ **서브계정 서버 작동 시간제한: 평일 09:00–22:00 / 주말 09:00–18:00.**
> 이 창 **밖에서는 서버 생성·기동이 막히고(`Temporarily out of service`), 창 밖 시간엔 서버가 자동 정지될 수 있음.**
> → 24/7 공개는 불가, **낮 시간(창 안) 시연용**. 배포·시연 모두 이 시간대에.

## 이미 만들어 둔(무료·재사용) 리소스
- VPC `142283` (carecall-vpc, 10.0.0.0/16)
- 서브넷 `309427` (carecall-bomi, KR-1, 10.0.1.0/24)
- ACG `365174` (인바운드: 22←내 PC IP, 8080/80/443←전체)
- 서버이미지 `23214590` (ubuntu-22.04 SVR22, KVM/G3 — 현 프로덕션과 동일), 스펙 `s2-g3a` (2vCPU/8GB)

## 사전
- ncloud CLI 인증됨(`~/.ncloud/configure`). PowerShell에서 `$ncloud = "C:\Users\samsung-user\ncloud-cli\CLI_1.1.30_20260625\cli_windows\ncloud.cmd"`
- SSH 키: `~/.ssh/carecall_ed25519(.pub)` (init 스크립트가 pub 주입)

## 1) 로그인키 + init 스크립트 (SSH pub 주입)
```powershell
& $ncloud vserver createLoginKey --keyName carecall-key   # privateKey 를 ~/.ncloud/carecall-key.pem 로 저장(루트 비번 복호화 대비)
$pub = Get-Content "$HOME\.ssh\carecall_ed25519.pub"
$init = "mkdir -p /root/.ssh; echo '$pub' >> /root/.ssh/authorized_keys; chmod 700 /root/.ssh; chmod 600 /root/.ssh/authorized_keys; export DEBIAN_FRONTEND=noninteractive; apt-get update -y; apt-get install -y git python3-venv python3-pip"
$initNo = (& $ncloud vserver createInitScript --regionCode KR --initScriptName carecall-init --initScriptContent $init | ConvertFrom-Json).createInitScriptResponse.initScriptList[0].initScriptNo
```

## 2) 서버 생성 (시간창 안에서!)
> ⚠️ 서브계정은 CLI 생성이 거부될 수 있음(`Temporarily out of service`) — 그 경우 **콘솔에서 동일 파라미터로 생성**.
```powershell
& $ncloud vserver createServerInstances --regionCode KR --vpcNo 142283 --subnetNo 309427 `
  --serverImageNo 23214590 --serverSpecCode s2-g3a --serverName carecall-1 `
  --loginKeyName carecall-key --initScriptNo $initNo `
  --networkInterfaceList "networkInterfaceOrder='0', subnetNo='309427', accessControlGroupNoList='365174'"
# RUN 될 때까지 대기(2~4분)
do { Start-Sleep 15; $s=(& $ncloud vserver getServerInstanceList --regionCode KR --vpcNo 142283 | ConvertFrom-Json).getServerInstanceListResponse.serverInstanceList[0]; $s.serverInstanceStatus.code } while ($s.serverInstanceStatus.code -ne "RUN")
$serverNo = $s.serverInstanceNo
```

## 3) 공인 IP 생성 + 연결
```powershell
$pip = (& $ncloud vserver createPublicIpInstance --regionCode KR --serverInstanceNo $serverNo | ConvertFrom-Json).createPublicIpInstanceResponse.publicIpInstanceList[0]
$IP = $pip.publicIp
"공인 IP: $IP"
```

## 4) ACG의 SSH(22) 규칙을 오늘자 내 PC IP로 갱신
```powershell
$myip = (Invoke-RestMethod https://api.ipify.org)
& $ncloud vserver addAccessControlGroupInboundRule --regionCode KR --vpcNo 142283 --accessControlGroupNo 365174 `
  --accessControlGroupRuleList "protocolTypeCode='TCP', ipBlock='$myip/32', portRange='22'"
```

## 5) 배포 (서버에서 git clone → .env만 전송)
```bash
# (PC, Git Bash) SSH 접속 확인
ssh -i ~/.ssh/carecall_ed25519 -o StrictHostKeyChecking=no root@$IP "echo ok"
# 서버에 공개 리포 클론
ssh -i ~/.ssh/carecall_ed25519 root@$IP "git clone https://github.com/wdragon92/carecall-bomi /opt/carecall"
# .env(키 포함, git 미포함)만 전송
scp -i ~/.ssh/carecall_ed25519 /c/Users/samsung-user/Desktop/ncloud_project/.env root@$IP:/opt/carecall/.env
# 서버 셋업(systemd + Caddy HTTPS)
ssh -i ~/.ssh/carecall_ed25519 root@$IP "APP_PUBLIC_IP=$IP bash /opt/carecall/deploy/server_setup.sh"
```

## 6) 확인
- HTTP : `http://<IP>:8080`
- HTTPS: `https://<IP>.sslip.io`  ← **모바일 마이크(STT)는 이 https 주소에서 동작**
```bash
curl -s http://$IP:8080/health   # providers 전부 real + rag.loaded:true 확인
```

## 7) 코드/인덱스 갱신 (운영 중)
```bash
# 코드 갱신 (requirements 변경 시 pip install 포함)
ssh -i ~/.ssh/carecall_ed25519 root@$IP \
  "cd /opt/carecall && git pull && ./.venv/bin/pip install -r requirements.txt -q && systemctl restart carecall"

# RAG 인덱스만 갱신 (재시작 불필요 — 무중단 스왑; 주 1회 cron 자동 + 발표 전날 수동 1회)
ssh -i ~/.ssh/carecall_ed25519 root@$IP \
  "cd /opt/carecall && ./.venv/bin/python build_index.py --source fixtures && curl -s -X POST http://127.0.0.1:8080/api/rag/reload"
```

## 철수 (시연 후) — TEARDOWN.md 참고
서버·공인IP만 지우면 과금 종료. VPC/서브넷/ACG는 무료라 유지해도 무방.
