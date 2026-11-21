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

- 현재 기준 **테스트 1073개 통과** (GUI 135개 포함). 코드를 바꾸면 반드시 전체 테스트를 돌릴 것.
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

**부재 = 각기둥(prism)**: 벽체·슬래브·승강장·지지벽체는 `(s 구간)×(t 구간)×(연직 두께)` + 종단구배(`rise`). **3D 면은 모두 바깥 법선**(꼭짓점 반시계 — (s, t 왼쪽 +, z) 는 오른손 좌표계, `tests/test_curved.py::test_all_3d_objects_face_outward` 가 부재마다 부호 있는 체적 > 0 으로 검사. 예전 직선 각기둥 `create_sloped_box_faces_global` 은 안쪽을 향해 스케치업에서 뒷면이 보였음). 직선 선형이면 경사 각기둥 1개(DXF 6면, IFC `SweptSolid`), 곡선이면 표본 측점마다 단면을 이은 스윕(`helper/prism_member.py`, IFC `Tessellation`/IfcPolygonalFaceSet). 곡선 체적은 `curve_factor`(= (1/L)∫(1−κ·t)ds)로 보정.

## 3. 구조 (BIM 객체 패턴)

각 부재 종류는 **Data / Shape / Package / Engine** 패턴을 따른다. 엔진이 BIM 객체를 만들고, 그 객체가 3D DXF·2D 도면·IFC 의 **단일 데이터 원천**이다. 도면/IFC 코드가 따로 기하를 다시 계산하면 안 된다.

```
main.py                     GUI 진입점
config/                     모델·선형
  station_config.py         StationParameters (층별 높이/벽두께, floor_t/mid_t/roof_t, sta_tick, offset ...)
  output_config.py          OutputOptions (출력 탭: 성과물 선택, 평면 층·절단 높이, 종단 축, 단면 측점·연속 단면 + validate)
  master_config.py          StationProjectConfig (station/platform/column/align/openings + validate + 선형 접점)
  widening.py               구조물 확폭 WidenSpec + 층·쪽별 내공면/바깥면 폴리선(연귀) + 사다리꼴 분해(band) + 검증
  alignment*.py             Alignment 인터페이스, BP/EP 직선, HeadingAlignment
  curved_alignment.py       평면곡선(직선/원/완화곡선) + 종곡선, CubicSpiral(japaneseCubic)
  sampled_alignment.py      점열(xyz) 선형 (국소 2차 회귀 평활 + Hermite)
  alignment_text.py / alignment_landxml.py / alignment_io.py   txt/csv, LandXML(Civil 3D 실파일 검증), JSON 로더
walls/ slabs/ platforms/ columns/   각 부재: *_data.py, *_shape.py, *_package.py, *_engine.py
rooms/                      실(구획): spec(실·공통 설정·용도 목록), layout(층별 입력 실 + 기본 실, 경계 칸막이벽), check(검증·간섭), data/engine
finishes/                   건축 마감: clear(계단·ESC 와 벽 마감 표면: t 기준점·간섭 검사 — 이슈 #32), spec(용도별 마감표 FinishType·FinishSettings·계단 마감 StairFinish), layout(실별 바닥·벽·기둥/승강로 둘레·천장·천장틀 조각), gaps(계단·ESC 접지 구간·오프닝 둘레 마감), pocket(확폭 사다리꼴 실), check(마감표 검증), engine
signs/                      사인: spec(StationInfo·SignSettings), nameplate(역명판·안내사인 이미지 — 스타일 등록부 + 그리기 함수, Pillow), layout(측벽 역명판·타는 곳·출구 배치 + 검증), engine
railings/                   오프닝 유리난간: spec(RailingSettings), layout(계단·ESC 오프닝 둘레 경계석·POST·레일·유리 조각 + 검증), engine
smokewalls/                 입구 천장 제연경계벽: spec(SmokeBarrierSettings·head_drop), layout(오프닝 입구 가장자리 프레임·유리 조각), engine
psds/                       스크린도어: spec(PsdSettings), layout(열차 문마다 유닛·POST·구동부·채움 패널 조각 + 검증), engine
trains/                     열차: spec(CarDoor·Car·Train·TrainStop·TrainSettings), layout(선로별 차량·문 위치 + 검증)
tactiles/                   점자블록: spec(TactileSettings·TactilePathSpec), layout(자동 점형·유도 경로 → 층별 겹치지 않는 평면 사각형 + 검증), engine
openings/                   슬래브 오프닝: kind, spec(입력), data(BIM), decompose(분해), opening_check(검증)
stairs/                     직선 계단: spec(입력), layout(단수·런/계단참·띠·자동 오프닝 계산), finish(계단 마감: 경사 슬래브 + 계단석), enclosure(옆 벽체·하부 창고 = 자동 실), check(검증), data/shape/package/engine
escalators/                 에스컬레이터: spec(입력·형상 상수), layout(WP·부재 띠·위층 오프닝·하부 피트), check(검증·간섭), data/package/engine
elevators/                  엘리베이터: spec(승강로·카·문 입력), layout(정지 바닥·피트/천장 채움·출입구·슬래브 오프닝), check(검증·간섭), data/engine
passages/                   출구통로: spec(경로 꼭짓점 입력), layout(경로 해석·연귀·부재 조각·측벽 오프닝), check(검증·간섭), data/package/engine
ventilations/               환기구: spec(연속박스 단면·그릴 입력), layout(수직구·칸별 오프닝·그릴 조각), check(검증·간섭), data/engine
entrances/                  출입구: spec(입력·구역 폭), layout(지표 EL 기준 자동 계산: 박스·계단·에스컬레이터 띠, EntranceFrame), check(검증), data/engine
helper/                     prism_member.py(각기둥/스윕 기하), strip_member.py(s 방향 띠 부재: 계단·에스컬레이터 공통), box_piece.py(세계 좌표 곧은 압출 조각 + 연귀 끝단·평면 절단: 출구통로), view_item.py(2D 윤곽), geometry_helper.py, trap_region.py(사다리꼴 영역 불 연산·경계·덩어리: 확폭 실·마감)
engine/                     cad_engine.py(StationCADEngine: DXF 4종 + IFC, build_*_doc = 저장 없는 DXF 문서), bim_engine.py(BIMEngine.build)
preview/                    preview_render.py(미리보기 작도, 화면 비의존: DXF 문서 → matplotlib 2D, 3DFACE → 3D 면·잘라 보기), pick.py(평면 위치 선택: PickRequest/PickSession·스냅·명령줄 좌표)
exporter/ifc_exporter.py    IFC4 내보내기 (storey별 포함, 재질, 오프닝 IfcRelVoidsElement)
exporter/dae_exporter.py    텍스처 3D 모델 COLLADA(.dae, 스케치업 둘러보기용) — render_material.py(보기 재질·텍스처 목록)
exporter/web_viewer.py      3D 웹 뷰어(three.js HTML 한 파일) + web_viewer_template.html(뷰어 HTML·JS), assets/web/three.min.js(r147, MIT), live_viewer.py(실시간 갱신 로컬 서버)
assets/image/tile/          텍스처 이미지(metal_panel·granite·ceiling_panel·stair_stone·tactile_*·Polished Concrete New 등, **저장소에 포함** — 출처·라이선스는 README) + README
assets/image/light/, mep/   나중 조명(light_on/off)·설비 디퓨저(diffuser) 텍스처 (아직 코드에서 안 씀)
gui/                        station_tab / platform_tab / column_tab / room_tab / finish_tab / opening_tab / stair_tab / escalator_tab / elevator_tab / passage_tab / entrance_tab / vent_tab / tactile_tab / print_tab / sign_tab (탭 1~15, 제목은 짧게 '1.선형' …, 창 폭 680),
                            column_draft·room_draft·finish_draft·opening_draft·stair_draft·escalator_draft·elevator_draft·passage_draft·entrance_draft·vent_draft·tactile_draft·train_draft·psd_draft·sign_draft·print_draft(화면 비의존 입력 초안), tk_adapter(입력 → Config), project_file(프로젝트 저장/불러오기, 화면 비의존), preview_window(미리보기 창 + 선택 모드), pick_fill(고른 점 → 초안 값, 화면 비의존), pick_buttons(탭의 [선택] 버튼 공통)
tests/                      test_patch, test_curved, test_sampled, test_landxml, test_openings, test_rooms, test_finishes, test_stairs, test_escalators, test_elevators, test_passages, test_entrances, test_vents, test_project_file, test_output_options, test_preview, test_dae, test_tactile, test_train, test_psd, test_signs, test_passage_branch, test_widening, test_widening_phase2, test_web_viewer, test_stair_finishes, test_railings, test_stair_enclosure, test_smoke_barriers, test_stair_clearance, test_gui
samples/                    예제 선형(JSON/xyz/LandXML, 실제 Civil 3D 파일 포함)
```

2D 도면: 각 엔진이 `section_items(sta)`, `profile_items(t_cut=0)`, `plan_items(cut_h, floor=1)` 로 `ViewItem` 을 돌려주고 `cad_engine` 이 모아서 그린다.
`plan_items` 의 cut_h 는 **본체 FL(z=0) 기준 절대 높이**(= `floor_level(n)` + 층 FL 기준 절단 높이) — 벽·기둥은 높이로, 계단·에스컬레이터·통로·출입구는 `floor` 로 층을 고르고 승강장은 최하층만. `profile_items(t_cut)` 은 선형 중심에서 t_cut 떨어진 연직면 절단(잘리면 해치, 아니면 측면 윤곽).

## 4. 구현된 핵심 기능

- 선형: BP/EP 직선, 곡선(원·완화곡선·종곡선), JSON, xyz txt/csv(1m 간격 등), LandXML(축 NE/EN 자동 판정, 단위 변환, 다중 선형 선택). 정거장 구간이 선형 범위 안에 있는지, 곡선 반경이 외곽 폭에 비해 너무 작지 않은지 `validate()` 가 검사.
- 본체: 층별 층고 합산, 층별 외벽 두께, 3종 슬래브 두께(`floor_t`/`mid_t`/`roof_t`).
- **지표 EL(정거장 공통)**: `StationParameters.ground_el`(절대 표고, None = 지표 없음 — 평탄 지표 하나). 1.선형 탭 '지표 EL'(비우면 없음). 쓰는 곳: 수직구로 끝나는 환기구 상단(= 지표 + `VentSpec.protrusion`), 출입구(`EntranceSpec.ground_el` 이 None 이면 공통값, 둘 다 없으면 오류). 본체 토피 검사·지형 자료는 아직 없음.
- **구조물 확폭(1단계: 구조, `config/widening.py`, `cfg.widenings`)**: `WidenSpec`(쪽 +1 = +t / −1 = −t, 적용 층(비면 모든 층), 완전 확폭 구간 `s_start`~`s_end`(None = 시점·종점 끝까지, 단부 벽도 넓어짐), 확폭량, 시작/끝 사선 전이 길이(None = 확폭량 = 45°, 0 = 직각 계단)). 실무 도면 사례: ESC 구간 국부 확폭(사선 전이), 정거장 끝까지 넓어지는 구간. 벽 밖 엘리베이터·특별피난계단 박스는 '본체 밖 구조물' 단계에서.
  - **종류 `WidenSpec.kind`**: `clear` = 내공 확폭(내공면이 이동, 아래 설명) | `wall` = **벽체 두께 증가**(내공면 고정, 벽 바깥면만 W/2 + 벽 두께 + e(s), 전이부는 바깥면만 사선 — 실무 ESC 구간 사례). 바깥면 = `outer_polyline` = 내공면을 띄운 선과 두께 증가 선의 위 포락선(`_envelope`). `wall` 은 측벽·단부 벽·바닥/천장 슬래브 외곽·위층이 두꺼워질 때의 중간 슬래브 받침만 바뀌고 내공(승강장·실·마감·검사)은 그대로 — 승강장은 `clear` 만(`specs_for(..., kind)`). 같은 층·쪽은 종류가 달라도 겹치면 오류. GUI 확폭 표 '종류' 칸(내공 확폭 | 벽체 두께).
  - 내공면 |t| = W/2 + e(s) 폴리선(`inner_polyline`), 벽 바깥면 = 그 폴리선을 벽 두께만큼 **수직 간격**으로 띄운 폴리선(`offset_polyline`, 꺾임점 연귀 — 사선 벽도 같은 두께, 직각 계단은 계단 벽), 두 폴리선 사이를 s 구간마다 아래·위가 직선인 **사다리꼴**로 분해(`band`). 부재 조각 `SlabPiece.trap = (t0, t1 @ s 시작, t0, t1 @ s 끝)`(None = 직사각형) — `prism_member` 가 `t_range_at`(보간)·`rings`·`mesh_faces`(사다리꼴은 스윕)·`section_rect` 에서 처리, `t_range` 는 양 끝을 모두 담는 범위, 체적은 평균 폭(정확).
  - 측벽: 확폭이 있는 층·쪽은 `WallData.pieces` = 사다리꼴 조각(`_widen_sides`), 단부 벽은 그 단부의 넓어진 바깥면까지(`outer_at`). 측벽 오프닝(통로·환기구)은 직사각형 조각에서만 — 사선 전이부에 걸리면 오류.
  - 슬래브(확폭이 하나라도 있으면 모든 슬래브를 조각으로): 바닥 = 최하층 바깥면 사이, 천장 = 최상층 바깥면 사이(단부 벽 포함 s −w ~ L + w), **중간 = 아래층 내공(아래층 확폭 포켓의 천장 포함) + 위층이 더 넓은 확폭 구간에서 아래층 바깥면 ~ 위층 바깥면**(`mid_slab_traps`, '넓은 층을 덮고 받침' — 위층 확폭 벽을 받침, 아래층 벽은 슬래브를 지나 올라가 그 자리는 뺌). 오프닝은 직사각형 조각에서만(사선 전이부 = 오류). 단면·종단은 조각별.
  - 승강장(최하층 확폭): 그 쪽 승강장 슬래브를 넓어진 내공면까지, 벽체측 지지벽체는 내공면을 따라 안쪽으로 지지벽 두께(사다리꼴 조각). IFC 승강장 지지벽도 조각이면 조각 형상.
  - 3D·IFC: 사다리꼴 조각은 면 집합(직선 선형도). 스윕 면 방향은 Newell 법선으로 판정(`_outward` — 한쪽 끝 폭 0 인 삼각 조각에서 첫 두 변 외적이 0 이 되어 면이 안쪽을 향하던 문제). 평면도는 확폭이 있으면 벽 조각마다 다각형. 곡선 선형 반경 검사에 최대 확폭량 포함.
  - 검증 `check_widenings`: 쪽·층·확폭량 > 0·전이 ≥ 0, 끝 > 시작, 전이부가 내공 시점·종점 밖이면 오류(끝까지 넓히려면 비움), 같은 층·쪽 확폭 구간(전이 포함) 겹침 오류.
  - GUI: 1.선형 탭 '구조물 확폭' 표(쪽·종류·층(B2F 또는 1 = 최하층, 쉼표)·시작/끝 STA·확폭량·전이(시작/끝)), `WidenDraft`, 프로젝트 파일 `widen_drafts`. 줄마다 [선택] = 미리보기 평면에서 **지금 보는 층**의 시작·끝 두 점(새 선택 종류 `LINE`: 두 점, s 가 달라야, 직교 모드 적용) → 층(그 평면 층 이름)·시작/끝 STA(작은 쪽이 시작)·쪽(두 점 t 평균 부호). `PickRequest.floor = 0` 이면 평면 층을 바꾸지 않고, 선택이 끝나면 미리보기가 `request.floor` 에 그때 보던 층을 넣음.
  - **2단계(넓어진 내공 활용)**: 내공 확폭(`clear`)이 있는 층만 새 경로(없으면 예전 코드 그대로). 영역 연산은 `helper/trap_region.py`(조각 `(s0, s1, lo0, hi0, lo1, hi1)`, s 를 조각 경계·선 교차점에서 잘라 띠마다 구간 연산 — 정확, `subtract/intersect/union/merge/groups/boundary/contains`). `widening.clear_traps`(넓어진 내공), `inner_range/inner_min`, `clear_contains_rect`, `on_inner_face`, `platform_ranges`(승강장 슬래브 t 범위를 벽 쪽으로 넓힘), `has_pockets`.
    - 실(`room_layout._layout_pocket_floor`): 실의 ±t 변이 그 s 구간 어디서나 닿는 내공면(`inner_min`) 위면 그 쪽은 본체 벽 → **실이 포켓까지 넓어짐**(맞닿은 실에 합침, 다른 입력 실 자리는 뺌), 나머지 = 기본 실(덩어리마다). 포켓 안 직사각형 실도 가능(넓어진 내공 안이면). `RoomLayout.traps`(영역 사다리꼴, `rects` = 외접 사각형), `region()`, `contains()`. 내공면 붙임도 그 실 s 구간의 `inner_min` 기준. 포켓까지 넓어진 실의 ±s 변 칸막이벽은 넓어진 내공면까지(사선이면 사다리꼴 조각 — 칸막이벽 조각 7번째 원소 = trap, 문은 사각 조각에만). 범위 검사 = 넓어진 내공.
    - 마감(`finishes/finish_pocket.py`, 사다리꼴 실만): 바닥·천장 = 영역 연산, 본체 측벽 벽 마감 = 내공면 폴리선을 이격·마감 표면 거리로 띄운 띠(`side_bands`, 사선 벽도 같은 이격·두께, 연귀) ∩ 실 영역, 칸막이벽·단부 벽 마감은 예전 규칙(측벽 띠에 닿는 끝은 넓혀 띠에서 끝남). 조각 `(…, z0, z1[, trap])`, `room_piece(..., trap)` / `RoomPiece.trap`. 점자블록 마감 대체도 사다리꼴. 검증: 바닥 = 내공 다각형 면적, 천장 = 마감 표면만큼 안으로 띄운(연귀) 다각형 A − P·d + d²Σcot(α/2), 벽 = 두 띄운 다각형 차 × 높이 (독립 공식) + 메쉬·IFC.
    - 범위 검사: 계단·ESC(시작 층 내공), 오프닝(슬래브 k → k층, 바닥 슬래브 → 최하층), 점자 유도 경로 꼭짓점, 승강장 위 판정(계단·EV·사인).
    - 통로·환기구: 첫 꼭짓점 = 그 자리 벽 바깥면 `outer_at`(내공 확폭·벽체 두께 증가 모두, t 비우면 자동), 아래층 벽 턱 = 두 층 바깥면 차, 위층 바깥면이 더 바깥이면 천장 슬래브 겹침 오류(`upper_wider`).
    - 역명판: 넓어진 내공면(− 마감 표면), 판 폭 안에서 내공면이 곧지 않으면(사선 전이부·계단) 건너뜀. 출구 사인도 넓어진 내공면 기준.
    - 평면 사다리꼴 조각 윤곽 = `PM.plan_item`(ViewItem 의 기운 아래·위 변). `prism_member._outward` 는 Newell 법선.
    - 남은 단순화: 미리보기 스냅의 내공면 선은 확폭 전 값, 승강장 평면 윤곽에 포켓 경계선이 보임, 사선 전이부 끝의 1mm 정도 연귀 자투리 조각.
