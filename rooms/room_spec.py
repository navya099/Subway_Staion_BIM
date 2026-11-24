import dataclasses
from typing import Optional

# 실 용도 기본 목록 (직접 입력도 가능). 나중에 용도별 기본 마감을 연결한다
ROOM_USES = ["대합실", "승강장층", "복도", "역무실", "기계실", "전기실", "통신실", "공조실", "화장실", "창고", "통로", "기타"]
PLATFORM_USE = "승강장층"
CONCOURSE_USE = "대합실"
DOOR_SIDES = ("+s", "-s", "+t", "-t")     # 문이 있는 실의 변: 종점 쪽 / 시점 쪽 / 왼쪽 / 오른쪽
# 문 종류 → IFC IfcDoor.OperationType
DOOR_KINDS = {"여닫이": "SINGLE_SWING_LEFT", "양개 여닫이": "DOUBLE_DOOR_SINGLE_SWING", "미닫이": "SLIDING_TO_LEFT",
              "방화문": "SINGLE_SWING_LEFT", "자동문": "DOUBLE_DOOR_SLIDING"}
PARTITION = "partition"      # 실 경계 = 칸막이벽 (공통 두께)
SEPARATION = "separation"    # 실 경계 = 구획분리 (두께 0 = 가상 경계선, > 0 = 얇은 실제 벽)
BOUNDARIES = (PARTITION, SEPARATION)


@dataclasses.dataclass
class DoorSpec:
    """실 경계 벽(칸막이벽·두께 있는 구획분리 벽)에 내는 문 1개.
    Attributes:
        side: 실의 어느 변 '+s' | '-s' | '+t' | '-t'
        center: 문 중심 위치 — ±s 변이면 t, ±t 변이면 s (정거장 로컬)
        width / height: 문 폭 / 높이 (벽 개구부 = 문틀 바깥 크기, 높이는 바닥 마감면부터 — 마감을 끄면 그 벽의 바닥부터)
        kind: DOOR_KINDS 의 하나 (여닫이 · 양개 여닫이 · 미닫이 · 방화문 · 자동문)
        swing: 열림 'in' 실 안쪽 | 'out' 실 바깥쪽 (미닫이·자동문은 문짝이 걸리는 쪽)
        hinge: 경첩 쪽 (미닫이는 밀리는 쪽), 실 안에서 문을 볼 때 'left' | 'right', None = 좌표(s 또는 t)가 작은 쪽
        name: 비우면 실 이름 + _D + 번호
    """
    side: str = "+t"
    center: float = 0.0
    width: float = 0.9
    height: float = 2.1
    kind: str = "여닫이"
    name: str = ""
    swing: str = "in"
    hinge: Optional[str] = None


@dataclasses.dataclass
class RoomSpec:
    """실(구획) 1개 = 한 층의 직사각형 영역 (정거장 로컬 좌표, 칸막이벽 중심선 기준).
    Attributes:
        floor: 층 번호 (1 = 최하층)
        use: 용도 (ROOM_USES 의 하나 또는 직접 입력한 이름)
        s0 / s1: 진행방향 범위 (내공 시점 기준 s, s0 < s1)
        t0 / t1: 직교방향 범위 (t, 왼쪽 +, t0 < t1)
        name: 비우면 용도 + 층 안 일련번호 (예: 역무실1)
        boundary: 경계 종류 — PARTITION(칸막이벽, 공통 두께) | SEPARATION(구획분리)
        sep_t: 구획분리 두께 (m). 0 = 두께 없는 가상 경계선(공간만 나눔), > 0 = 얇은 실제 벽
        doors: 이 실의 변에 내는 문 (DoorSpec). 그 변에 벽이 있어야 함 (본체 벽·가상 경계선은 불가)
        open_sides: 벽을 세우지 않는 변 ('+s' / '-s' / '+t' / '-t') — 계단실 앞면처럼 열린 변 (가상선도 없음)
        wall_tops: 변 → 그 변 벽의 윗면 높이 (본체 FL 기준, 비우면 위 슬래브 하면) — 계단 아래를 가로지르는 끝 벽
        auto: 자동 생성한 실의 출처 (예: 'ENC:ST1' 계단 옆 벽체) — 검사 전 다시 만들므로 입력 실과 구분
    경계 중 본체 벽(내공면)이 아닌 변에는 칸막이벽/구획분리가 중심선에 맞춰 자동으로 선다.
    같은 선에서 겹치면 칸막이벽이 우선 (구획분리끼리는 두꺼운 쪽).
    """
    floor: int = 1
    use: str = "역무실"
    s0: float = 0.0
    s1: float = 10.0
    t0: float = 0.0
    t1: float = 5.0
    name: str = ""
    boundary: str = PARTITION
    sep_t: float = 0.0
    doors: list = dataclasses.field(default_factory=list)        # list[DoorSpec]
    finish: str = ""                                             # 마감 종류 (비우면 용도 이름으로 마감표에서 찾음)
    open_sides: tuple = ()
    wall_tops: dict = dataclasses.field(default_factory=dict)
    auto: str = ""

    @property
    def rect(self) -> tuple:
        return (self.s0, self.s1, self.t0, self.t1)

    @property
    def area(self) -> float:
        return (self.s1 - self.s0) * (self.t1 - self.t0)


