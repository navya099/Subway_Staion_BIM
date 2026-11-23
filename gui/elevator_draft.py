"""엘리베이터 입력의 화면 비의존 모델 (문자열 초안 → ElevatorSpec 변환 + 검증)"""
from dataclasses import dataclass

from elevators.elevator_spec import ElevatorSpec
from gui.column_draft import _num, level_name

_SPEC = ElevatorSpec()             # 초기값은 모델 기본값이 단일 출처

DOORS = {"+t (왼쪽)": "+t", "−t (오른쪽)": "-t", "+s (종점 방향)": "+s", "−s (시점 방향)": "-s"}
DOOR_LABELS = list(DOORS)
SHAFT_GLASS = "투시형 (강관+유리)"
SHAFT_RC = "RC 승강로"
SHAFTS = {SHAFT_GLASS: "glass", SHAFT_RC: "rc"}
SHAFT_LABELS = list(SHAFTS)

# 투시형 승강로 제원 (양수 입력칸)
GLASS_FIELDS = [("glass_offset", "유리 바깥 간격"), ("glass_t", "유리 두께"), ("col_d", "기둥 지름"), ("col_inset", "기둥 위치"),
                ("girt_d", "가로재 지름"), ("glass_max_w", "유리 최대 폭"), ("door_frame_w", "승강장 문틀 폭")]

# (속성, 라벨) 양수 입력칸
NUM_FIELDS = [("inner_s", "승강로 내공 s"), ("inner_t", "승강로 내공 t"), ("wall_t", "승강로 벽"),
              ("door_w", "문 폭"), ("door_h", "문 높이"), ("pit_depth", "피트 깊이"), ("pit_slab_t", "피트 슬래브"),
              ("overhead", "오버헤드"), ("top_slab_t", "천장 슬래브"), ("car_width", "카 폭"), ("car_depth", "카 깊이"),
              ("car_height", "카 높이"), ("car_floor_t", "카 바닥"), ("car_wall_t", "카 벽·문"), ("car_roof_t", "카 천장")]


@dataclass
class ElevatorDraft:
    """엘리베이터 1대 (입력창 문자열 그대로 보관)
    sta_center: 승강로 내공 중심의 절대 STA — 정거장 시작 측점을 빼서 s 로 변환
    lower_floor / upper_floor / car_floor: 최하·최상 정지층, 카가 서 있는 층 (1 = 최하층)"""
    name: str = ""
    lower_floor: int = 1
    upper_floor: int = 2
    car_floor: int = 1
    sta_center: str = "0"
    t_center: str = "6.5"
    door: str = DOOR_LABELS[1]
    through: bool = False
    inner_s: str = f"{_SPEC.inner_s:g}"
    inner_t: str = f"{_SPEC.inner_t:g}"
    wall_t: str = f"{_SPEC.wall_t:g}"
    door_w: str = f"{_SPEC.door_w:g}"
    door_h: str = f"{_SPEC.door_h:g}"
    pit_depth: str = f"{_SPEC.pit_depth:g}"
    pit_slab_t: str = f"{_SPEC.pit_slab_t:g}"
    overhead: str = f"{_SPEC.overhead:g}"
    top_slab_t: str = f"{_SPEC.top_slab_t:g}"
    car_width: str = f"{_SPEC.car_width:g}"
    car_depth: str = f"{_SPEC.car_depth:g}"
    car_height: str = f"{_SPEC.car_height:g}"
    car_floor_t: str = f"{_SPEC.car_floor_t:g}"
    car_wall_t: str = f"{_SPEC.car_wall_t:g}"
    car_roof_t: str = f"{_SPEC.car_roof_t:g}"
    shaft: str = SHAFT_GLASS               # 화면 기본 = 투시형 (정거장 내부 실무 표준, 모델 기본 RC)
    door_floors: str = ""                 # 층별 문 방향 (최하 정지층부터 쉼표, 한 층에 여럿이면 '/', 비우면 문 방향·관통형)
    glass_offset: str = f"{_SPEC.glass_offset:g}"
    glass_t: str = f"{_SPEC.glass_t:g}"
    col_d: str = f"{_SPEC.col_d:g}"
    col_inset: str = f"{_SPEC.col_inset:g}"
    girt_d: str = f"{_SPEC.girt_d:g}"
    glass_max_w: str = f"{_SPEC.glass_max_w:g}"
    glass_rows: str = ", ".join(f"{h:g}" for h in _SPEC.glass_rows)
    door_frame_w: str = f"{_SPEC.door_frame_w:g}"
    car_offset: str = "0"                 # 카 위치 = 카 정지층 + 오프셋 (애니메이션 대비)
    door_open: str = "0"                  # 문 열림 비율 0~1
    car_glass: bool = True                # 투시형 카 (화면 기본, 모델 기본 끔)
    ladder: bool = True                   # 피트 점검 사다리
    fixtures: bool = True                 # 호출 버튼 판·층 표시기 (화면 기본, 모델 기본 끔)

    def to_spec(self, where: str, start_station: float) -> ElevatorSpec:
        if self.door not in DOORS:
            raise ValueError(f"{where}: 문 방향이 올바르지 않습니다 ('{self.door}')")
        if self.shaft not in SHAFTS:
            raise ValueError(f"{where}: 승강로 형식이 올바르지 않습니다 ('{self.shaft}')")
        vals = {attr: _num(getattr(self, attr), where, label, positive=True) for attr, label in NUM_FIELDS + GLASS_FIELDS}
        rows = tuple(_num(x, where, "유리 줄 높이", positive=True) for x in str(self.glass_rows).split(",") if x.strip())
        if not rows:
            raise ValueError(f"{where}: 유리 줄 높이를 입력하세요 (아래부터 쉼표)")
        floors = [x.strip().replace("−", "-") for x in str(self.door_floors).split(",")] if str(self.door_floors).strip() else None
        return ElevatorSpec(lower_floor=self.lower_floor, upper_floor=self.upper_floor, car_floor=self.car_floor,
                            s_center=_num(self.sta_center, where, "승강로 중심 측점") - start_station,
                            t_center=_num(self.t_center, where, "t 위치"), door_side=DOORS[self.door],
                            through=bool(self.through), name=self.name.strip(), shaft=SHAFTS[self.shaft],
                            door_floors=floors, glass_rows=rows, car_offset=_num(self.car_offset, where, "카 위치 오프셋"),
                            door_open=_num(self.door_open, where, "문 열림", nonneg=True), car_glass=bool(self.car_glass),
                            ladder=bool(self.ladder), fixtures=bool(self.fixtures), **vals)


