# MTTL-W01 로컬 서버

[Korean](README.md) | [English](README_EN.md)

LG U+ `MTTL-W01` 스마트 멀티탭을 제조사 클라우드 없이 내부망에서 사용하기 위한 Docker 기반 로컬 서버입니다.

![MTTL-W01 로컬 서버 웹 대시보드](docs/dashboard.png)

주요 기능:

- 멀티탭 인증서 발급 및 로컬 서버 등록(MEF enrollment)
- 멀티탭 전용 TLS MQTT 서버
- 여러 대의 멀티탭을 관리하는 웹 대시보드
- 전체 및 1~4번 채널 제어와 소비전력 표시
- ASUS 공유기의 목적지 IP 기반 DNAT 자동 설정
- Home Assistant MQTT Discovery 연동
- Android 프로비저닝 앱과 다운로드 QR
- 구형 기기의 정식 `1.0.66` 펌웨어 자동 업데이트
- DB 없이 JSON/JSONL 파일로 상태 저장

> 이 프로젝트는 LG U+의 공식 프로젝트가 아닙니다. 신뢰할 수 있는 개인 내부망에서 사용하는 것을 전제로 합니다.

## 동작 구조

멀티탭은 원래 제조사 서버 IP로 접속하지만, ASUS 공유기의 DNAT가 아래 네 연결만 Docker 서버로 전달합니다.

| 원래 목적지 | 로컬 서버 목적지 | 용도 |
| --- | --- | --- |
| `106.103.210.126:80` | `LOCAL_SERVER_IP:18080` | 자체 CA 다운로드 |
| `106.103.210.126:443` | `LOCAL_SERVER_IP:18443` | MEF 등록 및 OTA 확인 |
| `106.103.210.119:18831` | `LOCAL_SERVER_IP:18832` | 멀티탭 TLS MQTT |
| `61.34.165.80:443` | `LOCAL_SERVER_IP:19443` | QMS 진단 로그 수신 및 성공 응답 |

멀티탭의 출발지 IP를 고정하거나 기기별 DNAT 규칙을 만들 필요는 없습니다. 다만 위 목적지 IP를 사용하는 다른 LG U+ IoT 기기가 같은 네트워크에 있다면 그 기기의 통신도 영향을 받을 수 있습니다.

## 준비물

- LG U+ MTTL-W01 멀티탭
- 24시간 동작 가능한 Linux 서버(Ubuntu 22.04/24.04 권장)
- Docker Engine
- 내부망 고정 IP 또는 DHCP 고정 할당을 적용한 서버
- SSH가 활성화된 ASUS 공유기
  - SSH 계정이 `/usr/sbin/iptables`와 `/usr/sbin/conntrack`을 실행할 수 있어야 합니다.
- Android 10 이상 휴대전화
- 멀티탭이 연결할 2.4 GHz Wi-Fi SSID와 암호
- Home Assistant 연동 시 별도의 MQTT Broker

## 1. Docker 확인

Docker가 이미 설치되어 있다면 설치 단계는 건너뜁니다.

```bash
docker version
```

현재 사용자가 Docker를 실행할 권한이 없다면 명령 앞에 `sudo`를 붙이거나 Docker 그룹 설정을 완료하십시오.

## 2. 저장소 내려받기

```bash
git clone https://github.com/af950833/mttl_w01.git
cd mttl_w01
```

## 3. Docker 이미지 빌드

```bash
docker build -t mttl-local:latest .
```

이미지에는 서버, 웹 대시보드, Android APK 및 MTTL-W01 정식 `1.0.66` 펌웨어가 포함됩니다.

## 4. 데이터 및 인증서 디렉터리 생성

아래 예시는 `/srv/mttl`을 영구 저장 경로로 사용합니다. 다른 경로를 사용한다면 이후 명령도 같은 경로로 변경하십시오.

```bash
sudo mkdir -p /srv/mttl/data /srv/mttl/certs
sudo chown -R 10001:10001 /srv/mttl/data /srv/mttl/certs
```

컨테이너 내부 서버는 UID `10001`로 동작하므로 두 디렉터리에 쓰기 권한이 필요합니다.

## 5. 서버 전용 인증서 생성

설치할 서버마다 고유한 CA와 서버 인증서를 한 번 생성해야 합니다.

