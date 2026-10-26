# Sewer Profile Viewer (QGIS 플러그인)

[English](README.en.md) | 한국어

하수관로 노선을 **분기점 기준 구간 트리**로 나누고, 고른 노선의 **종단도**를 QGIS 하단 패널에 그린다.
지도에서 노선 위에 마우스를 올리면 빨간 점이 노선을 따라가고, 종단도에 같은 측점이 표시된다(종단 → 지도도 동작).

## 설치

### 가장 쉬운 방법: AI에게 맡기기
Claude Code, Cursor 같이 **내 PC에서 명령을 실행할 수 있는 AI**에게 이렇게 말하면 된다.

> https://github.com/taylee9809/qgis-sewer-profile QGIS 플러그인 설치해줘

AI가 이 README의 [AI용 설치 절차](#ai용-설치-절차)를 읽고 내려받기·압축 풀기·활성화까지 알아서 한다.
끝나면 QGIS를 다시 켜고 도구막대의 종단도 아이콘을 누르면 된다.
(웹 채팅만 되는 AI는 내 PC에 파일을 놓을 수 없으니 아래 직접 설치를 따른다.)

### 직접 설치
1. [최신 릴리스](https://github.com/taylee9809/qgis-sewer-profile/releases/latest)에서 `sewer_profile.zip` 을 받는다.
2. QGIS → **플러그인 → 플러그인 관리 및 설치 → ZIP에서 설치** → 받은 zip 선택 → **플러그인 설치**.
3. **설치됨** 탭에서 `Sewer Profile Viewer` 가 체크돼 있는지 확인 → 도구막대 아이콘으로 패널 열기.

QGIS 3.22 이상. 추가로 깔 것은 없다(matplotlib 은 QGIS 에 들어 있다).

### AI용 설치 절차
AI 에이전트가 따를 절차. 사람은 읽지 않아도 된다.
1. 받기: `https://github.com/taylee9809/qgis-sewer-profile/releases/latest/download/sewer_profile.zip`
2. 플러그인 폴더(`<plugins>`)에 풀어서 `<plugins>/sewer_profile/metadata.txt` 가 되게 한다. 폴더 이름은 반드시 `sewer_profile`.
   - Windows: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins`
   - macOS: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins`
   - Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins`
   - 프로필이 `default` 가 아니면 `profiles/` 아래 실제 프로필 이름을 쓴다. 이미 `sewer_profile` 폴더가 있으면 지우고 새로 푼다(업데이트).
3. 활성화: **QGIS 를 끈 상태에서** `profiles/<프로필>/QGIS/QGIS3.ini` 의 `[PythonPlugins]` 절에 `sewer_profile=true` 를 넣는다(절이 없으면 만든다). QGIS 가 켜져 있으면 끌 때 ini 를 덮어쓰므로 사용자에게 먼저 QGIS 를 끄라고 하거나, 대신 플러그인 관리자에서 체크하라고 안내한다.
4. 사용자에게 QGIS 를 다시 켜고 도구막대의 Sewer Profile 아이콘을 누르라고 알린다. 레이어 필드 이름이 아래 표와 다르면 `sewer_profile/network.py` 의 `PIPE_FIELDS` / `MH_FIELDS` 에 후보를 추가하면 된다는 것도 알린다.

## 기능
- 노선 레이어 → 관 그래프(끝점 0.05 m 이내 동일 노드) → 합류·분기점에서 끊은 구간(run) 트리
  - 뿌리 = 방류 구간, 자식 = 그 시점으로 합류하는 지선. 자식은 상류 총연장이 긴 순(본선 먼저)
  - 지구별로 묶어 표시, 압송 포함 구간은 분홍색
- 구간 선택 → 종단도: 지반선(맨홀 지반고 또는 DEM 2 m 샘플), 관저·관정선, 맨홀, 단차, 지장물
  - 여러 구간을 Ctrl 로 고르면 상하류로 이어지는 경우 하나로 붙여 그림
  - `방류까지` / `상류 본선` 체크로 하류·상류 자동 연장
  - 관 색: 구분(자연유하/압송) · 수리계산 결과(금회_수리판정)
- **레이어만 고르면 트리 자동 생성**(필터 입력 후 Enter 로 재생성)
- **지도에서 관로 선택 → 트리 자동 선택·펼침 → 종단 표시**, 커서가 클릭한 관 위치로 이동
  - `지도에서 고르기` 버튼(클릭한 곳에서 가장 가까운 관) 또는 QGIS 선택 도구 아무거나
- 지도 ↔ 종단 커서 연동, 커서 정보(측점·관번호·지반고·관저고·토피·경사·누가유량·유속)
- 트리 더블클릭 → 지도 확대, matplotlib 툴바로 확대/이동/PNG 저장, **마우스 휠 확대·축소**
- **표시: 도면식(기본)** — 실무 종단면도 DXF 서식(H 1:1000 · V 1:200 기본, V 배율 선택)
  - 하단 밴드 7단(측점·거리·추가거리·지반고·관저고·토피·구배), 구배 밴드 맨홀 원+관저고, `L=..M, H=..M` / `S=..‰`
  - 관번호 막대(y129)·관종 막대(`신설오수, D=200MM`, y111), 맨홀 2중 사각·45° 인출선(`SW-A-001 1호맨홀`, `H=..M (dh=..M)`)
  - 지장물 타원(가로 실폭·세로 ×V) + 45° 3줄 라벨(종류·INV.EL.·NO.)
  - 높이가 벗어나면 맨홀에서 **DATUM 변경(단절선)** — 실무 도면처럼 긴 노선도 높이를 유지
  - 글자는 도면 단위(TextPath)라 확대하면 CAD 처럼 같이 커진다
  - 지도 커서가 화면 밖으로 나가면 종단이 따라 이동
- 표시: 간단 — EL 축 그래프, 관 색(구분/수리계산 결과)

## 레이어 필드(기본 이름)
| 용도 | 필드 |
|---|---|
| 관번호 | `관번호` |
| 관저고 | `상류관저고`, `하류관저고` |
| 관경(mm) | `관경` |
| 지반고 | `상류지반고` (종점은 맨홀 레이어 `지반고`) |
| 구분 | `구분` (압송 포함 시 분홍) |
| 지장물 | `종단지장물` — `횡배수관 D600@13.3(74.70) / BOX D2.00X1.00@3.3(25.50)` (측점=관 시점부터 m, 괄호=flo 저면EL) |
| 판정·유량 | `금회_수리판정`, `수리판정`, `금회_누가유량_m3d`, `금회_실유속_mps`, `경사퍼밀` |

다른 이름을 쓰려면 `sewer_profile/network.py` 의 `PIPE_FIELDS` / `MH_FIELDS` 후보 목록에 추가한다.
도형 방향은 **상류 → 하류** 여야 한다.

## 개발용 설치
저장소를 받아 QGIS 플러그인 폴더에 정션으로 연결:
```powershell
New-Item -ItemType Junction -Path "$env:APPDATA\QGIS\QGIS3\profiles\default\python\plugins\sewer_profile" -Target "<repo>\sewer_profile"
```
QGIS → 플러그인 관리에서 `Sewer Profile Viewer` 활성화 → 도구막대 아이콘으로 패널 열기.
코드 수정 후에는 Plugin Reloader 또는 파이썬 콘솔 `qgis.utils.reloadPlugin('sewer_profile')`.

## 속도(1227관 · 최장 8.7 km 기준)
트리 생성 0.05 s · 지도 선택→종단 0.2~0.3 s · 8.7 km 도면식 2.3 s · 확대 후 이동 0.4 s.
도면식 글자는 화면에 보이고 3 px 이상일 때만 만든다(전부 도형화하면 44 s 걸렸음).

## 알려진 한계
- 지장물 원형관 위치는 `저면EL + 0.30` 을 관저로 본다(수리계산 flo 규약). BOX 는 저면EL 을 바닥으로 그린다.
- 분기 구간을 서로 다른 갈래로 함께 고르면 한 줄로 펼 수 없어 마지막 선택만 그린다.