class ElevatorDrafts:
    """엘리베이터 입력 초안 목록"""

    def __init__(self):
        self.items: list[ElevatorDraft] = []

    def ensure_floors(self, floor_count: int) -> bool:
        """층수가 바뀌면 정지층을 새 층수 안으로 (최상층 > 최하층, 카 층은 그 사이). 변경 여부 반환"""
        changed = False
        n = max(2, floor_count)
        for it in self.items:
            before = (it.lower_floor, it.upper_floor, it.car_floor)
            it.upper_floor = min(max(it.upper_floor, 2), n)
            it.lower_floor = min(max(it.lower_floor, 1), it.upper_floor - 1)
            it.car_floor = min(max(it.car_floor, it.lower_floor), it.upper_floor)
            changed |= before != (it.lower_floor, it.upper_floor, it.car_floor)
        return changed

    def to_specs(self, start_station: float) -> list[ElevatorSpec]:
        return [it.to_spec(self.where(i, it), start_station) for i, it in enumerate(self.items)]

    @staticmethod
    def where(i: int, it: ElevatorDraft) -> str:
        return f"엘리베이터 {i + 1}" + (f"({it.name.strip()})" if it.name.strip() else "")


def preview(it: ElevatorDraft, start_station: float, floor_count: int) -> str:
    """입력 중 미리보기: 정지층, 카 위치, 승강로 외곽 STA 범위"""
    try:
        sp = it.to_spec("", start_station)
    except ValueError:
        return "→ 입력값을 확인하세요"
    name = lambda n: level_name(floor_count, n)
    S0, S1, T0, T1 = sp.outer_rect()
    return (f"→ 정지 {name(sp.lower_floor)} ~ {name(sp.upper_floor)} ({sp.upper_floor - sp.lower_floor + 1}개 층), "
            f"카 {name(sp.stop_car)}, "
            + (f"층별 문 {', '.join(sp.door_floors)}" if sp.door_floors else f"문 {sp.door_side}{' 관통형' if sp.through else ''}")
            + (" · 투시형" if sp.shaft == "glass" else " · RC") + "\n"
            f"   승강로 외곽 STA {S0 + start_station:.2f} ~ {S1 + start_station:.2f}, t {T0:g} ~ {T1:g}")