```bash
docker run --rm \
  -v /srv/mttl/certs:/certs \
  mttl-local:latest generate-certs
```

생성되는 파일:

- `root-ca.crt`, `root-ca.key`
- `mef.crt`, `mef.key`
- `brk2.crt`, `brk2.key`
- `qms.crt`, `qms.key`

확인 명령:

```bash
sudo ls -l /srv/mttl/certs
```

완전한 인증서 세트가 이미 있으면 생성 명령은 기존 인증서를 덮어쓰지 않습니다. 이전 버전의 6개 인증서가 있고 `root-ca.key`가 보존되어 있으면 기존 CA로 `qms.crt`와 `qms.key`만 추가합니다. 일부 기본 파일만 남은 불완전한 상태에서는 자동 교체하지 않습니다.

`root-ca.key`는 서버의 개인키입니다. 공개 저장소나 공유 폴더에 복사하지 마십시오. 이미 등록한 멀티탭을 계속 사용하려면 `/srv/mttl/certs`를 반드시 백업해야 합니다.

## 6. 컨테이너 실행

```bash
docker run -d \
  --name mttl-local \
  --restart unless-stopped \
  --network host \
  -v /srv/mttl/data:/data \
  -v /srv/mttl/certs:/certs:ro \
  mttl-local:latest
```

실행 상태 확인:

```bash
docker ps --filter name=mttl-local
docker logs --tail 100 mttl-local
curl http://127.0.0.1:18833/api/health
```

정상 응답:

```json
{"status": "ok"}
```

서버에서 다음 TCP 포트를 허용해야 합니다.

| 포트 | 용도 |
| ---: | --- |
| `18080` | 멀티탭 CA 다운로드 |
| `18443` | TLS MEF 등록 및 OTA |
| `18832` | 멀티탭 TLS MQTT |
| `19443` | QMS TLS 진단 로그 수신 |
| `18833` | 웹 대시보드와 REST API |

UFW 명령은 **서버에서 UFW를 활성화하여 사용하는 경우에만 필요한 선택 사항**입니다. `sudo ufw status` 결과가 `inactive`라면 아래 규칙을 실행할 필요가 없습니다.

UFW 사용 예시:

```bash
sudo ufw allow from 192.168.0.0/24 to any port 18080 proto tcp
sudo ufw allow from 192.168.0.0/24 to any port 18443 proto tcp
sudo ufw allow from 192.168.0.0/24 to any port 18832 proto tcp
sudo ufw allow from 192.168.0.0/24 to any port 18833 proto tcp
sudo ufw allow from 192.168.0.0/24 to any port 19443 proto tcp
```

실제 네트워크가 다르면 `192.168.0.0/24`를 내부망 대역으로 변경하십시오.

## 7. 서버 업데이트

최초 설치가 끝난 뒤 새 버전으로 업데이트할 때는 영구 데이터를 먼저 백업하고 저장소와 이미지를 갱신합니다.

```bash
cd mttl_w01
git pull
docker build -t mttl-local:latest .
sudo test -s /srv/mttl/certs/root-ca.key
docker run --rm \
  -v /srv/mttl/certs:/certs \
  mttl-local:latest generate-certs
docker stop mttl-local
docker rm mttl-local
docker run -d \
  --name mttl-local \
  --restart unless-stopped \
  --network host \
  -v /srv/mttl/data:/data \
  -v /srv/mttl/certs:/certs:ro \
  mttl-local:latest
```

업데이트 시 인증서 생성 명령은 기존 CA와 서버 인증서를 변경하지 않고 필요한 새 인증서만 추가합니다. `root-ca.key` 검사에서 실패하면 진행을 중단하고 인증서 백업을 복원하십시오. 기존 CA 개인키 없이 새 CA를 생성하면 이미 등록된 멀티탭은 새 CA를 신뢰하지 않으므로 초기화 후 재프로비저닝해야 합니다.

업데이트 후 DNAT 카드가 **Partially Enabled**로 표시되면 **Disable DNAT**을 누른 뒤 **Enable DNAT**을 눌러 QMS를 포함한 네 규칙을 다시 적용합니다. 기존 CA가 보존되었다면 멀티탭을 재프로비저닝할 필요가 없습니다.

