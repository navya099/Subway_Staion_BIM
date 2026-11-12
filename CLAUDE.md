# CLAUDE.md — subway_station_BIM

지하철 개착식(open-cut) 정거장 BIM 자동 생성기. 파라미터(GUI/코드)를 입력하면 **3D DXF, 횡단면도, 평면도, 종단면도(DXF)와 IFC4** 를 만든다.
Python + tkinter. 작성자: Dger (한국어 사용, 응답·주석·커밋 메시지는 한국어 기본).

## 1. 빠른 시작

```bash
pip install ezdxf ifcopenshell numpy matplotlib pillow pytest pyflakes
# 리눅스: tkinter 는 시스템 파이썬과 같은 버전의 python3-tk 가 필요 (apt install python3-tk)
python main.py                      # GUI 실행
xvfb-run -a python -m pytest -q     # 전체 테스트 (GUI 포함, 디스플레이 없으면 GUI 테스트는 skip)
python -m pyflakes <소스 디렉터리>   # 소스는 경고 0 유지 (tests/ 에는 기존 미사용 import 경고가 일부 있음)
```

- 현재 기준 **테스트 479개 통과** (GUI 72개 포함). 코드를 바꾸면 반드시 전체 테스트를 돌릴 것.
- 코드 전체에서 길이 단위는 **m**, 각도 내부 단위는 rad.
- 패키지 폴더에는 `__init__.py` 를 두지 않는다 (네임스페이스 패키지로 통일).

## 2. 좌표계와 핵심 규약 (가장 중요 — 바꾸기 전에 반드시 읽을 것)

정거장 로컬 좌표 `(s, t, z)`:
- **s**: 선형 진행방향 거리. **s=0 = 시점 마감벽 안쪽 면(내공 시작)**, **s=L = 종점 마감벽 안쪽 면**. 단부 벽체는 s<0, s>L 에 붙는다.
- **t**: 선형 직교방향, **진행방향 왼쪽이 +** (`to_world` 가 이 방향으로 변환), 선형 중심 = 0.
- **z**: 본체 바닥 슬래브 상면 = FL = 0 기준 상대 표고. 실제 표고는 선형 종단 `lv(s) - offset + z`.
- 선형과의 접점은 `StationProjectConfig` 하나뿐: `lv(s)`, `theta_at(s)`, `grade_permil(s)`, `curvature_at(s)`, `to_world(s,t)`, `origin()`, `sample_s(s0,s1)`. 엔진·내보내기는 선형에 직접 접근하지 말고 이 메서드만 쓴다.

**내공(clear) 기준**: `StationParameters.length/width` 는 외곽이 아니라 **내공 치수**. 실무 도면 확인 결과 "벽 800 + 내공 213.2m + 벽 800" 구조이고, **start/end STA = 단부 마감벽 안쪽 면**.

**벽체 규약**: **내벽(내공면)은 모든 층에서 고정**, **외벽면만 층별 두께(`wall_ts[i]`)에 따라 계단식**으로 변한다. 슬래브는 이에 맞춰 — 중간 슬래브 = 내공 영역(0..L × ±W/2), 바닥/천장 슬래브 = 최하층/최상층 외곽.

**층 번호**: 내부는 `floor_n = 1` 이 최하층. 표시 이름은 `B3F … B1F`(층수>1), 1층 건물은 `1F`.

**슬래브 번호(오프닝용)**: `0` = 본체 바닥, `i`(1..floors-1) = i층/i+1층 사이 중간 슬래브, `floors` = 본체 천장. 슬래브 객체 이름은 `SLAB_{level}_{FLOOR|MID|ROOF}`.

**부재 = 각기둥(prism)**: 벽체·슬래브·승강장·지지벽체는 `(s 구간)×(t 구간)×(연직 두께)` + 종단구배(`rise`). 직선 선형이면 경사 각기둥 1개(DXF 6면, IFC `SweptSolid`), 곡선이면 표본 측점마다 단면을 이은 스윕(`helper/prism_member.py`, IFC `Tessellation`/IfcPolygonalFaceSet). 곡선 체적은 `curve_factor`(= (1/L)∫(1−κ·t)ds)로 보정.

## 3. 구조 (BIM 객체 패턴)

각 부재 종류는 **Data / Shape / Package / Engine** 패턴을 따른다. 엔진이 BIM 객체를 만들고, 그 객체가 3D DXF·2D 도면·IFC 의 **단일 데이터 원천**이다. 도면/IFC 코드가 따로 기하를 다시 계산하면 안 된다.