- 벽체(층별), 슬래브, 상대식 승강장(ㅠ형 슬래브 + 지지벽체), 중앙 기둥(층별·열별, 원/사각 혼합 패턴, 원은 지름 입력).
- **실(구획) 1단계**: 마감을 실별로 다르게 적용하기 위한 선행 단계. `RoomSpec`(층, 용도, s 범위 × t 범위 = **칸막이벽 중심선**, 이름) + `RoomSettings`(층별 기본 실 용도 — 없으면 최하층 승강장층·그 위 대합실, 칸막이벽 두께 0.2, 재질 Masonry_Block). 용도는 `ROOM_USES` 목록 또는 직접 입력.
  - 층마다 내공 영역에서 입력 실을 뺀 나머지 = 기본 실(직사각형 조각들, `decompose.subtract_rects`). **나머지가 입력 실로 끊겨 여러 덩어리면 덩어리마다 기본 실**(`connected_groups`: 변을 길이 > 0 공유하면 연결, 꼭짓점만 닿으면 따로, 이름 `{층}_{용도}{k}` — 하나면 번호 없음, s 순). 실끼리 겹치면 오류, 내공 밖이면 오류.
  - **내공면 자동 붙임**(`snap_to_clear`, `StationProjectConfig.validate` 가 맨 앞에서(계단·ESC 오프닝이 실 천장 높이를 찾기 전) `cfg.rooms` 를 정규화): 실의 각 변이 자기 쪽 내공면(s0 → 0, s1 → L, t0 → −W/2, t1 → +W/2)에서 경계 벽 두께(구획분리면 sep_t, 칸막이벽이면 공통 두께, 최소 칸막이벽 두께) 이내면 내공면으로 — 안쪽·바깥쪽 모두. 실무 샘플(내공 ±10.1 에 ±10 입력)에서 본체 벽에 붙은 얇은 벽과 0.1m 자투리 기본 실이 생기던 문제. 붙여서 크기가 0 이하가 되면 원래 값(검증이 알림). 실 탭 안내문에 '(내공면에 붙임: t1 10→10.1)' 표시.
  - 칸막이벽: 입력 실의 변 중 본체 벽(내공면) 위가 아닌 부분, 같은 선은 합쳐 한 번만, 중심선 양쪽 반 두께. s 방향 벽(t 일정)은 끝을 반 두께씩 늘리고 t 방향 벽에서는 s 방향 벽 띠를 뺌(모서리 중복·빈틈 없음). 높이 = 층 FL ~ 위 슬래브 하면, 최하층 승강장 슬래브 위(t 범위)는 승강장 상면부터. 이름 `PW_{층}_S{k}/T{k}`.
  - 실·칸막이벽 조각 = 선형 각기둥(`helper.prism_member`, 하면이 종단을 따름, 곡선 스윕). 3D DXF 는 칸막이벽만(STRUCT_PARTITION), 횡단 SEC_PARTITION·종단 PROF_PARTITION(해치), 평면 PLAN_PARTITION + 실 이름·면적 글자(PLAN_ROOM, 윤곽 없음 — `ViewItem(pts=[])` = 글자만).
  - IFC: 실 = `IfcSpace`(INTERNAL, LongName = 용도, 면 집합) → IfcRelAggregates 로 층 storey, 칸막이벽 = `IfcWall`(PARTITIONING, 재질) → 층 storey 포함.
  - 검증: 형식·층·용도·크기(> 칸막이벽 두께)·내공 범위, 같은 층 실 겹침, 이름 중복, 칸막이벽이 서 있는 슬래브(층−1)의 오프닝 위 금지(계단·에스컬레이터·엘리베이터 자동 오프닝 포함), 그 층에서 오르는 계단·에스컬레이터·그 층을 지나는 엘리베이터 승강로와 겹침 금지. 기둥과는 겹쳐도 허용(벽 속 기둥).
  - **구획분리(2단계)**: 실마다 경계 종류 `boundary` = `partition`(칸막이벽, 공통 두께) | `separation`(구획분리, 두께 `sep_t`: 0 = 두께 없는 가상 경계선, > 0 = 얇은 실제 벽). 예) 대합실 PAID 구역을 구획분리로 넣고 그 층 기본 실을 복도로 → 나머지가 복도.
    - 선(같은 s 또는 같은 t)마다 구간별로 종류를 정함: 칸막이벽이 우선, 구획분리끼리는 두꺼운 쪽. 같은 종류·두께로 이어지는 구간은 합침. 벽(두께 > 0)은 칸막이벽과 같은 모서리 규칙, 가상선은 `SeparationLineLayout`(층 FL 높이의 선).
    - 이름 `PW_`(칸막이벽) / `SW_`(구획분리 벽) / `SL_`(가상선). 구획분리 벽 = IfcWall(PARTITIONING, Description "구획분리벽", 재질 Separation_Panel), 가상선 = **IfcVirtualElement**(Axis/Curve3D 폴리선, 층 storey). 3D DXF STRUCT_SEPARATION, 평면 PLAN_SEPARATION(벽 윤곽 / 2점 선). 가상선은 오프닝·계단 검사 제외(공간만 나눔).
  - **문(3단계)**: `RoomSpec.doors` = `DoorSpec`(실의 변 `+s/-s/+t/-t`, 중심 — ±s 변이면 t·±t 변이면 s(GUI 는 STA), 폭 0.9·높이 2.1, 종류 여닫이·양개 여닫이·미닫이·방화문 → IFC OperationType). 그 변의 벽 조각(칸막이벽·두께 있는 구획분리 벽)에서 벽 평면 (접선, z) 으로 개구부를 빼고(`_cut_doors`, 문 위 인방 조각 유지) 닫힌 문짝(두께 0.05, 벽 중심) 생성. 벽 조각 하나의 접선 범위 안이어야 함(다른 문·승강장 끝 높이 변화에 걸치면 오류), 실 변의 끝 벽 반 두께 안쪽, 문 높이 < 벽 높이, 본체 벽 변·가상 경계선 변 불가.
    - IFC: 개구부 IfcOpeningElement(DOOR) → 벽 IfcRelVoidsElement, 문짝 **IfcDoor**(OverallWidth/Height, OperationType, 방화문 재질 Steel) → IfcRelFillsElement, 층 storey. 3D DXF STRUCT_DOOR, 횡단 SEC_DOOR·종단 PROF_DOOR(윤곽), 평면 PLAN_DOOR = 실 안쪽으로 연 문짝 + 호(여닫이, 양개는 반폭 둘), 미닫이는 실 쪽 벽면의 문짝. 평면도 칸막이벽은 절단 높이를 지나는 조각만(문 위 인방은 안 보여 문 자리가 비어 보임).
  - `decompose.subtract_rects` 는 구멍을 영역 안으로 잘라 쓴다(영역 밖 구멍이 엉뚱한 조각을 만들던 문제 수정).
- **건축 마감(1단계)**: `FinishSettings(enabled, table)` = 용도별 마감표(`FinishType`: 바닥 `ffl`(구조 바닥 → 마감면)·`floor_t`(마감재)·`floor_fill`(mortar 채움 | void 빈 공간=액세스 플로어)·재질, 벽 `wall_t`(마감재 두께, 0 = 면처리, 형상 없음)·`wall_face`(구조체 면 → 마감 표면 거리, None/빈칸 = wall_t 즉 이격 없음, 이격 = face − wall_t 빈 공간·하지재 미모델링)·**`partition_face`(칸막이벽·구획분리 벽 면 → 마감 표면, 비우면 이격 없음 — 본체 측벽의 큰 이격과 따로, 사용자 지적: 실무 샘플 승강장층 wall_face 0.5 가 칸막이벽에도 0.45 이격을 만듦. `FinishType.pface/pgap`, 마감 탭 '칸막이 마감면', IFC Pset `PartitionFinishFace`)**·재질, 천장 `ceiling`·`ceiling_h`(마감면 → 천장판 하면)·`board_t`·재질·`frame`(M/T)·`bar_spacing`·`carrier_spacing`·바/캐링 단면). 실은 용도 이름의 종류를 쓰고(없으면 '기본') `RoomSpec.finish` 로 덮어씀. 기본 마감표(`default_finishes`)는 예시값 — 기계·전기·공조실 콘크리트 면처리 + 천장 없음, 통신실 액세스 플로어 FL+0.45, 대합실·승강장층·복도·역무실·통로·기타·기본은 **금속패널 T1.6 + 구조면→표면 0.15**(실무 상세 WB-14), 화장실 타일은 이격 없음. **모델 기본은 끔(`enabled=False`, 기존 출력·golden 유지), GUI 는 켬.**
  - 배치(`layout_room_finishes`, 정거장 로컬 사각 조각 → 선형 각기둥 `RoomPiece`): 기준 바닥 = 층 FL, 최하층은 승강장 슬래브 위(t 범위)만 + 기준 = 승강장 상면(선로부 바닥·벽 마감 없음, 천장 높이 기준도 승강장 상면).
    - 바닥: 실 영역 ∩ 기준 바닥 − (칸막이벽·사각 기둥·승강로·그 층 계단/에스컬레이터 **접지 구간**·아래 슬래브 오프닝). 마감재 + (mortar 면) 채움. 접지 구간(`finish_gaps.contact_rects`) = 부재 띠의 하면이 그 자리 바닥 마감면(선형 표고 + 시작면 + ffl)보다 낮은 s 구간 × 부재 t 범위 — 계단 경사부·ESC 트러스가 떠 있는 곳 아래 바닥은 마감(예전엔 평면 전체를 빼서 콘크리트가 보였음, 사용자 지적).
    - **오프닝 둘레(`finish_gaps.opening_linings`, 천장 있는 실, 위 슬래브 오프닝)**: 천장판이 오프닝 가장자리에서 끝나 천장 속이 보이던 문제 → 가장자리 바깥에 벽 마감 두께의 막이(천장판 하면 ~ 위 슬래브 하면, 그 자리는 천장판에서 뺌) + 오프닝 안쪽 슬래브 옆면 마감(슬래브 하면 ~ 상면). 계단·ESC 가 도착하는 쪽 가장자리는 없음, 옆면 마감은 부재 상면이 슬래브 하면보다 높은 s 구간에서 뺌(겹침 없음). 승강로(`_SHAFT`)·피트 오프닝 제외. 조각은 그 실의 WALL 마감(재질·레이어 FIN_WALL)에 더함. 계단 마감은 아래 '계단 마감' 참고(하부 마감은 아직 없음).
    - 벽: 실 경계(같은 실 조각 사이 제외) 중 본체 벽 내공면·칸막이벽/구획분리 벽 면에만 (가상선 없음), 마감재는 구조체 면에서 [face − wall_t, face] (직각 벽 마감은 서로의 이격 공간(`gap_rects`)에 들어가지 않아 모서리에서 마감 표면끼리 만남), 높이 = 마감면 ~ 천장판 하면(천장 없으면 위 슬래브 하면). 문·본체 측벽 오프닝(통로·환기구) 자리 비움. 모서리는 t 방향 조각에서 s 방향 조각을 뺌, 벽·기둥·승강로 평면과 겹침 제거.
    - 기둥 둘레(실 안, 사각 = 4조각, 원 = 외접 16각형 BoxPiece 연귀 고리), 승강로 바깥면(그 층을 지나는 엘리베이터, 출입구 자리 비움). 같은 이격(사각은 키운 사각형, 원은 반지름 + 이격).
    - 천장: 실 영역 ∩ 기준 바닥(**최하층은 승강장 위만 — 선로 구간 천장 마감 없음**, 사용자 확인) − (칸막이벽·사각 기둥·승강로·위 슬래브 오프닝 — **위층 에스컬레이터 하부 피트는 제외**, 트러스가 슬래브 두께 안에서 막으므로 아래층 천장은 그대로) − 벽·사각 기둥·승강로 **마감 표면까지**(`face_rects`; 바닥은 구조체 면까지 — 실무 상세). 천장판 + 천장틀(t 방향 바를 s 의 bar_spacing 원점 격자에, s 방향 캐링 채널을 t 의 carrier_spacing 격자에, 판 위로 바 → 캐링). 천장판 + 틀이 위 슬래브 하면을 넘으면 오류.
  - IFC: 실마다 IfcCovering(FLOORING 마감재·채움 / CLADDING 벽·기둥·승강로 / CEILING 천장판) + IfcMember(천장틀), IfcRelCoversSpaces → IfcSpace, 층 storey. IfcSpace 에 속성 세트 `SSBIM_SpaceFinish`(종류·재질·마감 높이·벽 마감 두께·`WallFinishFace`·`WallFinishGap`·천장 높이·천장틀). 곡선 선형의 얇은 마감 층은 면을 중심점 4분할 삼각형으로 내보냄(비틀린 사각 면의 분할 방향 차이로 IFC 체적이 어긋나는 것 방지).
  - 3D DXF FIN_FLOOR / FIN_WALL / FIN_CEILING / FIN_FRAME, 횡단 SEC_FINISH·종단 PROF_FINISH(윤곽), 평면 PLAN_FINISH(절단 높이를 지나는 벽·기둥 마감, 원기둥 둘레는 기둥 중심 기준 회전으로 로컬 좌표 — to_station 반복은 매우 느림).
  - **바깥 모서리(다른 실 모서리를 감싸는 반사각 꼭짓점, `_reflex`)**: 모서리를 돌아 이어지는 칸막이벽이 있으면 s 방향 마감을 모서리 너머(벽 반두께 + 마감 표면)까지, t 방향 마감은 그 뒷면(반두께 + 이격)까지 늘려 서로 만남(예전엔 틈, 사용자 지적). 이격 공간은 벽 끝까지만. 열린 끝(이어지는 벽 없음)은 끝막음이 맡음. 확폭 포켓 경로는 아직.
  - 알려진 단순화: 원기둥은 바닥·천장에서 빼지 않음(겹침), 천장 행거·액세스 플로어 받침 미모델링.