## 8. 웹 대시보드 접속

브라우저에서 다음 주소를 엽니다.

```text
http://LOCAL_SERVER_IP:18833/
```

서버 IP가 `192.168.0.4`인 경우:

```text
http://192.168.0.4:18833/
```

## 9. ASUS Router DNAT 설정

ASUS 공유기 관리 페이지에서 SSH를 활성화한 다음 대시보드의 **ASUS Router DNAT** 카드에 입력합니다.

- **Router IP**: 공유기의 내부 IP
- **SSH Username**: 공유기 SSH 사용자 이름
- **SSH Password**: 공유기 SSH 암호
- **Local Server IP**: Docker 서버의 내부 IP

설정 순서:

1. **Save Settings**를 눌러 저장합니다.
2. **Test Connection**으로 SSH, `iptables`, `conntrack` 사용 가능 여부를 확인합니다.
3. **Enable DNAT**을 눌러 네 개의 전달 규칙을 적용합니다.
4. 카드 우측 상태가 **Enabled**이고 네 규칙이 모두 `Enabled`인지 확인합니다.

서버는 공유기에 `MTTL_DNAT`이라는 별도 NAT 체인을 만들고 기존 연결의 conntrack 항목을 정리합니다. 공유기 암호는 `/data/router-dnat.json`에 권한 `0600`으로 저장되며 대시보드 API로 반환되지 않습니다.

제조사 서버에 임시로 연결하거나 DNAT가 필요 없을 때는 **Disable DNAT**을 누릅니다.

### ASUS 공유기에서 수동으로 DNAT 설정하기

대시보드의 DNAT 관리 기능을 사용하지 않을 경우 ASUS 공유기에 SSH로 접속하여 직접 규칙을 만들 수도 있습니다. 다음 예시는 로컬 서버 IP가 `192.168.0.4`인 경우입니다. IP가 다르면 첫 줄의 값을 변경하십시오.

```sh
LOCAL_SERVER_IP=192.168.0.4

/usr/sbin/iptables -t nat -N MTTL_DNAT
/usr/sbin/iptables -t nat -I PREROUTING 1 -j MTTL_DNAT
/usr/sbin/iptables -t nat -A MTTL_DNAT -d 106.103.210.126/32 -p tcp --dport 80 -j DNAT --to-destination ${LOCAL_SERVER_IP}:18080
/usr/sbin/iptables -t nat -A MTTL_DNAT -d 106.103.210.126/32 -p tcp --dport 443 -j DNAT --to-destination ${LOCAL_SERVER_IP}:18443
/usr/sbin/iptables -t nat -A MTTL_DNAT -d 106.103.210.119/32 -p tcp --dport 18831 -j DNAT --to-destination ${LOCAL_SERVER_IP}:18832
/usr/sbin/iptables -t nat -A MTTL_DNAT -d 61.34.165.80/32 -p tcp --dport 443 -j DNAT --to-destination ${LOCAL_SERVER_IP}:19443

/usr/sbin/conntrack -D -d 106.103.210.126 -p tcp --dport 80
/usr/sbin/conntrack -D -d 106.103.210.126 -p tcp --dport 443
/usr/sbin/conntrack -D -d 106.103.210.119 -p tcp --dport 18831
/usr/sbin/conntrack -D -d 61.34.165.80 -p tcp --dport 443
```

적용 상태 확인:

```sh
/usr/sbin/iptables -t nat -nL MTTL_DNAT -v
```

수동 규칙 제거:

```sh
/usr/sbin/iptables -t nat -D PREROUTING -j MTTL_DNAT
/usr/sbin/iptables -t nat -F MTTL_DNAT
/usr/sbin/iptables -t nat -X MTTL_DNAT

/usr/sbin/conntrack -D -d 106.103.210.126 -p tcp --dport 80
/usr/sbin/conntrack -D -d 106.103.210.126 -p tcp --dport 443
/usr/sbin/conntrack -D -d 106.103.210.119 -p tcp --dport 18831
/usr/sbin/conntrack -D -d 61.34.165.80 -p tcp --dport 443
```