```
main.py                     GUI 진입점
config/                     모델·선형
  station_config.py         StationParameters (층별 높이/벽두께, floor_t/mid_t/roof_t, sta_tick, offset ...)
  master_config.py          StationProjectConfig (station/platform/column/align/openings + validate + 선형 접점)
  alignment*.py             Alignment 인터페이스, BP/EP 직선, HeadingAlignment
  curved_alignment.py       평면곡선(직선/원/완화곡선) + 종곡선, CubicSpiral(japaneseCubic)
  sampled_alignment.py      점열(xyz) 선형 (국소 2차 회귀 평활 + Hermite)
  alignment_text.py / alignment_landxml.py / alignment_io.py   txt/csv, LandXML(Civil 3D 실파일 검증), JSON 로더
walls/ slabs/ platforms/ columns/   각 부재: *_data.py, *_shape.py, *_package.py, *_engine.py
openings/                   슬래브 오프닝: kind, spec(입력), data(BIM), decompose(분해), opening_check(검증)
stairs/                     직선 계단: spec(입력), layout(단수·런/계단참·띠·자동 오프닝 계산), check(검증), data/shape/package/engine
escalators/                 에스컬레이터: spec(입력·형상 상수), layout(WP·부재 띠·위층 오프닝·하부 피트), check(검증·간섭), data/package/engine
helper/                     prism_member.py(각기둥/스윕 기하), strip_member.py(s 방향 띠 부재: 계단·에스컬레이터 공통), view_item.py(2D 윤곽), geometry_helper.py
engine/                     cad_engine.py(StationCADEngine: DXF 4종 + IFC), bim_engine.py(BIMEngine.build)
exporter/ifc_exporter.py    IFC4 내보내기 (storey별 포함, 재질, 오프닝 IfcRelVoidsElement)
gui/                        station_tab / platform_tab / column_tab / opening_tab / stair_tab / escalator_tab / print_tab (탭 1~7),
                            column_draft·opening_draft·stair_draft·escalator_draft(화면 비의존 입력 초안), tk_adapter(입력 → Config)
tests/                      test_patch, test_curved, test_sampled, test_landxml, test_openings, test_stairs, test_escalators, test_gui
samples/                    예제 선형(JSON/xyz/LandXML, 실제 Civil 3D 파일 포함)
```

2D 도면: 각 엔진이 `section_items(sta)`, `profile_items()`, `plan_items(cut_h)` 로 `ViewItem` 을 돌려주고 `cad_engine` 이 모아서 그린다.

## 4. 구현된 핵심 기능

- 선형: BP/EP 직선, 곡선(원·완화곡선·종곡선), JSON, xyz txt/csv(1m 간격 등), LandXML(축 NE/EN 자동 판정, 단위 변환, 다중 선형 선택). 정거장 구간이 선형 범위 안에 있는지, 곡선 반경이 외곽 폭에 비해 너무 작지 않은지 `validate()` 가 검사.
- 본체: 층별 층고 합산, 층별 외벽 두께, 3종 슬래브 두께(`floor_t`/`mid_t`/`roof_t`).
- 벽체(층별), 슬래브, 상대식 승강장(ㅠ형 슬래브 + 지지벽체), 중앙 기둥(층별·열별, 원/사각 혼합 패턴, 원은 지름 입력).
- **슬래브 오프닝(1단계)**: 직사각형만 (계단/에스컬레이터/엘리베이터/환기·설비). 오프닝이 있는 슬래브는 직사각형 조각(`SlabPiece`)으로 분해 — 슬래브는 여전히 BIM 객체 1개(`shape` = 뚫기 전 전체, `net_volume` = 순 체적). 슬래브·오프닝 검증: 내공 영역 안, 같은 슬래브에서 상호 비겹침, 기둥 비관통(`SlabEngine.check_columns`, 슬래브 k 는 k층·k+1층 기둥과 검사). 3D DXF·단면·종단·IFC(IfcSlab 1개 + IfcOpeningElement/IfcRelVoidsElement) 반영.
- **직선 계단(1단계)**: `StairSpec`(시작 층 k → k+1, 첫 단 STA + 오르는 방향 ±s, t 중심·폭, 단높이 상한·단너비·런 높이 상한·계단참 길이·슬래브 두께·머리 높이).
  - 단수 = 올림(실제 표고차 / 단높이 상한), 실제 단높이 = 표고차 / 단수 (종단구배 반영, 모든 단 동일). 디딤판·계단참 상면은 수평(절대 표고).
  - 한 런 높이 ≤ 런 높이 상한이 되도록 계단참 자동, 단수는 런마다 고르게. 최하층에서 계단 폭이 승강장 슬래브 안이면 승강장 상면에서 시작(걸치면 오류).
  - 위층 슬래브(번호 k)에 **머리 높이 부족 구간 ~ 도착 지점** 오프닝 자동 생성 (`cfg.all_openings()` = 수동 + 계단). 계산은 `stairs/stair_layout.py` 한 곳(검증·슬래브·계단 엔진 공유).
  - 형상 = s 방향 띠(`StairStrip`: 상면 수평, 하면 직선)의 연속. 곡선에서 경사 하면(비틀린 사각형)은 중심점 4분할 삼각형으로 작도해 체적 편차 제거.
  - 구조(일체형, 실무 도면 기준): 구조 상면선(디딤판 안쪽 모서리 선 / 계단참 상면)에서 **연직 두께 일정**(= 허리 두께 / cos)한 띠가 하면. 경사부·계단참의 상·하면이 같은 s 에서 꺾임 — 계단참 시작 쪽은 마지막 챌판 + 단너비, 끝 쪽은 다음 런 첫 챌판. 계단참 길이 ≥ 단너비.
  - 위층 도착: 마지막 챌판 위 **위층 바닥 높이 디딤판 1개까지 계단에 포함**(길이 = run + 단너비), 그 끝에서 위층 슬래브 상면과 같은 높이로 맞닿고 자동 오프닝도 그 점까지. 단높이는 그 맞닿는 점의 바닥 표고 기준.
  - 실무 도면은 구조 슬래브 위 계단연석(마감) 구조 — 현재는 일체형, 연석 분리는 이후 단계.
