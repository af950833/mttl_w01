# MTTL-W01 Home Assistant Card

MTTL-W01의 MAC 마지막 7자리만 입력하면 전체 및 4개 채널 스위치와 전력 센서를 자동으로 연결하는 Lovelace 카드입니다.

## 설치

1. `mttl-w01-card.js`를 Home Assistant의 `/config/www/`에 복사합니다.
2. Home Assistant에서 **설정 → 대시보드 → 리소스**를 엽니다.
3. `/local/mttl-w01-card.js`를 **JavaScript Module**로 등록합니다.
4. 브라우저 캐시를 새로고침합니다.

카드를 추가하면 Home Assistant 비주얼 에디터에서 MAC 마지막 7자리, 선택 카드 이름과 모바일 4열 유지 옵션을 설정할 수 있습니다.

## 사용

```yaml
type: custom:mttl-w01-card
mac: 97c0123
```

선택 설정:

```yaml
type: custom:mttl-w01-card
mac: 97c0123
name: Living Room Power Strip
compact: false
```

- `mac`: MAC 주소의 마지막 7자리. 구분자와 대소문자는 자동으로 정리됩니다.
- `name`: 카드 제목을 직접 지정합니다. 생략하면 `MTTL XXXXXXX`를 표시합니다.
- `compact`: `true`이면 좁은 화면에서도 채널 4개를 한 줄로 유지합니다. 기본값은 모바일에서 2×2입니다.

카드는 기본 Entity ID가 유지되어 있어야 합니다. 예를 들어 MAC 마지막 7자리가 `97C0123`이면 `switch.mttl_97c0123_sw1`과 `sensor.mttl_97c0123_power1` 형식을 사용합니다. Home Assistant에서 Entity ID를 직접 변경했다면 자동 매핑되지 않습니다.