- **점자블록(1단계, `tactiles/`)**: `cfg.tactile_settings = TactileSettings`(모델 기본 끔 — 기존 출력 유지, GUI 13.점자 탭은 켬, 옛 프로젝트도 켬). 일반값 예시 기본값(실무 기준 받으면 교체).
  - 자동 점형(경고): 승강장 연단(최하층, 선로 쪽 끝단 |t| = D/2 + 끝단 거리에서 `edge_offset` 0.6 떨어져 폭 `edge_width` 0.6, s 0~L), 계단 첫 챌판 앞(`s_at(−clear−depth .. −clear)`)·위층 도착 뒤(`s_at(length + clear ..)`, 위층), 에스컬레이터 트러스 끝 앞·뒤(`u_range` 기준, 폭 = 트러스 외폭), 엘리베이터 정지층마다 문 앞(승강로 바깥면에서 `ev_clear`, 폭 = 문 폭 + 2 × 블록 크기, 관통형은 양쪽). 이격 0.3·깊이 0.6.
  - 유도 경로 `TactilePathSpec`(층, (s, t) 꼭짓점 = 블록 중심선, 폭 비우면 블록 크기 0.3): **선분은 s 또는 t 방향만**(사선 오류 — 미리보기 경로 선택은 직교 모드), 꼭짓점마다 점형 정사각형, 사이는 선형 띠. 최하층은 승강장 위만(선로 위 오류), 내공 범위 검사, 이름 중복 오류(비우면 TP{k}).
  - 겹침: 점형 우선, 같은 종류는 먼저 놓인 것 우선 → 층마다 서로 겹치지 않는 사각형(`TactileBlock`). 빼는 것: 칸막이벽·구획분리 벽, 사각 기둥(원기둥은 남김), 그 층을 지나는 승강로, 그 층에서 오르는 계단·ESC 평면, 아래 슬래브 오프닝. 최하층은 승강장 슬래브 t 범위로 자르고 기준 = 승강장 상면.
  - 높이: **바닥 마감이 있으면 그 마감재를 대체**(`layout_room_finishes(tactile=…)` 가 마감재 사각형에서 빼고 같은 z(마감면 − floor_t ~ 마감면)로 `RoomFinishLayout.tactile`/`RoomFinishData.tactile` — 몰탈 채움은 그대로), 마감이 없는 곳(마감 끔, 기계실 등 바닥 마감 없는 실)은 기준 바닥 위 `block_t` 0.03.
  - BIM: 층·종류마다 `TactileElementData`(이름 `TB_{층}_WARN|GUIDE`, 재질 `점자블록 점형|선형`, 조각 = RoomPiece 선형 각기둥, 곡선 스윕). 3D DXF FIN_TACTILE(미리보기 '바닥·벽 마감' 묶음), 횡단·종단 SEC_TACTILE(윤곽), 평면 PLAN_TACTILE(그 층 블록 윤곽, 절단 높이 무관), IFC `IfcCovering`(FLOORING, ObjectType = 재질 이름, 재질, 층 storey), 텍스처 DAE `tactile_warning`/`tactile_guide` 0.3×0.3(노란색).
  - 공용 도우미: `finishes.finish_engine.room_piece`(사각 조각 → RoomPiece), `column_footprints`(기둥 평면).
  - **승하차 위치 표시(2단계, 열차 연계)**: 열차를 쓰면 연단 경고블록 띠(같은 t 범위) 중 문 중심 ± `mark_width`/2(기본 1.8) 구간을 종류 `BOARD`(재질 `승하차위치표시`, 분홍, DAE 텍스처 `tactile_boarding`)로 — 우선순위 BOARD > 점형 > 선형. 요소 `TB_{층}_BOARD`, 평면도 PLAN_TACTILE 에 번호 글자 '차량-문'(`TactileEngine.labels`). 연단 경고블록을 꺼도 승하차 위치는 놓임(점자블록 탭은 켜져 있어야 함). 삼각형·번호판은 텍스처/평면 글자로만(형상 없음).
  - 다음 후보: 유도 경로 자동(출입구 → 개찰구 → 승강장), 사선 경로, 블록 줄눈에 맞춘 텍스처 원점, 실무 기준(연단 이격·띠 폭) 반영, 계단참 점형.
- **열차(`trains/`)**: `cfg.train_settings = TrainSettings(enabled, train, stops, mark_width)`(모델 기본 끔, GUI 2.승강장 탭 '열차' 묶음은 켬 — 옛 프로젝트도 켬). 사용자 정의 구조: `Train(cars)`·`total_cars`·`length`, `Car(length 20, doors, is_first)`(cars[0] = 선두), `CarDoor(offset = 차량 앞끝(진행방향)에서 문 중심, width 1.2)`. 기본 = 8량 × 20m, 문 4개 2.5/7.5/12.5/17.5 (예시, `default_doors` = 길이를 문 수로 고르게 나눈 칸 가운데). `make_train(n, 길이, doors, first_doors)` 는 선두 차량만 다른 문 배치 가능.
  - 정차 `TrainStop(track 'L'(t = +D/2) | 'R'(−D/2), direction ±1, front_s)`: **선두 정지 위치**(GUI 는 STA, 비우면 열차 중심 = 내공 중심). 기본 R 선로 +s, L 선로 −s. 각 선로의 승강장 = 같은 t 부호 쪽.
  - `layout_trains(cfg)` → `TrainPlacement`(차량별 앞·뒤 끝 s, `DoorPosition`(선로, 차량 번호(선두 1), 문 번호(차량 앞끝 1), 문 중심 s = 차량 앞끝 − direction × offset, 폭, `label` '차량-문')). 이후 스크린도어(PSD) 가동문도 이 문 위치를 쓸 예정.
  - 검증 `check_train`: 차량 1량 이상·길이·문 폭 > 0, 문이 차량 안·앞끝 기준 오름차순으로 안 겹침, 선로 L/R·중복, 방향 ±1, 정차한 열차가 내공 길이 안, 표시 폭 > 0.
  - GUI: 2.승강장 탭 '열차 (승하차 위치)' — 차량 수·길이·문 폭·표시 폭, 문 위치(쉼표)·선두 차량 문 위치(비우면 같음), 선로별 정차·진행방향·선두 STA. `TrainDraft`, 프로젝트 파일 `train_draft`.
  - 다음 후보: 평면도 열차 윤곽, 열차 3D(차체), 차종별 제원.
- **역명판·안내사인(`signs/`)**: `cfg.sign_settings = SignSettings`(모델 기본 끔, GUI **15.사인** 탭은 켬 — 옛 프로젝트도 켬). 창 폭 600 → 680 (탭 15개).
  - 역 정보 `StationInfo`(한글·영문·한자·일문 역명, 역번호, 노선색, `plus`/`minus` = +s(종점)·−s(시점) 방향 이웃 역 `StationRef`).
  - **이미지(`signs/nameplate.py`)**: 역명판 생성기(buttaiwan.github.io/eki)와 같은 구조 — 스타일 등록부 `STYLES`(`@define_style(id, 라벨, 쓰는 항목)`) + 공통 입력 `NameplateInput` + 스타일별 그리기 함수 → Pillow 이미지. 기준 단위 좌표·글자 크기를 `MASTER_SCALE`(3) 배로 그림, 글꼴은 운영체제 글꼴(맑은 고딕·Yu Gothic·MS YaHei·Arial, 없으면 Pillow 기본). **생성기 저장소에 라이선스가 없어 코드는 옮기지 않고 새로 작성**. 스타일: `seoul`(서울 지하철형 — 노선색 둥근 테두리·역번호 원·아래 띠에 ◀/▶ 이웃 역), `korail`(코레일형 — 짙은 녹색, 가운데 큰 역명·가로줄·영문/한자·아래 이웃 역). 안내사인: `render_boarding`(남색, ↓ 타는 곳 Platform + 방면), `render_exit`(노란 바탕, 검정 상자 출구 번호 + 출구 Exit + 목적지 3줄). 사인 크기 비율로 그림.
  - 배치(`layout_signs` → `SignPlacement`(중심 s, t(벽 부착은 뒷면), 앞면 법선(축 방향), 폭·높이·두께, 하단 z, 부착/매달림)):
    - 역명판 `NP_{L|R}_{k}`: 최하층 승강장 양쪽 뒤 측벽 — 면 = 내공면 − 벽 마감 표면 거리(`FinishType.face`), s = 내공 가운데에서 `plate_interval` 40 간격 대칭, 하단 = 승강장 바닥 마감면 + `plate_bottom` 2.0, 높이 `plate_h` 0.8·폭 = 이미지 비율, 두께 0.05. 측벽 오프닝(통로·환기구) 높이 구간과 겹치면 그 자리 건너뜀. 이미지 좌우 이웃 역 = 보는 사람 기준 실제 방향(+t 벽을 보면 오른쪽 = +s → 오른쪽 자리에 plus 역).
    - 타는 곳 `BD_{계단/ESC 이름}`: 승강장(1층)으로 내려가는 계단·ESC(lower_floor = 1)의 위층 도착 끝(계단 `length`, ESC `u_range[1]`) + `hang_offset` 1.5, 그 계단 t 중심, 앞면 = 오르는 방향(걸어오는 사람 쪽). 방면 = 계단 t 부호 쪽 선로(+t = L → `dest_l`). 하단 = 그 층 바닥 마감면 + `hang_bottom` 2.5, 2.4 × 0.45 × 0.1.
    - 출구 `EX_{통로 이름}`: 출구통로 측벽 접합부 중심 s, 측벽 면에서 `hang_offset` 안쪽, 앞면 = 정거장 안쪽. 번호·목적지 = `exit_info`(통로 이름별, 번호 비우면 통로 순번).
    - 높이 기준·천장은 그 자리 실의 마감표(`finish_at` / `floor_and_ceiling`: 바닥 마감면, 천장판 하면 또는 위 슬래브 하면). 검증: 치수·스타일, 사인 윗면 ≤ 천장, 내공 길이 안.
  - BIM `SignElementData`: 본체 판(STRUCT_SIGN) + 앞면 이미지 면(두께 2mm, STRUCT_SIGN_FACE), RoomPiece(종단구배 따름). 미리보기 '사인' 묶음, 횡단·종단 SEC_SIGN, 평면 PLAN_SIGN(윤곽 + 문구, 매달림 사인도 그 층에 표시), IFC `IfcBuildingElementProxy`(USERDEFINED, ObjectType SIGNAGE, Description = 문구, Pset `SSBIM_Sign` Kind·Text, 그 층 storey).
  - **텍스처 DAE**: 사인마다 이미지를 그려 `textures/sign_{k:03d}.png` 저장, 이미지 면에 **한 장을 맞춤**(`RenderMaterial.image` + `frame` = 왼쪽 아래·오른쪽·위쪽·폭·높이·구배 → `frame_uv`, 판이 종단구배를 따르므로 v 를 구배만큼 보정). 2D 도면·IFC 에는 이미지 없음(문구만).
  - 다음 후보: 양면 매달림 사인, 기둥 부착 역명판, 승강장 출구 안내·환승 안내, 사인 위치 직접 입력, 스타일 추가(부산·인천 등).