- **에스컬레이터(1단계)**: `EscalatorSpec`(시작 층 k → k+1, **하부 WP** STA + 오르는 방향, t 중심, 경사각 30°, 스텝 폭 1.0(S1000), 트러스 외폭 1.6·연직 높이 1.15(=피트 깊이), 하부/상부 연장 2.4/2.8, 평탄 스텝 2/3단, 스텝 깊이 0.4, 핸드레일 높이 1.0, 머리 높이 2.3 — 모두 입력 가능).
  - 스텝 코 선 N(u): 하부 WP 앞은 시작면(FL 또는 승강장 상면), WP 사이 경사선, 상부 WP 뒤 위층 바닥면. 상부 WP = 경사선이 위층 바닥(구배 반영)과 만나는 점.
  - 부재(모두 띠 부재): 트러스(N − 높이 ~ 스텝 아래/덮개판=바닥면), 스텝(경사 디딤판 수평·앞 코가 N 위, 평탄 스텝은 바닥면, 하면 N − 단높이 − 0.1), 난간 패널 좌/우(N ~ N + 핸드레일 높이 − 0.08), 핸드레일 좌/우(0.08×0.08). 세부 상수는 `escalator_spec.py`.
  - 자동 오프닝: 위층 슬래브(번호 k) = 트러스가 슬래브를 지나는 구간 ∪ 머리 높이 부족 구간 ~ 트러스 상단 끝. 하부 피트 = 트러스 하면이 시작면 아래인 구간 → 아래 슬래브(k−1) 오프닝, **피트가 슬래브보다 깊으면 오류**(바닥 내린 피트는 이후 단계). 승강장 위면 승강장 슬래브에 구멍(`cfg.platform_holes()`, `PlatformData.pieces/openings`), 지지벽체와 겹치면 오류.
  - IFC: `IfcTransportElement`(ESCALATOR) ⊃ 트러스·스텝 `IfcBuildingElementPart`, 난간 `IfcRailing`(BALUSTRADE), 핸드레일 `IfcRailing`(HANDRAIL). 승강장 IfcSlab 에도 IfcOpeningElement.
  - 검증: 치수·층·내공 범위, 트러스 폭 ≥ 스텝+난간, 같은 층 에스컬레이터·계단끼리 비겹침, 서 있는 슬래브의 다른 오프닝 위 금지(계단도 피트 위 금지), 시작 층 기둥 비관통.
  - IFC: `IfcStair`(STRAIGHT_RUN_STAIR) ⊃ `IfcStairFlight` + `IfcSlab`(LANDING), IfcStair 만 시작 층 storey 에 포함. 평면도는 최하층 계단만 표시.
  - 검증: 층 범위·치수·내공 범위, 같은 층 계단끼리 비겹침, 서 있는 슬래브(k−1)의 오프닝 위 금지, 시작 층 기둥 비관통(자동 오프닝은 k·k+1층 기둥 검사).
- 출력: 3D DXF, 횡단면도, 평면도(직선=전개, 곡선=WCS), 종단면도, IFC4.

## 5. 테스트 작성 규약