위 생성 명령은 빈 상태에서 한 번 실행하는 기준입니다. 같은 명령을 반복하면 규칙이 중복되거나 `Chain already exists` 오류가 발생할 수 있습니다. 대시보드 자동 관리와 수동 설정을 동시에 사용하지 마십시오. 일반적인 ASUS 펌웨어에서는 재부팅 후 직접 추가한 규칙이 사라질 수 있으므로, 영구 적용이 필요하다면 ASUSWRT-Merlin의 방화벽 시작 스크립트 등 사용 중인 펌웨어에 맞는 방법을 별도로 적용해야 합니다.

ASUS 이외의 공유기는 프로젝트가 DNAT를 자동 설정하지 않습니다. 해당 공유기의 포트 포워딩, 정책 NAT 또는 방화벽 기능을 이용하여 위 표의 **목적지 IP와 목적지 포트 기준 DNAT 네 규칙**을 사용자가 직접 구현해야 합니다. 일반적인 외부 포트 포워딩과 달리 LAN 클라이언트가 특정 인터넷 IP로 보내는 트래픽을 내부 서버로 바꾸는 기능이 필요합니다.

## 10. Android 프로비저닝 앱 설치

대시보드 최상단의 QR 코드를 Android 휴대전화로 스캔하거나 아래 주소에서 APK를 받습니다.

```text
http://LOCAL_SERVER_IP:18833/downloads/MTTL-W01-Provisioner.apk
```

GitHub에서도 직접 받을 수 있습니다.

- [MTTL-W01 Provisioner APK](web/downloads/MTTL-W01-Provisioner.apk)

Android가 경고하면 해당 브라우저 또는 파일 관리자의 **알 수 없는 앱 설치** 권한을 허용합니다. Wi-Fi 검색을 위한 위치 또는 주변 기기 권한도 허용해야 합니다.

이 APK를 이용하면 제조사 앱인 **U+ 스마트홈** 없이도 멀티탭을 프로비저닝할 수 있습니다.

APK를 신뢰하기 어려운 사용자는 제조사 앱을 설치하고 회원가입한 뒤 제조사 앱으로 프로비저닝해도 됩니다. 다만 제조사 앱은 대한민국 휴대전화번호를 통한 본인 인증이 필요하므로, 대한민국 휴대전화번호를 사용할 수 없는 해외 사용자에게는 이 APK 사용을 권장합니다.

## 11. 멀티탭 프로비저닝

프로비저닝 전에 DNAT를 활성화하고 Docker 서버가 정상 동작 중인지 확인합니다.

1. 멀티탭의 메인 버튼을 약 10초 이상 눌러 상태 LED가 빠르게 깜박이게 합니다.
2. `TONLY_TAP_XXXXXXX` 형식의 설정 AP가 나타날 때까지 기다립니다.
3. 앱에서 **SCAN WI-FI Network**를 누릅니다.
4. **Home Wi-Fi SSID**에서 멀티탭이 사용할 2.4 GHz Wi-Fi를 선택합니다.
5. **Home Wi-Fi password**에 암호를 입력합니다.
6. 앱에서 해당 멀티탭 AP를 선택하고 **Provision**을 누릅니다.
7. Android의 Wi-Fi 연결 승인 창이 나타나면 허용합니다.
8. 앱 로그에 **Provision Success**와 **You can close this APP**이 표시될 때까지 기다립니다.
9. 멀티탭이 자동으로 재부팅하고 홈 Wi-Fi에 연결될 때까지 기다립니다.
10. 대시보드에 새 카드가 나타나고 상태 LED가 더 이상 깜빡이지 않는지 확인합니다.

앱은 설정 AP 이름의 마지막 7자리로 `LGU_XXXXXXX` 형식의 AP 암호를 자동 계산합니다. 홈 Wi-Fi 정보는 멀티탭의 로컬 포트 `30300`으로 직접 전송합니다.

대시보드에서 카드만 삭제해도 이미 프로비저닝된 멀티탭이 서버에 재접속하면 카드가 다시 생성될 수 있습니다. 완전히 삭제하려면 멀티탭을 초기화한 뒤 카드를 삭제하세요.

## 12. 대시보드 기능

- 기기 이름 및 채널 이름 변경
- 전체 전원 및 1~4번 채널 개별 제어
- 전체/채널별 현재 소비전력 확인
- Today 사용량 확인
- 펌웨어 버전과 온라인 상태 확인
- **HA Link** 활성화/비활성화
- 기기 카드 삭제

