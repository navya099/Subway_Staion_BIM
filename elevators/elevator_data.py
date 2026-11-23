from dataclasses import dataclass, field

from bim_data.common_bim_data import CommonBIMData
from elevators.elevator_type import ElevatorPartKind


@dataclass
class ElevatorElementData(CommonBIMData):
    """엘리베이터 부재 1개 (승강로 벽 1면 · 피트 슬래브 · 천장 슬래브 · 카 바닥/벽 1면/천장/문).
    IFC: 승강로 벽 = IfcWall, 피트 = IfcSlab(BASESLAB), 천장 = IfcSlab(ROOF), 카 = IfcBuildingElementPart, 카 문 = IfcDoor
    Attributes:
        kind / code: 부재 종류 / 엘리베이터 안의 코드 (WALL_PS, CAR_DOOR_PT …)
        parts: ElevatorPartLayout 목록 (상자 띠, 출입구로 나뉜 벽은 여러 조각)
    """
    kind: ElevatorPartKind = ElevatorPartKind.HOIST_WALL
    code: str = ""
    parts: list = field(default_factory=list)
    slide: tuple = None          # 문짝 애니메이션: ((ds, dt) 정거장 단위 방향, 최대 이동) — 열림 비율 × 최대 이동만큼 그 방향
    stop: int = None             # 승강장 문짝의 층

    @property
    def volume(self) -> float:
        return sum(p.volume for p in self.parts)


@dataclass
class ElevatorData(CommonBIMData):
    """엘리베이터 1대 (IFC: IfcElementAssembly(ELEVATOR) ⊃ 승강로 부재 + IfcTransportElement(ELEVATOR) ⊃ 카 부재).
    level = 최하 정지층 이름, pos = 승강로 내공 중심 (s, t) 와 피트 슬래브 하면 표고
    Attributes:
        lower_floor / upper_floor / car_floor: 정지층 범위, 카가 서 있는 층
        on_platform: 최하층 정지 바닥이 승강장 상면인가
        stops: 층 번호 → 정지 바닥 절대 표고
        outer / inner: 승강로 외곽 / 내공 (s0, s1, t0, t1)
        door_openings: [(이름, 벽 code, 층, (s0, s1, t0, t1), z0, z1)] 정지층 출입구
        elements: 승강로·카 부재
    """
    lower_floor: int = 1
    upper_floor: int = 2
    car_floor: int = 1
    on_platform: bool = False
    stops: dict = field(default_factory=dict)
    outer: tuple = (0.0, 0.0, 0.0, 0.0)
    inner: tuple = (0.0, 0.0, 0.0, 0.0)
    door_openings: list = field(default_factory=list)
    elements: list = field(default_factory=list)
    car_z: float = 0.0           # 카 바닥 상면 절대 표고 (애니메이션: 이 값을 바꾸면 카 묶음(is_car)이 연직 이동)
    travel: tuple = (0.0, 0.0)   # 카 바닥 상면 운행 범위 (최하·최상 정지 바닥, 절대 표고)
    door_open: float = 0.0       # 현재 문 열림 비율 (카 문 + 카가 선 층 승강장 문)

    def element(self, code: str) -> ElevatorElementData:
        return next(e for e in self.elements if e.code == code)

    @property
    def hoistway(self) -> list:
        return [e for e in self.elements if not e.kind.is_car]

    @property
    def car(self) -> list:
        return [e for e in self.elements if e.kind.is_car]