- **오프닝 유리난간(`railings/`)**: `cfg.railing_settings = RailingSettings`(모델 기본 끔, GUI **7.계단 탭** 맨 위 '오프닝 유리난간' 묶음은 켬 — 옛 프로젝트도 켬, 프로젝트 파일 `railing_draft`). 실무 사진 기준 단순 모델(사용자: 너무 상세할 필요 없음).
  - 대상: 계단 자동 오프닝(항상) + ESC 자동 오프닝(`escalators`). 난간은 **위층**(오프닝 슬래브 k → k+1층) 바닥, 오프닝 가장자리 바깥. 도착 쪽 가장자리 없음, 경계석이 내공면(벽)·내공 시점/종점 밖으로 나가는 가장자리 없음, 같은 슬래브 다른 오프닝과 겹치는 가장자리 없음(나란한 계단 사이는 난간 없음 — 단순화).
  - 부재(바깥 거리 e 띠, `band`: 모서리는 s 방향 가장자리 T0/T1 가 차지, t 방향 S0/S1 은 그 안쪽까지): 경계석 [0, curb_w] × 위층 구조 FL ~ 바닥 마감면 + curb_h — **ㅠ 형태**(실무, 사용자 지정): 윗면 화강석 석판 `plate_t`(폭 전체, 코드 CURB) + 양 옆 흑색 걸레받이 `skirt_t`(SKIRT, 재질 '흑색 걸레받이' = 텍스처 `Skirting` 0.8×0.2 타일) + 속채움(CORE, 몰탈), 각각 띠로 나눠 모서리 겹침 없음, POST(중심선 e = curb_w/2, 중심선 방향 post_w × 가로 post_d, 간격 ≤ post_spacing 고르게, 모서리는 post_d 정사각 1개, 경계석 위 ~ 마감면 + rail_h1), 유리(POST 사이 post_gap 띄움, 두께 glass_t, 경계석 위 glass_gap ~ rail_h1 − glass_top_gap), 파이프 레일 2개(정사각 단면 rail_d, POST 바닥 쪽 면에 붙음, 위 레일 윗면 rail_h1·아래 레일 중심 rail_h2). 마감면 = 위층 FL + 그 자리 실 `ffl`(`floor_ffl_at`, 마감 끄면 0).
  - 바닥 마감·점자블록은 경계석 자리를 뺌(`railing_footprints`). 유리 색 = `glass_rgb`(0~255)·`glass_alpha` — DAE·웹 뷰어 재질(`render_material.railing_glass_material`), 나머지는 부재 재질(화강석·스테인리스).
  - 출력: 3D DXF STRUCT_RAILING / STRUCT_RAILING_GLASS(미리보기 '계단·ESC·EV' 묶음), 횡단·종단 SEC_RAILING, 평면 PLAN_RAILING(그 층: 경계석 + 절단 높이를 지나는 POST·유리), IFC `IfcRailing`(GUARDRAIL) ⊃ 경계석 IfcBuildingElementPart(USERDEFINED CURB)·POST IfcMember(POST)·레일 IfcMember(USERDEFINED HANDRAIL)·유리 IfcPlate(CURTAIN_PANEL), 그 층 storey.
  - 다음 후보: 계단 옆 경량칸막이 벽체 + 뒤편 창고 문(사용자 예정), 원형 파이프 단면, 나란한 오프닝 사이 공유 난간, 계단 자체 핸드레일.
- **계단·ESC 옆 벽체 + 하부 창고(`stairs/stair_enclosure.py`)**: `cfg.enclosure_settings = EnclosureSettings`(모델 기본 끔, GUI 7.계단 탭 '계단 옆 벽체 · 하부 창고' 묶음은 켬 — 옛 프로젝트도, 프로젝트 파일 `enclosure_draft`). 실무 평면(계단·ESC 승강장 쪽 긴 옆면을 칸막이벽으로, 높은 쪽 아래는 기계실·창고) 기준.
  - **기존 실 기능을 그대로 씀**: 묶음마다 자동 실(`RoomSpec.auto = 'ENC:…'`)을 만들어 `cfg.rooms` 에 넣음 → 칸막이벽·문·마감·IfcSpace/IfcWall/IfcDoor 가 따라 나옴. `StationProjectConfig.validate` 가 처음에 자동 실을 지우고(`auto`), 계단·ESC 배치 직후 다시 만듦(두 번 검증해도 같음). 계단 시작 앞·도착 지점 실과 아래층 천장은 바뀌지 않아 계단 배치(디딤판·오프닝)는 그대로.
  - 묶음: 같은 층·같은 오르는 방향, s 구간 겹침, t 간격 ≤ `group_gap`(1.0) 인 계단·ESC — 사이는 막지 않음. 계단실 = 그 층 기본 실 용도(마감 같음), 앞(첫 챌판 쪽) = `RoomSpec.open_sides`(벽·가상선 없음), 노출된 긴 옆면 벽 중심선 = 묶음 t 끝 − 그 실 벽 마감 표면 거리 − 반두께(마감 표면이 계단 옆면에 닿음), 내공면에 가까우면 본체 벽. 벽 두께·재질 = 실 탭 칸막이벽.
  - 창고(`storage_use` 기본 창고 — 마감표 '창고' = 천장 없음·벽 면처리): 묶음 하면이 바닥 마감면 + `storage_h`(2.1) 이상인 첫 위치부터 높은 쪽 끝(+ 반두께 + 창고 마감면)까지, 경계 끝 벽 윗면 = 그 벽(+ 계단실 쪽 벽 마감) 구간의 부재 하면 최저(`RoomSpec.wall_tops` → 칸막이벽 조각 윗면 상한, 그 벽 면 벽 마감도 칸막이벽 윗면까지 — `finish_layout.part_top`). 문 = **뒷 벽(높은 쪽 끝) 가운데**(`door_at` 'back' 기본, 사용자 요청 — 뒷 벽이 본체 단부 벽이거나 폭이 모자라면 옆 벽) 또는 노출된 옆 벽 가운데('side', 계단 탭 '문 뒷 벽' 체크)(`door_w`×`door_h`). `min_storage` 보다 짧으면 창고 없이 계단실만.
  - **열린 벽 끝 끝막음(`finish_layout._wall_end_caps`, 모든 s 방향 칸막이벽)**: 다른 벽에 닿지 않고 끝나는 칸막이벽 끝(계단실 앞)은 벽 마감이 구조면에서 띄워 붙어(금속패널 0.15) 벽과 마감 사이 빈 공간이 두 겹처럼 보였음(사용자 지적) → 양쪽 마감을 벽 끝 + 마감 두께까지 늘리고 그 사이(벽 끝면 + 이격)를 끝 앞 실 마감재로 덮음. 모서리로 맞닿은 벽은 연결로 봄.
  - 칸막이벽·계단 간섭 검사(`room_check._below_member`): 벽 윗면이 그 자리 계단·ESC 하면 아래면 허용(끝 벽).
  - 만들지 않는 경우: 입력 실과 벽 두께 이내로 가깝거나 겹침, 엘리베이터 승강로와 겹침, 구조물 내공 확폭 층(포켓 경로 미지원).
  - 다음 후보: 확폭 층 지원, 문 위치·종류 입력, 창고 대신 실 용도 지정(기계실 등)을 계단마다, 이슈 #32(오프닝 둘레 막이와 이웃 계단).
- **입구 천장 제연경계벽(`smokewalls/`)**: `cfg.smoke_settings = SmokeBarrierSettings`(모델 기본 끔, GUI 7.계단 탭 '입구 천장 제연경계벽' 묶음은 켬 — 옛 프로젝트도, 프로젝트 파일 `smoke_draft`). 사용자 지정: **계단·ESC 입구 쪽만**(다른 사례는 오프닝 옆까지 있으나 옆은 계단 옆 벽체가 막음), 천장 아래 `depth` 0.6, 유리 + 위·아래 프레임, 유리 색 RGB.
  - 배치(`layout_smoke_barriers`): 계단(항상)·ESC(`escalators`) 자동 오프닝마다 입구 쪽 가장자리(계단 첫 챌판 `s_at(0)` / ESC `u_range[0]` 에 가까운 가장자리) 바깥에 진행방향 두께 `frame_d`, t 폭 = 오프닝 폭 전체, 위 = 그 자리 아래층 천장판 하면(`ceiling_bottom_under`, 천장 없거나 마감 끔이면 위 슬래브 하면), 아래 = 위 − depth. 위·아래 프레임(`frame_h`) + 가운데 유리(`glass_t`, 가운데).
  - **오프닝 연장(`smoke_spec.head_drop`)**: 켜면 계단·ESC 자동 오프닝의 머리 높이 기준을 depth 만큼 낮춤(`stair_layout`·`escalator_layout` 의 z_head) → 오프닝이 입구 쪽으로 길어져 경계벽 아래에서도 머리 높이 확보(ESC 는 `escalators` 일 때만).
  - 출력: 3D DXF STRUCT_SMOKE / STRUCT_SMOKE_GLASS(미리보기 '계단·ESC·EV' 묶음), 횡단·종단 SEC_RAILING, 평면 PLAN_RAILING(그 층, 매달림이라 절단 높이 무관), IFC `IfcCurtainWall`(USERDEFINED, ObjectType SMOKE_BARRIER) ⊃ 프레임 IfcMember(USERDEFINED FRAME)·유리 IfcPlate(CURTAIN_PANEL), 그 층 storey. DAE·웹 뷰어 유리 = 설정 색(`railing_glass_material(…, '제연 유리')`), 프레임 '알루미늄 프레임'.
  - 다음 후보: 오프닝 옆 경계벽(옆 벽체가 없는 경우), 측면 프레임·행거, 제연경계 폭 검사(법규).
- **스크린도어 PSD(`psds/`)**: `cfg.psd_settings = PsdSettings`(모델 기본 끔, GUI 2.승강장 탭 '스크린도어' 묶음은 켬 — 옛 프로젝트도 켬). **열차를 써야 함**(정차 선로마다 한 줄). 치수는 실무 입면 상세도(UNIT 4,800 = 고정부 1,350 | 가동문 1,050 × 2 | 고정부 1,350(한쪽 비상문 겸용), 문 높이 2,000 + 구동부 400) + 단면은 일반값 예시(POST 0.2×0.2, 구동부 깊이 0.35, 프레임 0.05×0.05, 하부 레일 0.1, 유리 8mm), 모두 입력.
  - 배치(`layout_psds`): 유닛 중심(두 가동문 사이) = 열차 문 중심. POST 는 유닛 양옆, 이웃 유닛 POST 가 같은 자리면(문 간격 = 유닛 + POST = 5.0, 기본 20m 4도어와 같음) 하나로 공유. 유닛 사이가 벌어지면 채움 고정 패널(한 장 ≤ `fill_max` 1.5, 여러 장이면 사이 POST) + 구동부, 열차 바깥은 없음. 내공 [0, L] 밖으로 나간 조각은 잘라냄(열차가 승강장 끝에 붙은 실무 샘플). 오류: 유닛 겹침(간격 < 유닛 폭), POST 일부 겹침(공유도 아니고 떨어지지도 않음), 채움 패널이 너무 좁음.
  - 위치: PSD 중심선 |t| = 승강장 끝단(D/2 + 끝단 거리) + `edge_offset` 0.3, 그 선로 승강장 쪽. 바닥 = 그 자리 실의 바닥 마감면(`platform_base`, 마감 끔·마감 없으면 승강장 상면). 연단 점자블록(끝단 + 0.6~1.2)과 겹치지 않음.
  - 부재(정거장 로컬 상자 → RoomPiece): 패널(고정부·가동문·채움) = 양옆 기둥·위 레일(frame_w)·하부 레일(kick_h) 프레임 + 가운데 유리, 구동부 = 문 위 header_h × header_d, POST = 바닥 ~ 구동부 위. 이름 `PSD_{선로}_{차량-문}_FIX_N/DOOR_N/DOOR_P/FIX_P/HEADER`, `PSD_{선로}_P{k}`, 채움 `F{k}`/`FH{k}`. 비상문 겸용 = `emergency` 쪽 고정부(+s/−s/없음). 문은 닫힌 상태. 전광판·표시등·패닉바·도어록은 생략.
  - 출력: 3D DXF STRUCT_PSD(프레임·POST·구동부) / STRUCT_PSD_GLASS(유리), 미리보기 '스크린도어' 묶음, 횡단·종단 SEC_PSD(윤곽), 평면 PLAN_PSD(최하층, 절단 높이를 지나는 조각), IFC 선로마다 `IfcElementAssembly`(PLATFORM_SCREEN_DOOR, 최하층 storey) ⊃ POST `IfcColumn` · 구동부 `IfcMember`(PSD_HEADER) · 가동문 `IfcDoor`(SLIDING_TO_LEFT/RIGHT) · 비상문 겸용 `IfcDoor`(SINGLE_SWING_LEFT) · 고정부/채움 `IfcPlate`(CURTAIN_PANEL), DAE 유리 반투명(`RenderMaterial.alpha` 0.3 → `<transparency>`).
  - 성능: 실무 샘플(12량 × 2선로, 유닛 96개) IFC 출력 약 8초 → 25초 (면 집합). 직선이면 압출 솔리드로 줄일 수 있음(후보).
  - 다음 후보: 가동문 열림 상태, 전광판·표시등·도어록·패닉바, 단부 고정벽(열차 바깥 ~ 승강장 끝), 승강장 끝 점검문, 실무 단면 상세 반영, IFC 압출 솔리드.