연결이 끊기면 기본적으로 약 45초 뒤 오프라인으로 판단합니다. 기기 상태 변경은 SSE를 통해 대시보드에 실시간으로 반영되며, 누락에 대비해 약 30초 간격으로 다시 확인합니다.

## 13. Home Assistant MQTT 연동

Home Assistant에 MQTT 통합과 MQTT Broker가 먼저 준비되어 있어야 합니다. 대시보드의 **Home Assistant MQTT** 카드에 입력합니다.

- **MQTT Broker IP**: MQTT Broker의 내부 IP
- **Port**: 기본값 `1883`
- **Username / Password**: MQTT Broker 계정
- **Discovery Prefix**: 기본값 `homeassistant`
- **Topic Prefix**: 기본값 `mttl`

**Save & Connect**를 누르고 `Status: Connected`를 확인합니다. 이후 각 멀티탭 카드의 **HA Link**를 활성화하면 MQTT Discovery 엔티티가 생성됩니다.

MAC 마지막 7자리가 `97C0123`인 기기의 기본 Entity ID:

```text
switch.mttl_97c0123_all
switch.mttl_97c0123_sw1
switch.mttl_97c0123_sw2
switch.mttl_97c0123_sw3
switch.mttl_97c0123_sw4

sensor.mttl_97c0123_powerall
sensor.mttl_97c0123_power1
sensor.mttl_97c0123_power2
sensor.mttl_97c0123_power3
sensor.mttl_97c0123_power4
sensor.mttl_97c0123_today_usage
```

전체 스위치 표시 이름은 `SW All`, 일일 사용량 센서는 `Today Usage`입니다. 온라인 여부는 별도 센서가 아니라 각 엔티티의 MQTT availability로 전달됩니다.

HA Link를 비활성화하면 MQTT Discovery 삭제 메시지가 발행됩니다. Home Assistant가 중지된 상태에서는 삭제를 즉시 처리하지 못할 수 있으므로 HA와 Broker가 실행 중일 때 비활성화하는 것이 좋습니다.

### MTTL-W01 Lovelace 카드

[`ha-card/mttl-w01-card.js`](ha-card/mttl-w01-card.js)를 Home Assistant의 `/config/www/`에 복사하고 `/local/mttl-w01-card.js`를 JavaScript Module 리소스로 등록합니다. MAC 마지막 7자리만 입력하면 전체 전력, Today Usage, 전체 스위치와 4개 채널의 이름·현재 전력·스위치를 자동 배치합니다.

```yaml
type: custom:mttl-w01-card
mac: 97c0123
```

![MTTL-W01 Home Assistant Lovelace 카드](ha-card/HA_card.png)

상세 설치법과 선택 설정은 [`ha-card/README.md`](ha-card/README.md)를 참고하십시오. Home Assistant에서 기본 Entity ID를 직접 변경한 경우에는 자동 매핑되지 않습니다.

## 14. 펌웨어 자동 업데이트

이미지에는 수정하지 않은 MTTL-W01 정식 `1.0.66` 펌웨어가 포함됩니다. 기기가 로컬 MEF 서버에 보고한 버전이 `1.0.66`보다 낮으면 서버가 자동으로 업데이트를 제안하며, `1.0.66` 이상에는 제안하지 않습니다.

```text
파일:   comMTTL-W01_1.0.66.fwr
크기:   327944 bytes
SHA256: d780b578af69d52f3a05191a8e7d91a20e05085a912722327481cd5663682c04
```

업데이트 중에는 전원을 차단하지 마십시오. 다운로드 후 여러 번 재부팅하거나 다시 온라인으로 나타나기까지 시간이 걸릴 수 있습니다.

```bash
docker logs -f mttl-local
```

## 15. 데이터와 백업

별도 DB 없이 영구 데이터는 `/srv/mttl/data`에 저장됩니다.

- 기기 등록 정보와 이름
- 채널 상태와 전력 정보
- Today 사용량 스냅샷
- DNAT 및 Home Assistant MQTT 설정
- 서버 로그

백업 대상:

```text
/srv/mttl/data
/srv/mttl/certs
```