@dataclasses.dataclass
class RoomSettings:
    """실 공통 설정.
    Attributes:
        default_uses: 층 번호 → 기본 실(입력한 실을 뺀 나머지 영역)의 용도. 없는 층은 최하층 = 승강장층, 그 위 = 대합실
        partition_t: 칸막이벽 두께 (m, 조적 기본 0.2)
        partition_material: 칸막이벽 재질 이름 (IFC 재질)
        separation_material: 구획분리 벽(두께 > 0) 재질 이름
    """
    default_uses: dict = dataclasses.field(default_factory=dict)
    partition_t: float = 0.2
    partition_material: str = "Masonry_Block"
    separation_material: str = "Separation_Panel"

    def default_use(self, floor: int) -> str:
        return self.default_uses.get(floor) or (PLATFORM_USE if floor == 1 else CONCOURSE_USE)


def snap_tolerance(spec: RoomSpec, settings: RoomSettings) -> float:
    """실 경계를 내공면에 붙이는 허용 거리 = 그 실 경계 벽 두께 (구획분리면 sep_t, 칸막이벽이면 공통 두께), 최소 칸막이벽 두께"""
    own = spec.sep_t if spec.boundary == SEPARATION else settings.partition_t
    return max(own, settings.partition_t)


def snap_to_clear(spec: RoomSpec, length: float, half_w: float, settings: RoomSettings,
                  half_w_neg: Optional[float] = None) -> RoomSpec:
    """실 경계가 내공면(s = 0 / L, t = ±W/2)에서 경계 벽 두께 이내면 내공면에 붙인 사본 (안쪽·바깥쪽 모두).
    예) 내공 폭 20.2 (±10.1) 인데 t = ±10 으로 입력 → ±10.1: 본체 벽에 붙은 얇은 벽과 0.1m 자투리 실이 생기지 않음.
    문 중심(±t 변 = s, ±s 변 = t)은 그대로 둔다. half_w_neg: −t 쪽 내공면 |t| (구조물 확폭, 비우면 half_w)"""
    tol = snap_tolerance(spec, settings) + 1e-9

    def snap(v, face):                          # 변마다 자기 쪽 내공면만 (s0 → 시점, s1 → 종점, t0 → 오른쪽, t1 → 왼쪽)
        return face if 1e-12 < abs(v - face) <= tol else v
    s0, s1 = snap(spec.s0, 0.0), snap(spec.s1, length)
    t0, t1 = snap(spec.t0, -(half_w if half_w_neg is None else half_w_neg)), snap(spec.t1, half_w)
    if (s0, s1, t0, t1) == spec.rect or not (s0 < s1 and t0 < t1):
        return spec
    return dataclasses.replace(spec, s0=s0, s1=s1, t0=t0, t1=t1)


def snap_rooms_to_clear(specs: list, station, settings: RoomSettings, cfg=None) -> list:
    """snap_to_clear 를 모든 실에 (StationProjectConfig.validate 가 검사 전에 입력을 정규화).
    cfg 를 주면 내공 확폭이 있는 층은 그 실 s 구간의 넓어진 내공면(구간 어디서나 닿는 |t|)에 붙임"""
    out = []
    for sp in specs:
        if cfg is not None and isinstance(sp, RoomSpec) and isinstance(sp.floor, int) and 1 <= sp.floor <= station.floors:
            from config.widening import has_pockets, inner_min
            if has_pockets(cfg, sp.floor) and sp.s0 < sp.s1:
                out.append(snap_to_clear(sp, station.length, inner_min(cfg, sp.floor, 1, sp.s0, sp.s1), settings,
                                         inner_min(cfg, sp.floor, -1, sp.s0, sp.s1)))
                continue
        out.append(snap_to_clear(sp, station.length, station.width / 2.0, settings))
    return out