- **슬래브 오프닝(1단계)**: 직사각형만 (계단/에스컬레이터/엘리베이터/환기·설비). 오프닝이 있는 슬래브는 직사각형 조각(`SlabPiece`)으로 분해 — 슬래브는 여전히 BIM 객체 1개(`shape` = 뚫기 전 전체, `net_volume` = 순 체적). 슬래브·오프닝 검증: 내공 영역 안, 같은 슬래브에서 상호 비겹침, 기둥 비관통(`SlabEngine.check_columns`, 슬래브 k 는 k층·k+1층 기둥과 검사). 3D DXF·단면·종단·IFC(IfcSlab 1개 + IfcOpeningElement/IfcRelVoidsElement) 반영.
- **직선 계단(1단계)**: `StairSpec`(시작 층 k → k+1, 첫 단 STA + 오르는 방향 ±s, t 중심·폭, 단높이 상한·단너비·런 높이 상한·계단참 길이·슬래브 두께·머리 높이).
  - 단수 = 올림(실제 표고차 / 단높이 상한), 실제 단높이 = 표고차 / 단수 (종단구배 반영, 모든 단 동일). 디딤판·계단참 상면은 수평(절대 표고).
  - 한 런 높이 ≤ 런 높이 상한이 되도록 계단참 자동, 단수는 런마다 고르게. 최하층에서 계단 폭이 승강장 슬래브 안이면 승강장 상면에서 시작(걸치면 오류).
  - 위층 슬래브(번호 k)에 **머리 높이 부족 구간 ~ 도착 지점** 오프닝 자동 생성 (`cfg.all_openings()` = 수동 + 계단). 머리 높이 기준 = 위층 슬래브 하면, **마감을 켜면 아래층(k) 천장판 하면이 더 낮을 때 그 높이**(`finishes.finish_layout.ceiling_bottom_under`: 계단 평면과 겹치는 k층 실 중 천장 있는 실의 가장 낮은 천장판 하면, 천장 없는 실·마감 끔은 슬래브 기준) — 천장판·천장틀이 오르내리는 사람 머리에 걸리지 않게 구조 오프닝 자체를 키움(천장은 오프닝 자리에서 빠짐). 오프닝 폭 = 계단 폭 + 2 × `side_clear`(옆 여유, 기본 0). 계산은 `stairs/stair_layout.py` 한 곳(검증·슬래브·계단 엔진 공유).
  - 형상 = s 방향 띠(`StairStrip`: 상면 수평, 하면 직선)의 연속. 곡선에서 경사 하면(비틀린 사각형)은 중심점 4분할 삼각형으로 작도해 체적 편차 제거.
  - 구조(일체형, 실무 도면 기준): 구조 상면선(디딤판 안쪽 모서리 선 / 계단참 상면)에서 **연직 두께 일정**(= 허리 두께 / cos)한 띠가 하면. 경사부·계단참의 상·하면이 같은 s 에서 꺾임 — 계단참 시작 쪽은 마지막 챌판 + 단너비, 끝 쪽은 다음 런 첫 챌판. 계단참 길이 ≥ 단너비.
  - 위층 도착: 마지막 챌판 위 **위층 바닥 높이 디딤판 1개까지 계단에 포함**(길이 = run + 단너비), 그 끝에서 위층 슬래브 상면과 같은 높이로 맞닿고 자동 오프닝도 그 점까지. 단높이는 그 맞닿는 점의 바닥 표고 기준.
  - 실무 도면은 구조 슬래브 위 계단연석(마감) 구조 — 마감을 끄면 일체형, 켜면 아래 '계단 마감'(분리 구조).
  - **계단 마감(`stairs/stair_finish.py`, `FinishSettings.stair = StairFinish`, 마감 탭 '계단 마감' 묶음)**: 마감을 켜고 계단 마감을 쓰면(`stair_finish()`, 기본 사용 — 옛 프로젝트도) 계단을 **구조 + 계단석으로 분리**. 마감을 끄면 예전 일체형 그대로(golden 유지).
    - 디딤판 높이 = **아래층 바닥 마감면 ~ 위층 바닥 마감면**을 같은 단높이로 (`finishes.finish_layout.floor_ffl_at`: 첫 챌판 앞·도착 지점이 든 실의 `ffl`, 위층은 런 길이가 바뀌므로 반복). `StairLayout.base_level` 은 구조 시작면 그대로(접지·바닥 마감 계산), `finish_base` = 아래층 마감면. 오프닝 머리 높이 기준 슬래브 하면은 구조 FL 기준.
    - 구조 = **매끈한 경사 슬래브**: 상면 T(u) = min(마감 안쪽 모서리 선, 다음 면 높이) − `depth`(받침 두께), 하면 = T − 허리 두께/cos, 첫 런은 시작면 아래 잘라냄(상·하면 모두 max(바닥, …)). 꺾임 위치는 일체형과 같음(마지막 챌판 + 단너비). 상면이 기운 띠 = `Strip.zt1`.
    - 스텝(칸 = 디딤판·계단참·위층 도착 디딤판, 앞에 챌판): `plate` 판석(디딤판 `tread_t` 칸 전체 + 앞 챌판 `riser_t` [아래 디딤판 높이 ~ 디딤판 하면] + 나머지 채움 `fill_material`), `solid` 통석(칸 전체 돌 + 깔 몰탈 `bed`, 계단참은 판석), `concrete` 칸 전체 채움(재질 콘크리트). 첫 챌판 아래(아래층 마감면 아래)는 채움.
    - 논슬립: 칸마다 앞 코에서 `nosing_w` × (폭 − 2·`nosing_end`) × 상면에서 `nosing_t` — 맨 위 재료에서 그 자리를 빼고 끝 쪽은 따로 조각. 옆면: **노출된 쪽만**(`config.widening.inner_min` 내공면에 붙은 쪽 제외) 계단 폭 안쪽 `side_t`, **스텝(계단석·채움) 부분만** — 구조 상면 ~ 마감면(계단 모양), 스텝은 그만큼 좁아짐. **구조 슬래브 옆면은 콘크리트 노출**(사용자 지정, 실무 — 실제 지하철은 계단 옆 칸막이벽이 가림), 구조는 계단 폭 전체(`PartLayout.t_range` = 계단 폭).
    - 부재: `FinishPart(code TREAD/RISER/STONE/FILL/NOSING/SIDE, 재질, t 범위, 띠)` → `StairFinishData`(이름 `{계단}_FIN_{코드}_{k}`, `StairData.finishes`, `StairEngine.finish_elements()`). 3D DXF `FIN_STAIR`(미리보기 '바닥·벽 마감' 묶음), 횡단 SEC_FINISH·종단 PROF_FINISH(절단면 지나는 것만), IFC `IfcCovering`(디딤판·통석·채움 FLOORING, 챌판·옆면 CLADDING, 논슬립 USERDEFINED, 면 집합) → `IfcRelCoversBldgElements`(IfcStair), 층 storey. DAE·웹 뷰어 재질 = 부재 재질(논슬립·콘크리트 보기 재질 추가). **계단석 재질 기본 `계단석`**(바닥 화강석과 구분, 옆면은 화강석) — 텍스처 `stair_stone`(사용자 준비), **디딤판 윗면은 디딤판마다 이미지 한 장**(`StairEngine._tread_frames` → `StairFinishData.face_frames` 핸들 → (원점, u = +t, v = 앞 코 → 안쪽, 한 장 폭, 단너비), 폭은 `stone_len`(기본 1.2)에 가깝게 고르게 나눔, 이미지 아래쪽 = 앞 코, `dae_exporter.apply_tread_uv`/`tread_uv` 를 DAE·웹 뷰어가 공유). 계단참·챌판·연직 면은 일반 타일(0.6×0.6, 사용자가 이음매 없는 정사각 무늬로 교체).
    - 바닥 마감 접지 구간(`contact_rects`)·오프닝 옆면 마감은 계단 마감 부재도 포함(계단당 s 구간을 합쳐 계단 폭 사각형 하나). 검증: `StairFinish.check`(방식·0 이상·받침 > 디딤판/깔 몰탈·논슬립 깊이·디딤판 < 단높이), 옆면이 폭에 비해 큼.
    - 검증된 성질(테스트): 세 방식 모두 무작위 점에서 부재끼리 겹침·연직 빈틈 없음 + 맨 위 = 걷는 면, 체적 띠 공식 = 메쉬 = IFC(곡선 rel 1e-4).
    - 다음 후보: **계단·ESC 옆 칸막이벽으로 구조 옆면 가리기**(사용자 예정 — 실무 사진: 계단·ESC 옆을 벽체로 막음), 계단 하부 마감(천장판·도장), 계단 난간·핸드레일, 계단석 줄눈·분할, 에스컬레이터 마감(트러스 옆·하부 패널), 출입구 계단 마감.
  - **t 기준점·벽 마감 간섭(`finishes/finish_clear.py`, 이슈 #32 근본 원인 — 사용자 지적: 마감 간섭 검사가 없어 문제 개체가 조용히 생김, 중심 t 입력이라 벽 마감면까지 거리를 모름)**: `StairSpec.t_ref`·`EscalatorSpec.t_ref` = `center`(t = 중심) | `+t`/`-t`(t = 왼쪽·오른쪽 변) | `wall+t`/`wall-t`(t = 그 쪽 본체 벽 마감 표면에서의 이격 ≥ 0, 벽 쪽 변을 마감 표면에 맞춤). `StationProjectConfig.validate` 가 배치 전에 중심 t 로 풀어 `t_ref = center` 로 바꿈(`normalize_t_refs`, 두 번 검증해도 같음). 벽 마감 표면 `wall_surface` = 내공면(구간 최안쪽, 확폭 포함) − 그 벽에 붙은 실들(구간 1m 표본) 중 가장 큰 `FinishType.face`(마감 끔·벽 마감 없음 = 0). 계단·ESC 탭 't 기준' 콤보, 입력칸 이름 't 값', 미리보기에 '왼쪽 벽 마감면에서 0.1 띄움'.
    - 간섭 검사 `check_wall_clearance`(계단·ESC 배치 검사): 평면이 본체 측벽 벽 마감 표면 안쪽으로 들어가면 오류 + 들어간 거리(마감 켰을 때만). 실무 샘플 내부계단 #1~4·ESC 는 벽 마감면 0.5 안으로 0.4m 들어가 이제 오류 — 't 기준'을 벽 마감면으로 바꿔야 함. 칸막이벽 마감과의 검사는 아직(구조체 겹침만).
    - **계단 구간 벽 마감(#32 설계 2단계, 사용자 지적: 아래층 벽 마감은 천장에서 끊기고 위층까지 콘크리트)**: 계단·ESC 옆이 **본체 벽 마감 표면에 붙은 쪽**(`shaft_opening_t`: 변 ≥ 표면 − 1mm) 또는 **계단실 옆 칸막이벽 쪽**(`_partition_panel`: 계단 옆 벽체 켬·마감 켬, 그 쪽에 묶음 간격 이하로 이웃한 계단·ESC 없음)은 자동 오프닝을 **벽 마감재 두께만큼 그 쪽으로 넓힘**(본체 벽 = `wall_panel` 두께, 칸막이벽 = 그 층 기본 실 마감 두께). 그 띠(부재 변 ~ 오프닝 가장자리 × 오프닝 s 구간, `finish_layout.shaft_walls`)는 **계단 구간 패널 한 장**: 아래층 바닥 마감면(계단 시작 쪽 실) ~ 위층 바닥 마감면, 그 실 벽 마감재(`_shaft_panels` — 띠 자리의 기존 벽 마감·막이를 빼고, 문 자리는 비움, 칸막이벽(창고 끝 벽 — 계단 아래)이 띠를 가로지르는 자리는 그 벽 윗면부터: 예전엔 끝 벽 위로 세로 틈, 사용자 지적). 입구·끝 가장자리 막이는 패널과 s 로 맞닿아 그대로. 그 가장자리 오프닝 둘레 마감은 없고 입구·끝 가장자리 막이는 패널 자리를 뺌(`finish_gaps`). 예전 칸막이벽 쪽은 막이가 '오프닝 중심이 든 실'(창고 = 천장 없음)에서만 만들어져 아예 없어 콘크리트가 보였음.
    - 벽에 붙은 쪽 판단도 벽 마감 표면 기준: 계단실 옆 벽(`stair_enclosure`: 칸막이벽이 마감 표면 안쪽에 설 자리가 없으면 본체 벽 — 예전엔 마감 이격 안에 칸막이벽이 섬), 계단 옆면 마감 노출(`_exposed_sides`), 유리난간 가장자리(위층 마감 표면).
  - IFC: `IfcStair`(STRAIGHT_RUN_STAIR) ⊃ `IfcStairFlight` + `IfcSlab`(LANDING), IfcStair 만 시작 층 storey 에 포함. 평면도는 최하층 계단만 표시.
  - 검증: 층 범위·치수·내공 범위, 같은 층 계단끼리 비겹침, 서 있는 슬래브(k−1)의 오프닝 위 금지, 시작 층 기둥 비관통(자동 오프닝은 k·k+1층 기둥 검사).
- **에스컬레이터(1단계)**: `EscalatorSpec`(시작 층 k → k+1, **하부 WP** STA + 오르는 방향, t 중심, 경사각 30°, 스텝 폭 1.0(S1000), 트러스 외폭 1.6·연직 높이 1.15(=피트 깊이), 하부/상부 연장 2.4/2.8, 평탄 스텝 2/3단, 스텝 깊이 0.4, 핸드레일 높이 1.0, 머리 높이 2.3 — 모두 입력 가능).
  - 스텝 코 선 N(u): 하부 WP 앞은 시작면(FL 또는 승강장 상면), WP 사이 경사선, 상부 WP 뒤 위층 바닥면. 상부 WP = 경사선이 위층 바닥(구배 반영)과 만나는 점.
  - 부재(모두 띠 부재): 트러스(N − 높이 ~ 스텝 아래/덮개판=바닥면), 스텝(경사 디딤판 수평·앞 코가 N 위, 평탄 스텝은 바닥면, 하면 N − 단높이 − 0.1), 난간 패널 좌/우(N ~ N + 핸드레일 높이 − 0.08), 핸드레일 좌/우(0.08×0.08). 세부 상수는 `escalator_spec.py`.
  - **상세 형상 1단계(`escalators/escalator_geom.py`, 사용자: ESC 를 개략형상에서 완전 개조 — 4단계 중 1)**: 스텝 코 선 `NoseLine` = 아래층 바닥 → **하부 곡선 전이**(오목, `lower_radius` 1.0) → 경사선 → **상부 곡선 전이**(볼록, `upper_radius` 1.5) → 위층 바닥. 전이부 = WP 에서 만나는 두 직선(바닥은 WP 기울기로 근사 — 종단구배)에 접하는 원호(필렛), 0 이면 예전 꺾임. 띠 부재(트러스·난간·핸드레일)는 전이부를 `ARC_STEP` 0.05 로 따라 자름(`escalator_part_strips(extra_us, steps_range)`).
    - **스텝 개별 객체**(애니메이션 대비, 위 운행로만 — 사용자 선택): 스텝 k 코 u_k = 첫 스텝 + k·스텝 깊이(수평), 코가 N 위·디딤판 수평(`step_pose(nose, u, dep)` → (디딤판 윗면, 아래 스텝과 높이차)), 형상 `step_pieces` = 디딤판 판(`STEP_PLATE_T`) + 앞 챌판 판(`STEP_RISER_T` 0.03, 아래 스텝 디딤판 높이 ~ 디딤판 하면) — 이웃 스텝과 겹침 없음, u 를 옮겨도 같음. 스텝 범위 = 평탄부 끝(전이 시작/끝) ± 평탄 스텝 수, 트러스보다 길면 오류. `EscalatorLayout.steps`(StepLayout)·`nose`, BIM `EscalatorStepData`(이름 `{ESC}_STEP001…`, `chain_u`), 예전 `STEPS` 띠 부재는 없어짐(출입구 에스컬레이터는 예전 형상 그대로). IFC 스텝마다 `IfcBuildingElementPart`(USERDEFINED, ObjectType STEP, Pset `SSBIM_EscalatorStep` Index·ChainU, 면 집합) ⊂ IfcTransportElement. 3D DXF STRUCT_ESCALATOR, 종단 스텝마다 윤곽, 평면 스텝 범위 사각형. ESC 탭 '하부/상부 전이 반경'.
    - **2단계 난간·데크·스커트**(정거장 상세 형상만 — 출입구 ESC 는 예전 난간 패널): 단면(스텝 가장자리 → 바깥) 틈 `SKIRT_GAP` · 스커트 `SKIRT_T`(트러스 상면 ~ 코 선 + `skirt_height`) · 안쪽 데크(스커트 안쪽 면 ~ 유리, 폭 `deck_width`, 두께 `DECK_T`) · 유리 난간(`glass_t`, 데크 위 ~ 핸드레일 아래) · 바깥 데크(유리 ~ 트러스 바깥, 데크와 같은 높이), 핸드레일은 유리 위 가운데(`spec.detail_t`). 부재 종류 SKIRT / INNER_DECK / OUTER_DECK(좌·우), 유리는 레이어 `STRUCT_ESC_GLASS`(반투명 '에스컬레이터 유리'), IFC IfcBuildingElementPart(USERDEFINED, ObjectType 종류)·유리는 IfcRailing BALUSTRADE. 검사: 트러스 외폭 ≥ 스텝·스커트·데크·유리 + 0.01, 스커트 높이가 핸드레일에 비해 큼. ESC 탭 '스커트 높이·데크 폭·난간 유리 두께'. 난간·데크는 아직 스텝 구간만(끝 뉴얼·승강구 쪽 마감은 3·4단계).
    - 다음 단계: 3 핸드레일 고리·뉴얼, 4 승강구(바닥판·콤) + 트러스 외장 마감.
  - 자동 오프닝: 위층 슬래브(번호 k) = 트러스가 슬래브를 지나는 구간 ∪ 머리 높이 부족 구간 ~ 트러스 상단 끝. 머리 높이 기준은 계단과 같이 아래층 천장판 하면(마감 켬, 더 낮을 때), 폭 = 트러스 외폭 + 2 × `side_clear`. 하부 피트 = 트러스 하면이 시작면 아래인 구간 → 아래 슬래브(k−1) 오프닝, **피트가 슬래브보다 깊으면 오류**(바닥 내린 피트는 이후 단계). 승강장 위면 승강장 슬래브에 구멍(`cfg.platform_holes()`, `PlatformData.pieces/openings`), 지지벽체와 겹치면 오류.
  - IFC: `IfcTransportElement`(ESCALATOR) ⊃ 트러스·스텝 `IfcBuildingElementPart`, 난간 `IfcRailing`(BALUSTRADE), 핸드레일 `IfcRailing`(HANDRAIL). 승강장 IfcSlab 에도 IfcOpeningElement.
  - 검증: 치수·층·내공 범위, 트러스 폭 ≥ 스텝+난간, 같은 층 에스컬레이터·계단끼리 비겹침, 서 있는 슬래브의 다른 오프닝 위 금지(계단도 피트 위 금지), 시작 층 기둥 비관통.
- **엘리베이터(1단계, 정거장 내부)**: `ElevatorSpec`(최하·최상 정지층 = 그 사이 모든 층 정지, **카 정지층 1개**(카가 서 있는 위치), 승강로 내공 중심 s·t, 내공 2.4×2.4, 벽 0.3, 문 방향 ±s/±t + 관통형, 문 0.9×2.1, 피트 1.5 + 피트 슬래브 0.6, 오버헤드 4.0 + 천장 슬래브 0.3, 카 1.6(문 면과 나란)×1.5×2.3, 카 바닥 0.1·벽/문 0.05·천장 0.1).
  - 모든 부재 = 정거장 로컬 상자(띠 1개, `helper.strip_member`), 절대 표고는 승강로 중심 s 의 FL 기준(연직·수평, 구배 안 따름). 정지 바닥 = 층 FL, 최하층에서 승강로 외곽이 승강장 슬래브 안이면 승강장 상면(걸치면 오류).
  - 승강로 벽 = 피트 바닥 상면(최하 정지 − pit_depth) ~ 최상 정지 + overhead. 문 쪽 벽(관통형이면 반대쪽도)은 정지층마다 출입구를 뺀 조각(`decompose.subtract_rects`). 벽 코드 `WALL_PS/NS/PT/NT`(+s/−s/+t/−t 면, s 면 벽이 외곽 t 폭 전체).
  - **승강로가 지나는 본체 슬래브·승강장 슬래브는 외곽 크기 오프닝**(`cfg.all_openings()` 에 `{이름}_SHAFT`, `cfg.platform_holes()`). 피트 슬래브 하면 / 천장 슬래브 상면이 뚫린 슬래브 두께 안에서 끝나면 그 슬래브 면까지 늘려 채움(내린 피트). 천장 슬래브가 본체 천장 하면을 넘으면 오류, 피트가 아래층 바닥에 닿으면 오류.
  - 카: 내공 중심, 카 바닥 상면 = 카 정지층 정지 바닥. `CAR_FLOOR/CAR_ROOF`(카 외곽), `CAR_WALL_PS/NS/PT/NT`(문 쪽은 문 자리 비운 조각), `CAR_DOOR_*`(닫힌 문 패널, 벽 + 문 = 닫힌 벽).
  - IFC: `IfcElementAssembly`(USERDEFINED, ELEVATOR) ⊃ IfcWall(승강로)·IfcSlab(BASESLAB 피트, ROOF 천장)·`IfcTransportElement`(ELEVATOR, 카) ⊃ IfcBuildingElementPart(바닥·벽·천장) + IfcDoor. 출입구 = IfcOpeningElement(ELEVATOR_DOOR) → 승강로 벽 IfcRelVoidsElement. 형상은 모두 면 집합(세계 좌표), 최하 정지층 storey.
  - 2D: 횡단 = 승강로 해치(SEC_CONCRETE, merge) + 카 윤곽(SEC_ELEVATOR), 종단 = 축이 지나면 절단(카는 PROF_ESCALATOR 레이어), 아니면 승강로 외곽 1개(PROF_BEYOND), 평면(PLAN_ELEVATOR) = 정지층마다 외곽·내공·X 기호, 카 정지층에 카 외곽.
  - 검증: 층 범위·최하 < 최상·카 층 범위·문 방향·치수, 카 외곽 ≤ 승강로 내공(문 면 기준), 문 ≤ 카, 피트 ≥ 카 바닥, 오버헤드 ≥ 카 높이 + 천장, 출입구 높이 ≤ 층 내공, 엘리베이터끼리·계단·에스컬레이터와 평면 겹침(같은 층), 슬래브 오프닝 검사(내공 범위·다른 오프닝과 겹침·기둥 관통), 승강장 지지벽체 겹침.
- **출구통로(경로 입력)**: `PassageSpec`(층, `path` = 통로 중심선 폴리선 꼭짓점 목록, 내공 폭·높이 4.0×3.0, 벽·바닥·천장 0.6, 상부 헌치 0.3×0.3·하부 헌치(기본 없음)).
  - 꼭짓점 `PathVertex(mode, x, y, z)`: **꼭짓점마다** 좌표 방식 선택 — `station` = 선형 상대 (s, t, 접합부 FL 기준 높이), `world` = 절대 (X, Y, EL). GUI 는 통로마다 한 방식(STA 로 입력해 s 로 변환), 모델은 혼용 가능(향후 큰 UI 대비).
  - 절대 좌표 해석을 위해 `StationProjectConfig.to_station(x, y)`(to_world 의 역변환, 수선의 발 탐색)를 둠. 선형 접점은 여전히 config 하나.
  - 첫 꼭짓점 = 그 층 외벽 바깥면 위 접합점(|t| = W/2 + 벽 두께, 1mm 허용), 첫 구간은 본체에 직각(바깥쪽). 첫 높이는 비우면 FL, 주면 FL 과 같아야 함(5mm). **첫 꼭짓점(선형 상대) t 를 비우면(`PathVertex.y = None`) 외벽 바깥면에 자동**(측벽 = 두 번째 꼭짓점 t 부호) — 벽 두께를 바꿔도 따라감. 다른 꼭짓점·절대 좌표는 비울 수 없음.
  - **아래층 외벽이 더 두꺼우면**(`passage_layout.lower_ledge` = 아래층 − 그 층 벽 두께): 아래층 벽 상단(= 그 층 FL)이 바깥으로 나온 턱과 첫 구간 바닥 슬래브(FL − 바닥 두께 ~ FL)가 겹치므로 **첫 구간 바닥 슬래브를 턱 폭 뒤부터** 시작(겹친 부분은 벽 체적, 턱 위는 벽 상단이 바닥). 하부 헌치(FL 위)·벽·천장은 그대로. 첫 구간이 턱보다 짧으면 오류. 직선 근사(곡선 선형에서 벽 바깥면의 휨·벽 상단 종단구배는 무시). 위층 외벽이 더 두꺼워 천장 슬래브와 겹치는 경우는 여전히 오류.
  - **T자 분기(`PassageSpec.parent` = 부모 통로 이름, 여러 단계 가능)**: 자식 통로의 첫 꼭짓점은 부모 측벽 바깥면에 자동 — 부모 구간 = 첫 꼭짓점(t 를 비우면 두 번째 꼭짓점)에 가장 가까운 구간, 접합점 = 두 번째 꼭짓점에서 그 구간에 내린 수선의 발 + 부모 외곽 반폭(첫 구간이 늘 부모에 직각, side = 부모 진행방향 왼쪽 +1). 층·접합부 바닥 = 부모(입력 층 무시), 높이 기준(선형 상대 z) = 분기점 부모 바닥. `layout_passages` 가 부모 먼저(`_branch_order`, 순환·자기 자신·없는 부모 오류) 배치하고 `cut_branch_opening` 으로 부모 그 구간의 WALL_L/R 조각을 자식 내공 폭 × 내공 높이만큼 잘라 앞·뒤 조각 + 위 인방(`local['lintel']`)으로 나눔. 결과 순서는 입력 순서. 분기 통로는 `wall_opening = None`(본체 측벽 개구부 없음, `cfg.wall_openings()`·출구 사인 제외), 아래층 벽 턱 처리 없음, 층 내공·외벽 간섭 검사는 부모가. 오류: 분기하는 부모 구간이 경사, 두 번째 꼭짓점이 부모 외곽 안, 개구부가 부모 구간 측벽 범위(연귀 포함) 밖, 자식 내공 높이 > 부모. 출입구는 분기 통로 끝에도 붙음. GUI: 통로마다 '분기' 콤보(본체 | 다른 통로 이름), `PassageDraft.parent`. 분기 위치(두 번째 꼭짓점의 수선의 발)가 부모 구간 밖이면 '수선의 발이 구간 밖' 오류.
  - **끝 폐합 옵션(`PassageSpec.close_end`, 통로 탭 '끝 폐합' 체크, 기본 끔)**: 켜면 경로 끝 [L − 벽 두께, L] 에 끝 벽 `S{run}_END`(좌우 벽 사이 × 바닥 상면 ~ 내공 높이, 마지막 구간 구배, IfcWall), 헌치 삼각 조각은 끝 벽 앞까지. 자동 판단 없음(사용자 요청 — 처음 만든 '분기 근처면 자동으로 자르고 늘여 폐합'은 되돌림). 오류: 출입구가 붙은 통로, 마지막 구간이 끝 벽보다 짧음, 분기 개구부가 끝 벽과 겹침(늘여야 할 길이를 알려 줌 — 분기 바깥 벽 면까지 늘리면 맞음).
  - GUI: 콤보박스 위 휠이 값을 바꾸고 `<<ComboboxSelected>>` 를 보내던 ttk 기본 동작을 앱 시작 때 지움(`unbind_class('TCombobox', '<MouseWheel>')`) — 스크롤하다 분기·층 선택이 몰래 바뀌던 문제.
  - 높이는 꼭짓점 사이 직선 보간: 같으면 수평, 다르면 경사. 평면 일직선 꼭짓점 = 경사 변화점(직각 끝으로 조각 분할).
  - 꺾이는 꼭짓점: **임의 각도(≤135°), 이등분선 연귀 접합**. 단면 v 위치에서 앞 구간 끝 = L − v·tan(δ/2), 뒤 구간 시작 = v·tan(δ/2) (δ = 왼쪽 + 회전각). **꺾임 앞뒤 구간은 수평이어야 함**(아니면 오류). 연귀는 재료를 더하거나 빼지 않아 벽 체적 = 2·벽두께·H·중심선 길이.
  - 부재는 평면 직선 구간(run, 꺾임마다 증가)별: `S{run}_FLOOR/ROOF/WALL_L/WALL_R` (L = 진행방향 왼쪽). 헌치는 천장/바닥 슬래브에 포함. 끝단 개방.
  - 형상 = `helper/box_piece.py` BoxPiece(연직 단면 × 수평 축 + 구배, 끝단 비스듬함 ks/ke). IFC: 직각 끝 조각만이면 IfcExtrudedAreaSolid(압출 방향 (0, 구배, 1)), 연귀가 있으면 그 부재는 IfcPolygonalFaceSet(평면 면, 정확).
  - 본체 측벽 오프닝: 그 층 측벽(t 부호로 찾음, +t = 벽 코드 R)을 s–z 면에서 첫 꼭짓점 s ± 내공 폭/2 × FL ~ FL+내공 높이로 조각(`WallData.pieces/openings`) 분해, IFC 는 IfcWall 조각 + IfcOpeningElement(PASSAGE).
  - 2D: 횡단면도는 측점 sta 의 연직면(선형 접선이 법선)으로 조각을 **정확히** 자른 다각형(`BoxPiece.cut_by_plane`), 평면도는 최하층 통로 벽 평면을 to_station 으로 옮긴 다각형(WCS 평면도에서는 꼭짓점을 그대로 되돌림). 종단면도에는 그리지 않음.
  - IFC: `IfcElementAssembly`(USERDEFINED, EXIT_PASSAGE) ⊃ run 별 `IfcSlab`(FLOOR/ROOF) + `IfcWall`, 통로가 붙는 층 storey 에 포함.
  - 검증: 꼭짓점 2개 이상·형식, 치수·헌치, 접합점·직각·첫 높이, 같은 위치 꼭짓점, 꺾임각, 꺾임부 수평, 연귀에 비해 짧은 구간, 경로 자기 겹침(이웃 아닌 구간), 측벽 오프닝이 내공 길이 안, 내공 높이 ≤ 층 내공 높이, 위층 외벽 간섭(아래층은 바닥 슬래브를 잘라 허용), 첫 구간 ≥ 아래층 벽 턱, 통로끼리 겹침.
- **출입구(1단계)**: `EntranceSpec`(이어 붙일 통로 이름, **지표 EL**, 계단 폭 1.75 + 칸막이벽 0.2 + 에스컬레이터 구역 3.31(좌/우 선택, 없앨 수 있음), 벽·슬래브 두께 0.8 하나, 헌치 0.3, 하부/상부 여유 1.0, 파라펫 0.3, 계단·에스컬레이터 제원, `stair_offset`(비우면 자동)). 실무 도면(외부출입구 종단·단면) 기준.
  - 통로 마지막 꼭짓점 = 이음면, 마지막 구간 방향이 출입구 u 축(`EntranceFrame`: 세계 좌표 원점 + 방향, t 왼쪽 +). 높이 Zp(통로 끝 바닥) → G(지표 EL).
  - 에스컬레이터: 하부 WP = 벽 + 하부 여유 + 하부 연장, 상부 WP = Zp ~ G 를 경사각으로. 박스 바닥 = 트러스 하면을 따라감(하부·상부 피트 포함, 하부 수평부 = 이음면 ~ 피트 끝).
  - 계단: 별도 슬래브(`stair_part_strips` 공유) + 칸막이벽(바닥 ~ 계단 슬래브 하면). 계단이 바닥 아래로 가면 **시작점을 하부 수평부 쪽으로 자동으로 앞당김**(이분법, 0 이하 `stair_offset` 로 수동 지정 가능), 하부 수평부 끝까지 당겨도 안 되면 오류. 상부 도착 계단참은 끝 벽까지 연장.
  - 천장: 에스컬레이터와 나란한 직선. 하면 = max(통로 내공 높이, 코 선 + c), c = 에스컬레이터 머리 높이 2.3·천장 아래 계단 머리 높이 2.1 을 모두 만족하는 최소값. **천장 상면이 지표에 닿는 점에서 끝**, 그 뒤는 개구부(측벽 = 지표 + 파라펫, 끝 벽). 헌치는 천장 구간별 BoxPiece.
  - 부재: FLOOR_S/FLOOR_E, ROOF, WALL_L/R, END_WALL_S/E, JOINT_WALL_L/R(통로보다 넓을 때 이음면의 바깥쪽), PARTITION, 계단 `{EN}_STAIR_*`, 에스컬레이터 `{EN}_ESC_*`. 모두 프레임 위 띠 부재(`helper/strip_member`), 한쪽 끝 높이 0 인 띠는 `_degenerate_faces`.
  - IFC: `IfcElementAssembly`(USERDEFINED, ENTRANCE) ⊃ IfcSlab(FLOOR/ROOF)·IfcWall·IfcStair(⊃ Flight/Landing)·IfcTransportElement(⊃ 부재), 통로 층 storey. 띠 = s–z 사각형을 t 로 압출(IfcExtrudedAreaSolid).
  - 2D: 횡단면도에서 정확히 자름(`cut_faces_by_plane`), 평면도는 통로가 최하층일 때 외곽만. 종단면도에는 그리지 않음.
  - 지표 EL 은 출입구마다 입력, 비우면(GUI 기본 빈칸) 정거장 공통 지표 EL.
  - 검증: 통로 존재·통로당 1개, 치수, 내공 폭 ≥ 통로 내공 폭, 에스컬레이터 구역 ≥ 트러스 외폭, 지표가 통로 바닥보다 충분히 높음(토피), 계단 바닥 위.
- **환기구(1단계)**: `VentSpec`(층, `path` = 출구통로와 같은 PathVertex, **n련 연속박스**: 련 수 4·칸 내공 2.5×3.0·바깥 벽 0.6·중벽 0.4·바닥/천장 0.6·칸마다 상부 헌치 0.3, 수직구 깊이(비우면 칸 높이), 그릴 두께 0.1·테두리 0.1·살 0.03·간격 0.1).
  - 경로 해석은 출구통로의 `resolve_vertices(…, what="환기구")` 그대로(첫 꼭짓점 = 외벽 바깥면(t 비우면 자동), 첫 구간 직각·수평, 꺾임 연귀·앞뒤 수평). 아래층 외벽이 더 두꺼우면 첫 덕트 바닥 슬래브를 턱 폭 뒤부터(출구통로와 같음). 칸 v 구간은 오른쪽(−v) 칸부터, 단면 = FLOOR·ROOF·WALL_L/R·MID{k} (+헌치는 ROOF).
  - **수직 구간** = 평면 위치 같고 높이만 다른 연속 두 꼭짓점(위로만, 연속 금지, 앞뒤 덕트 수평). 기존 출구통로는 수직 이동을 지원하지 않음(같은 평면 위치 = 오류) — BoxPiece 를 상자(축 u × 단면 v·z)로 써서 수직구를 표현.
  - 수직구 접합(실무식): 수직 꼭짓점 = 수직구 내공 중심, 아래 덕트 방향 u 로 깊이 D. 아래 덕트는 내공이 +D/2 까지 → 끝 벽(END_E, 바닥 하면~천장 상면), 천장은 [L−D/2, L+D/2] 에서 칸 자리만 비움(벽 위 띠만, 헌치 없음). 수직구 = 아래 천장 상면 ~ (위 덕트 바닥 하면 | 마지막이면 꼭짓점 높이), 앞·뒤 벽(wall_t)·좌우 벽·중벽. 위 덕트는 아래 덕트와 **같은 선(같은/반대 방향)**만, 내공 −D/2 부터 + 시작 벽(END_S), 바닥은 [−D/2, D/2] 칸 자리 비움.
  - **지상 돌출 높이 `protrusion`(환기구마다, 기본 2.0m)**: 수직구로 끝나는 환기구의 상단(그릴 윗면 = 마지막 꼭짓점 높이) = 지표 EL + 돌출. 마지막 꼭짓점 높이를 **비우면 자동**(`resolve_vertices(last_z=…)`), 값을 주면 지표 EL 이 있을 때 같아야 함(5mm, 다르면 오류). 비웠는데 지표 EL 이 없거나 덕트 끝(수직구 아님)이면 오류. 지표 EL 이 없으면 입력 높이 그대로(예전 동작). 실무 샘플에서 수직구가 지표 위 9m 까지 솟던 문제.
  - 그릴: 경로 마지막 끝면 칸마다(`GRILL{k}`). 수직구 끝 = 상단 수평(윗면 = 마지막 꼭짓점 높이, u 방향 살), 덕트 끝 = 끝 단면 연직(덕트 개방, 연직 살, 그 자리 헌치 없음). 테두리 4 + 살(폭 bar, 개수 = int((안폭 − 간격)/(bar + 간격)), 등간격).
  - 부재 코드: `D{run}_FLOOR/ROOF/WALL_L/WALL_R/MID{k}/END_S/END_E`(run 은 꺾임·수직구마다 증가), `V{j}_WALL_F/B/L/R/MID{k}`, `GRILL{k}`. 본체 측벽 오프닝은 칸마다(`{이름}_C{k}`, `OpeningKind.VENT_DUCT`, `cfg.wall_openings()` 8번째 값 = 종류).
  - IFC: `IfcElementAssembly`(USERDEFINED, VENTILATION) ⊃ IfcSlab(FLOOR/ROOF)·IfcWall(바깥·중벽·끝·수직구)·**IfcAirTerminal(GRILLE, Steel)**. 3D DXF 레이어 STRUCT_VENT / STRUCT_GRILL, 횡단면 SEC_CONCRETE / SEC_GRILL, 평면 PLAN_VENT(그 층 벽 평면).
  - 검증: 형식·치수·련 수(1~20)·중벽·헌치(칸 폭 절반 미만)·그릴 테두리, 칸 높이 ≤ 층 내공, 위층 외벽 간섭(아래층은 바닥 슬래브를 잘라 허용), 수직 구간 규칙(아래로·연속·앞뒤 수평·같은 선·너무 낮음·덕트가 수직구에 비해 짧음), 측벽 오프닝 범위, 자기 겹침, 환기구끼리·출구통로와 겹침.
- **프로젝트 파일(*.ssbim, JSON)**: 파일 메뉴(새 프로젝트 Ctrl+N / 열기 Ctrl+O / 최근 프로젝트 5개 / 저장 Ctrl+S / 다른 이름으로 저장 Ctrl+Shift+S / 종료).
  - **화면 입력 그대로** 저장: `ProjectState` = 입력칸 텍스트(`fields`, 층별 `floor_height_n`/`wall_t_n` 포함) + 승강장 형식·기둥 동기화 + 탭별 입력 초안(dataclass → JSON). 미완성·오류 입력도 그대로 복원. 형식 `format`/`version`(현재 1), 없는 필드는 기본값·모르는 필드는 무시(옛/새 파일 호환), 더 새 버전은 오류.
  - 불러온 선형 파일은 **원본 내용 + 읽기 옵션을 포함**(zlib+base64, 선형 JSON 이 참조하는 points/landxml 파일도 함께, 참조는 파일 이름으로 바꿈). 열 때 임시 폴더에 풀어 다시 읽음, 실패하면 BP/EP 직선으로 열고 경고. `AlignmentSource.embedded` 는 불러올 때 만듦.
  - 복원 순서(`StationBIMApp.apply_state`): 선형 초기화 → 층별이 아닌 입력칸 → 층수 반영(`_on_floors_changed`) → 층별 입력칸 → 초안 교체(복사본) → 탭 render → 선형. 초안은 화면이 계속 고치므로 수집·복원 모두 deepcopy.
  - 변경 표시: 저장 시점 `ProjectState.key()` 와 비교(700ms 주기, 선형은 지문). 제목 "이름 * — 앱", 새 프로젝트·열기·종료(창 닫기 포함) 전에 저장 확인. 저장은 임시 파일 후 교체(원자적). 최근 목록은 `%APPDATA%/subway_station_bim/recent.json`(테스트는 `recent_file` 인자로 격리, `watch=False`).
- **출력 옵션(출력 탭, `OutputOptions`)**: '성과물 출력' 은 체크한 성과물만 출력 (3D DXF · IFC · 평면도 · 종단면도 · 단면도 · 텍스처 DAE(기본 끔), 하나 이상).
  - 평면도: 출력할 층(체크, 기본 모든 층) + 절단 높이(각 층 FL 기준, 모든 층 공통, 기본 2.0, 고른 층 내공 높이 미만). 여러 층은 한 파일에 아래층부터 위로 세로 배치(첫 층만 실제 좌표), 제목에 층 이름.
  - 종단면도: 절단 축 = 선형 중심 / 왼쪽·오른쪽 선로 중심(±선로 간격/2) 체크 + 직접 offset(쉼표, 왼쪽 +). 본체 외곽 안이어야 함. 여러 축은 한 파일에 아래로 배치, 제목에 `AXIS: C.L.±x`(중심 1개면 예전 제목).
  - 단면도: 측점(절대 STA, `134.45` 또는 `0+134.45`, 쉼표) + 연속 단면(간격, 시작·끝 STA — 비우면 내공 시점·종점, 최대 500개). 정렬·1mm 중복 제거, 내공 범위 밖이면 오류. 둘 다 없으면 내공 1/4·1/2·3/4.
  - 끈 성과물의 세부 입력은 검사하지 않음. 옵션은 폴더를 고르기 전에 검사하고(`TkAdapter.collect_output`), 프로젝트 파일에 `print_draft` 로 저장.
- **미리보기(F5, `gui/preview_window.py`)**: 파일 저장 없이 현재 입력으로 모델을 만들어 별도 창에서 평면·종단·횡단·3D 를 봄. 메인 창 '미리보기 (F5)' 버튼·보기 메뉴·F5 = 창을 열거나 갱신.
  - 2D 는 도면 출력과 **같은 DXF 문서**(`StationCADEngine.build_plan_doc/build_profile_doc/build_section_doc`, `generate_*_dxf` = build + 저장)를 ezdxf drawing(matplotlib)으로 그림 — 미리보기 = 출력 도면. 미리보기 문서만 Standard 글꼴을 `malgun.ttf` 로(한글 실 이름).
  - 평면 = 층 1개 + 절단 높이, 종단 = 축 선택(선형 중심·좌우 선로) 또는 offset 직접, 횡단 = STA 입력·슬라이더·◀▶(간격). 첫 값은 출력 탭(절단 높이·첫 단면 측점)에서.
  - 같은 보기(평면은 같은 층, 종단·횡단은 항상)를 다시 그리면 **확대/이동 상태 유지** → 입력 수정 후 F5 로 같은 자리 확인. 휠 = 커서 기준 확대, 도구 막대 = 이동·확대·그림 저장.
  - 3D = 3D DXF 문서의 3DFACE(`mesh_from_doc`: 꼭짓점마다 (x, y, z, s, h), 정수 원점 기준 상대 좌표, s = 1m 중심선 표본 최근접 + 접선 투영 근사, h = 그 s 의 FL 기준 높이). 표시 묶음(구조체·계단ESCEV·통로출입구환기구·칸막이문·바닥벽 마감·천장판·천장틀 — 천장판·천장틀은 기본 끔), **보이는 층(그 층 천장 하면 위를 잘라냄)·STA 범위**는 면을 경계에서 잘라 남김(Sutherland–Hodgman, 긴 벽도 구간만큼만), 경계면 위의 면은 버림. 한 Poly3DCollection 에 모든 면(레이어별로 나누면 깊이 정렬이 틀림) + 6m 넘는 사각 면은 나눠 그림 + 법선 음영. matplotlib 화가 알고리즘이라 앞뒤가 가끔 틀릴 수 있음(미리보기 한계).
  - 갱신 실패(입력 오류·검증 오류) = 상태줄 빨간 글자 + 메시지, 이전 모델·그림 유지. 3D 자료는 3D 탭을 처음 그릴 때 만듦(마감 켠 큰 모델 약 2초).
  - ezdxf `finalize` 가 그림(Figure) 크기를 도면 비율로 바꿔 버리므로 `draw_doc_2d` 가 원래 크기로 되돌림 (안 하면 다시 그릴 때 확대 상태가 깨짐).
- **미리보기에서 위치 선택(CAD 명령 방식)**: 입력 탭의 [선택] 버튼(주황) → `entries['pick']`(= `StationBIMApp.request_pick`) → 미리보기 창 `start_pick(PickRequest)`: 평면 탭·그 층으로 바꾸고(입력으로 갱신, 지금 입력이 오류면 직전 모델로 선택 + 경고) 점을 받음. 끝나면 `on_done(점 목록)` 이 탭 입력칸 변수에 값을 넣고 미리보기를 다시 갱신(확대 유지).
  - 종류(`preview/pick.py`): POINT(1점) / RECT(대각 2점, s·t 모두 달라야) / PATH(여러 점, Enter·오른쪽 클릭·빈 명령 = 끝) / LINE(시작·끝 2점, STA 가 달라야 — 확폭 구간). 점은 정거장 로컬 (s, t). 왼쪽 클릭 = 점(이동·확대 도구 사용 중엔 무시), Esc = 취소, 명령줄 `U` = 한 점 취소.
  - 명령줄: `STA, offset`(절대, `0+134.5, 3.2`) / `@ds, dt`(직전 점 기준). 커서 줄에 STA·offset·직전 점 기준 상대값·스냅 종류 표시, 평면에 고른 점·고무줄·커서·스냅 이름.
  - 스냅(`Snapper`): 부재 점(내공 모서리·그 층 기둥 중심·실 모서리·오프닝 모서리) → 부재 선(축별: 내공 시점/종점 s, 내공면·외벽 바깥면(통로 접합점)·선형 중심 t) → 격자(절대 STA 기준, 기본 0.1m). 허용 거리 = 화면 10px(`ax.bbox.width` 기준). 평면 조작 줄에서 켜고 끔.
  - **직교 모드(F8, 기본 켬, 경로 선택만)**: 직전 점에서 커서가 더 많이 움직인 축(s 또는 t) 방향으로만 — 고정 축은 직전 값, 움직이는 축만 스냅(`ortho_snap`). 출구통로·환기구 첫 구간(본체에 직각) 을 클릭으로 만들 수 있게 함 (사용자 작동 테스트에서 없으면 불가능했음).
  - 곡선 선형은 평면이 WCS 라 클릭은 `to_station`(정확, 약 30ms), 마우스 이동은 0.5m 중심선 표본 근사(`to_st(fast=True)`).
  - 탭 연결(`gui/pick_buttons.py`, 값 계산은 `gui/pick_fill.py`): 실 '영역 선택'(RECT → 시작/끝 STA·t), 문 '선택'(POINT → 가장 가까운 실 변 + 중심, 변 범위로 자름), 오프닝 '영역 선택'(RECT → 시작 STA·길이·t 중심·폭, 평면 층 = 가장 낮은 슬래브 위층), 계단 '위치 선택'(첫 단 STA·t), ESC(하부 WP), EV(승강로 중심, 최하 정지층), 출구통로·환기구 '경로 선택'(PATH → 꼭짓점 표 교체, 높이는 같은 순번 값 유지·새 점은 첫 점 비움/나머지 0, 절대 좌표 방식이면 to_world 로 X·Y).
- **텍스처 3D 모델(COLLADA .dae, `exporter/dae_exporter.py`)**: 스케치업 기본 가져오기로 둘러보기용 (스케치업 IFC 가져오기는 텍스처를 읽지 않음, 2D 도면에는 불필요). 출력 탭 '텍스처 DAE'(기본 끔) → `정거장3d모델.dae` + 옆 `textures/` 에 이미지 복사.
  - 기하 = `build_3d_doc` 의 3DFACE 그대로(단일 원천). 마감 부재는 그 부재의 `material`(source_element 핸들로 연결), 나머지는 레이어별 재질(`render_material.LAYER_MATERIALS`, 목록에 없는 구조 레이어 = `CONCRETE` — 텍스처 `Polished Concrete New` 2.0×2.0, 콘크리트 면처리도 같은 텍스처). **천장틀(FIN_FRAME)은 기본 제외**(면이 많고 천장판에 가림, `frames=True` 로 포함).
  - 텍스처는 재질 이름 기준 `FINISH_MATERIALS`: 금속패널 → `metal_panel` 1.2×0.6, 화강석 → `granite` 0.6×0.6, 알루미늄 천장판 → `ceiling_panel` 0.6×0.6 (이미지 한 장의 실제 크기). 이미지(`assets/image/tile/{이름}.jpg|.jpeg|.png`, 공백 있는 이름은 URI 에서 `%20`)가 없으면 색만 + 완료 알림에 안내. 그 밖의 재질은 색만.
  - 텍스처 좌표: 면마다 평면 투영 — 수평 면(|n_z| ≥ 0.7)은 u = 면 중심의 선형 접선(곡선은 `preview_render.station_of` 근사), v = 왼쪽 +t; 그 밖은 u = 면 안 수평, v = 면 안 위쪽. 세계 원점 기준 좌표라 이웃 면끼리 무늬가 이어짐(곡선 수평 면은 근사).
  - 좌표는 정수 원점 기준 상대 좌표(소수 5자리, 스케치업 정밀도) — 원점은 `<asset><comments>`·완료 알림. 레이어마다 노드(스케치업 그룹), 재질마다 삼각형 묶음, double_sided.
  - 기본 마감 재질 이름 변경: 바닥 기본 `석재` → **화강석**, 벽 기본 `패널` → **금속패널**(FinishType·마감 탭 초안). 옛 프로젝트 파일의 마감표는 저장된 이름 그대로라 텍스처를 쓰려면 마감 탭에서 이름을 바꿔야 함.
- **3D 웹 뷰어(`exporter/web_viewer.py`, 출력 탭 '3D 웹 뷰어(HTML)', 기본 끔 → `정거장3d뷰어.html`)**: matplotlib 3D 미리보기가 느려서 만든 브라우저 뷰어. three.js(`assets/web/three.min.js` r147, MIT)와 모델 자료를 HTML 한 파일에 넣어 인터넷 없이 열림.
  - 자료 = `build_3d_doc` 의 3DFACE 그대로(단일 원천, 천장틀 FIN_FRAME 은 기본 제외). 묶음(레이어 × 보기 재질 `render_material`)마다 꼭짓점(float32, 정수 원점 기준 상대)·꼭짓점별 (s, FL 기준 h)·삼각형 번호·삼각형 → 부재 번호를 한 바이트 열로 이어 gzip + base64(브라우저 `DecompressionStream`). 부재 표 = 서브 엔진의 BIM 객체 중 `source_element` 를 가진 것(이름·층·재질·종류, `_element_index` 가 훑음). h 의 FL 은 선형 끝 밖을 끝 구배로 연장.
  - 뷰어(템플릿 JS): Z 위 궤도 조작(왼쪽 회전, 오른쪽/Shift 이동, 휠 확대, 더블클릭 = 회전 중심), 표시 묶음(미리보기 `LAYER_GROUPS`), 보이는 층(그 층 천장 하면 위를 버림)·STA 범위 = 셰이더 discard(모든 재질 공통 uniform), 클릭 = 부재 정보 + 강조(잘린 면은 건너뜀), 걷기(포인터 잠금, WASD·Shift·E/Q·PgUp/PgDn 층, 눈높이 = 선형 중심 표본 FL + 층 바닥(최하층은 승강장 상면) + 1.6). `window.__viewer` 로 상태 접근(디버그).
  - **텍스처**: DAE 와 같은 재질·텍스처 좌표(`dae_exporter.texture_axes`(면마다 u·v 방향, `texture_uv` 가 씀)·`frame_uv`). 텍스처 이미지가 있는 묶음만 꼭짓점 uv(면마다 넓은 쪽 삼각형으로 방향), 이미지는 긴 변 `IMAGE_MAX` 1024px 로 줄인 data URL(`DATA.images`, 투명 PNG 는 PNG·나머지 JPEG), 이미지 없는 텍스처는 `missing_textures`(통계 줄에 표시). 사인은 그린 이미지 한 장(ClampToEdge). 뷰어 '텍스처' 체크(기본 켬, 끄면 재질 색), 같은 data URL 의 THREE.Texture 는 실시간 갱신에서도 재사용.
  - 실무 샘플: 삼각형 8.4만, 4.7MB(텍스처 포함, 없으면 2.2MB), 약 11초.
  - **실시간 갱신(`exporter/live_viewer.py`)**: 미리보기 창 [브라우저 3D (실시간)] → 앱 안의 로컬 HTTP 서버(`127.0.0.1`, 빈 포트, 앱 전체 하나 `shared()`)로 기본 브라우저를 열고 지금 모델을 올림. 이후 미리보기 갱신(F5)마다 `update(cfg)` = **설정 사본(deepcopy)으로 별도 엔진**을 백그라운드 스레드에서 만들어 올림(미리보기 엔진과 3D 문서를 함께 쓰지 않음, 만드는 중에 들어온 갱신은 끝나고 최신 것 한 번). 경로 `/`(LIVE 뷰어), `/version`(version·status idle|building|ok|error·message), `/data.json`, `/data.bin`(gzip). 뷰어는 1초마다 `/version` 을 물어 새 버전이면 `loadModel` 로 모델만 바꿈 — 카메라·표시 묶음·보이는 층(이름)·STA 범위·고른 부재(이름) 유지, 원점이 바뀌면 카메라를 같은 세계 위치로. 입력 오류면 이전 모델 + 왼쪽 아래에 오류, 서버가 꺼지면 '연결 끊김'(다시 켜지면 이어짐). 미리보기 머리줄 오른쪽 `live_label` 에 상태. 템플릿은 정적(`DATA_EMBED` + `BLOB`)·실시간(`LIVE = true`) 겸용.
- 출력: 3D DXF, 횡단면도, 평면도(직선=전개, 곡선=WCS), 종단면도, IFC4, 텍스처 DAE, 3D 웹 뷰어(HTML).

## 5. 테스트 작성 규약

- 회귀: 직선 기본 출력은 **golden hash**(`tests/test_curved.py::GOLDEN_STRAIGHT`)로 고정. 기하 규약을 의도적으로 바꿀 때만 갱신하고, 왜 바뀌었는지 커밋 메시지에 남긴다.
- 체적은 공식 ↔ 3D 메쉬(발산 정리) ↔ IFC 형상(ifcopenshell) 세 가지를 서로 교차 검증하는 방식. 곡선 메쉬 허용오차는 `rel=1e-4`.
- GUI 테스트는 `tkinter` + 디스플레이 필요 (`xvfb-run -a`). tk 변수(`StringVar` 등)는 **반드시 속성/딕셔너리에 보관** — 지역 변수로 두면 GC 되어 `trace` 가 사라진다 (실제로 겪은 버그).
- 테스트에서 직접 `set_kind()` 같은 초안 메서드를 호출하면 화면 위젯(콤보박스)은 갱신되지 않는다 (실제 입력에서는 위젯이 초안을 바꿈).

## 6. 앞으로 할 일 / 미결 사항

**사용자 확인이 필요한 것 (미답변)**
1. 평면도에 오프닝을 표시해야 하는가? 층별 평면도는 생겼지만(출력 탭) 슬래브 오프닝 외곽은 아직 그리지 않음. 층마다 그 층 바닥 슬래브의 오프닝을 점선 등으로 표시할지.
2. 실무 도면의 오프닝 표기 기준 — 지금은 `시작 STA + 길이`, `t 중심 + 폭`. 도면이 STA 범위 + 선로 중심 이격으로 되어 있으면 입력 항목을 맞춘다.

**제안 (사용자 확정 전, 우선순위 참고용)**
- 층별 평면도에 오프닝 외곽 표시. 위 1번 답에 따라.
- 오프닝 위에 실제 계단/에스컬레이터/엘리베이터 BIM 객체 배치 (용도별 IfcStair/IfcTransportElement 등) — "본격적인 정거장 구현"의 다음 단계.
- 오프닝 IFC 속성(Pset: 용도, 치수) 추가, 오프닝 간 최소 이격/벽체 이격 검증 규칙.
- 승강장 슬래브·지지벽체와 바닥 슬래브 오프닝의 간섭 검사 (현재 기둥만 검사).
- 마감 다음 후보: 벽 마감 하지재(각파이프·앵글·패널 클립 — 이격 공간), 걸레받이(실무 상세의 화강석 물갈기 T24/T30), 천장 행거·액세스 플로어 받침, 실무 마감표 반영, 원기둥 바닥·천장 빼기, 걸레받이·몰딩, 계단 하부·에스컬레이터 마감, 마감 물량표.
- 실 다음 후보: 사각형이 아닌 실(L자 등 사각형 조합), 실 면적표 출력, 기둥과 칸막이벽 체적 중복 정리.
- 프로젝트 파일 다음 후보: 자동 저장·복구, 프로젝트에서 선형 원본 다시 꺼내기(내보내기).
- 미리보기 다음 후보: UI 고도화 때 메인 창 안에 내장, 3D 를 OpenGL(pyvista 등)로 바꿔 깊이 정확·빠른 회전, 입력 중인 부재 강조, 횡단·종단에서도 위치 선택(높이), 평면에서 부재를 클릭해 해당 탭 항목 열기, 끌어서 옮기기(그립 편집).

- 계단 2단계 후보: U자(꺾임) 계단, 계단 위 난간.
- 엘리베이터 2단계 후보: 지상까지 가는 외부 엘리베이터(출입구 연계), 유리 승강로, 일부 층 미정지(정지층 선택), 승강장 문(landing door) 패널, 기계실형, 실무 제원 반영.
- 출입구 2단계 후보: 천장을 도면처럼 계단참마다 꺾기, 깊이별 벽 두께(700/800/900), 상부 캐노피(지상 구조물), E-E 단면처럼 계단식 파라펫, 지형 자료 불러오기(지표 EL 자동), 종단면도·층별 평면도 표시, 계단연석 분리.
- 지표 다음 후보: 본체 천장·통로·덕트 토피 검사(지표 위로 나오면 경고), 지형 자료(측점별 지표 EL)·지형 불러오기, IFC IfcSite 표고.
- 환기구 2단계 후보: 아래로 내려가는 수직구, 위 덕트가 다른 방향(직각)으로 나가는 수직구, 본체 천장에서 바로 올라가는 수직구, 지상 환기탑·루버, 수직구 깊이 방향 회전, 종단면도 표시.
- 출구통로 다음 후보: Y자(끝에서 갈라짐)·비스듬한 분기, 분기부 바닥·천장 접합 상세, 통로 경로와 본체(다른 층·곡선 안쪽)의 간섭 검사, 종단면도 표시, 경로 그래픽 편집 UI(Revit 식).
- 에스컬레이터 2단계 후보: 바닥을 내린 피트 구조(슬래브보다 깊은 피트), 상·하부 곡선 전이부, 핸드레일 끝 곡선(뉴얼), 실무 도면 제원 반영.

**알려진 정리 항목**
- `gui/gui.py` 는 어디서도 import 하지 않는 옛 파일이며 pyflakes 경고(`ColumnParameters` 미정의) 1건이 있다.
- 벽체 코드 `L`/`R` 과 `WallRole.LEFT/RIGHT` 는 t 음수/양수 쪽이라 "진행방향 왼쪽 = +t" 규약과 이름이 반대다 (동작은 t 범위 기준이라 문제 없음, 출구통로는 t 부호로 벽을 찾음).
- `boxes/`(BoxShape/BoxData)는 여전히 쓰이지 않는다. 출구통로는 부재별 분리 요구에 맞춰 `passages/` 로 새로 구현함.
- 문서 문자열 불일치: `columns/column_params.py` 의 `t_offset` 설명과 기둥 탭 안내문이 "오른쪽 +" 라고 쓰여 있으나, 실제 코드는 `t_offset` 을 그대로 `pos_y`(왼쪽 +)로 쓴다. 코드 동작이 기준이므로 문구를 "왼쪽 +" 로 정정하거나(권장) 의도를 사용자에게 확인할 것.
- `tests/` 의 미사용 import 등 pyflakes 경고(기존).
- 패키지 폴더명 `boxes/`(원본은 `boxs/`) 등 원본 대비 이름 정리가 누적 패치에 포함되어 있음.

## 7. 작업 방식 (사용자 선호)

- 요청은 **단계별로 구현 → 테스트 → 산출물(zip + 누적 패치)** 순으로 진행했고, 사용자는 각 단계 결과를 확인한 뒤 "계속" 으로 다음 단계를 지시한다.
- 실무 도면 근거로 규약을 정정해 주는 경우가 많다 (내벽 고정, 내공 기준, STA 기준). 규약이 불분명하면 추측하지 말고 먼저 묻는다.
- 누적 패치는 `diff -ruN -x __pycache__ -x .pytest_cache a b` (a = 원본 폴더, b = 수정본)로 만들어 `patch -p1` 로 적용되게 한다.
- 변경 후에는 전체 테스트 + pyflakes(소스) 통과를 확인하고, 형상 변경은 독립 계산(공식·메쉬·IFC)으로 교차 검증한다.