인증서 디렉터리를 잃어버리면 기존 CA를 신뢰하도록 등록된 멀티탭을 초기화하고 다시 프로비저닝해야 할 수 있습니다.

## 16. 문제 해결

### 대시보드가 열리지 않을 때

```bash
docker ps --filter name=mttl-local
docker logs --tail 200 mttl-local
sudo ss -lntp | grep -E '18080|18443|18832|18833|19443'
curl http://127.0.0.1:18833/api/health
```

### 컨테이너가 인증서 오류로 종료될 때

로그에 `missing certificate files`가 표시되면 `/srv/mttl/certs`의 파일과 마운트 경로를 확인하고 5단계의 인증서 생성 명령을 실행합니다.

### DNAT 테스트가 실패할 때

- 공유기의 SSH 기능과 계정 정보를 확인합니다.
- `/usr/sbin/iptables --version` 실행 여부를 확인합니다.
- 공유기에 `/usr/sbin/conntrack`이 존재하는지 확인합니다.
- Docker 서버 IP가 변경되지 않았는지 확인합니다.
- 공유기와 서버가 서로 접근 가능한 내부망인지 확인합니다.

### 프로비저닝 후 기기가 오프라인일 때

- DNAT 네 항목이 모두 Enabled인지 확인합니다.
- 멀티탭이 2.4 GHz Wi-Fi를 사용하는지 확인합니다.
- 서버 방화벽이 `18080`, `18443`, `18832`, `19443`을 허용하는지 확인합니다.
- `docker logs -f mttl-local` 상태에서 멀티탭 전원을 다시 연결합니다.
- SSID 또는 암호에 `:`가 있으면 현재 펌웨어의 로컬 명령 형식상 사용할 수 없습니다.

### Home Assistant 엔티티가 생성되지 않을 때

- Home Assistant MQTT 카드가 `Connected`인지 확인합니다.
- 멀티탭 카드의 HA Link를 활성화합니다.
- Discovery Prefix가 Home Assistant 설정과 같은지 확인합니다.
- MQTT 계정에 Discovery 및 `mttl/#` 토픽 publish/subscribe 권한이 있는지 확인합니다.

## 보안 참고

- 웹 대시보드는 인증 기능이 없으므로 인터넷에 직접 노출하지 마십시오.
- 공유기 및 MQTT 암호가 저장되는 데이터 디렉터리 권한을 제한하십시오.
- 생성한 CA 개인키를 저장소에 커밋하지 마십시오.
- DNAT를 켜면 지정된 제조사 목적지의 통신이 로컬 서버로 전달됩니다.

## 현재 버전

| 구성 요소 | 버전 |
| --- | --- |
| 로컬 서버 및 웹 대시보드 | `20260901` |
| Android Provisioner | `0.3.2` (`versionCode 14`) |
| 내장 MTTL-W01 펌웨어 | `1.0.66` |

## Version history

### `20260901`

- QMS HTTPS 요청을 로컬에서 수신하고 빈 `HTTP 200` 응답을 반환하도록 추가
- QMS 목적지 `61.34.165.80:443`을 기존 ASUS Router DNAT의 네 번째 규칙으로 통합
- 기존 `root-ca.key`를 사용해 `qms.crt`와 `qms.key`만 추가할 수 있도록 인증서 생성 기능 확장
- 기존 사용자가 CA와 프로비저닝 상태를 유지하면서 업데이트할 수 있는 절차 추가
- MQTT 명령 처리와 연결 상태 관리 안정성 개선
- SSE 실시간 알림으로 웹·물리 버튼·Home Assistant 제어 상태를 즉시 갱신
- MAC 마지막 7자리만 입력하는 MTTL-W01 Lovelace 카드 추가
- MTTL-W01 카드 비주얼 에디터 지원

### `20260831`

- MTTL-W01 로컬 서버 및 카드형 웹 대시보드 최초 공개
- 멀티탭 전체/채널 제어, 상태·전력·Today Usage 표시 지원
- Home Assistant MQTT Discovery 및 기기별 HA Link 지원
- ASUS 공유기 목적지 기반 DNAT 자동 관리 지원
- Android Provisioner `0.3.2`와 QR/APK 다운로드 제공
- 정식 MTTL-W01 펌웨어 `1.0.66` OTA 제공