- 회귀: 직선 기본 출력은 **golden hash**(`tests/test_curved.py::GOLDEN_STRAIGHT`)로 고정. 기하 규약을 의도적으로 바꿀 때만 갱신하고, 왜 바뀌었는지 커밋 메시지에 남긴다.
- 체적은 공식 ↔ 3D 메쉬(발산 정리) ↔ IFC 형상(ifcopenshell) 세 가지를 서로 교차 검증하는 방식. 곡선 메쉬 허용오차는 `rel=1e-4`.
- GUI 테스트는 `tkinter` + 디스플레이 필요 (`xvfb-run -a`). tk 변수(`StringVar` 등)는 **반드시 속성/딕셔너리에 보관** — 지역 변수로 두면 GC 되어 `trace` 가 사라진다 (실제로 겪은 버그).
- 테스트에서 직접 `set_kind()` 같은 초안 메서드를 호출하면 화면 위젯(콤보박스)은 갱신되지 않는다 (실제 입력에서는 위젯이 초안을 바꿈).

## 6. 앞으로 할 일 / 미결 사항

**사용자 확인이 필요한 것 (미답변)**
1. 평면도에 오프닝을 표시해야 하는가? 현재 평면도는 최하층 FL+2m 에서만 자르므로 위층 슬래브 오프닝이 안 보임. 층별 평면도(층마다 해당 슬래브의 오프닝 외곽을 점선 등으로 표시)가 필요한지.
2. 실무 도면의 오프닝 표기 기준 — 지금은 `시작 STA + 길이`, `t 중심 + 폭`. 도면이 STA 범위 + 선로 중심 이격으로 되어 있으면 입력 항목을 맞춘다.

**제안 (사용자 확정 전, 우선순위 참고용)**
- 층별 평면도 생성(오프닝·기둥·벽·승강장). 위 1번 답에 따라.
- 오프닝 위에 실제 계단/에스컬레이터/엘리베이터 BIM 객체 배치 (용도별 IfcStair/IfcTransportElement 등) — "본격적인 정거장 구현"의 다음 단계.
- 오프닝 IFC 속성(Pset: 용도, 치수) 추가, 오프닝 간 최소 이격/벽체 이격 검증 규칙.
- 승강장 슬래브·지지벽체와 바닥 슬래브 오프닝의 간섭 검사 (현재 기둥만 검사).
- 오프닝 입력 저장/불러오기(JSON), GUI 입력 전체 프로젝트 파일화.

- 계단 2단계 후보: U자(꺾임) 계단, 엘리베이터 객체, 계단 위 난간, 층별 평면도에 계단·에스컬레이터 표시.
- 에스컬레이터 2단계 후보: 바닥을 내린 피트 구조(슬래브보다 깊은 피트), 상·하부 곡선 전이부, 핸드레일 끝 곡선(뉴얼), 실무 도면 제원 반영.

**알려진 정리 항목**
- `gui/gui.py` 는 어디서도 import 하지 않는 옛 파일이며 pyflakes 경고(`ColumnParameters` 미정의) 1건이 있다.
- 문서 문자열 불일치: `columns/column_params.py` 의 `t_offset` 설명과 기둥 탭 안내문이 "오른쪽 +" 라고 쓰여 있으나, 실제 코드는 `t_offset` 을 그대로 `pos_y`(왼쪽 +)로 쓴다. 코드 동작이 기준이므로 문구를 "왼쪽 +" 로 정정하거나(권장) 의도를 사용자에게 확인할 것.
- 평면도에서 `PLAN_CUT_H` 가 최하층 기준 고정(2.0m).
- `tests/` 의 미사용 import 등 pyflakes 경고(기존).
- 패키지 폴더명 `boxes/`(원본은 `boxs/`) 등 원본 대비 이름 정리가 누적 패치에 포함되어 있음.

## 7. 작업 방식 (사용자 선호)

- 요청은 **단계별로 구현 → 테스트 → 산출물(zip + 누적 패치)** 순으로 진행했고, 사용자는 각 단계 결과를 확인한 뒤 "계속" 으로 다음 단계를 지시한다.
- 실무 도면 근거로 규약을 정정해 주는 경우가 많다 (내벽 고정, 내공 기준, STA 기준). 규약이 불분명하면 추측하지 말고 먼저 묻는다.
- 누적 패치는 `diff -ruN -x __pycache__ -x .pytest_cache a b` (a = 원본 폴더, b = 수정본)로 만들어 `patch -p1` 로 적용되게 한다.
- 변경 후에는 전체 테스트 + pyflakes(소스) 통과를 확인하고, 형상 변경은 독립 계산(공식·메쉬·IFC)으로 교차 검증한다.
