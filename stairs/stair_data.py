from dataclasses import dataclass, field
from typing import Optional

from bim_data.common_bim_data import CommonBIMData
from stairs.stair_shape import StairPartShape
from stairs.stair_type import StairPartKind


@dataclass
class StairPartData(CommonBIMData):
    """계단 런 또는 중간 계단참 1개 (IFC: IfcStairFlight / IfcSlab LANDING).
    pos_x/pos_y: 평면 중심 (s, t), pos_z: 상면 최저 표고 (절대)
    Attributes:
        kind: 런 / 계단참
        n_risers: 런의 챌판 수 (계단참은 0)
        n_treads: 런의 디딤판 수 (= 챌판 수 − 1, 마지막 챌판은 계단참·위층 바닥으로 올라감)
        t_range: (t0, t1)
        surfaces: 걷는 면 [(s0, s1, 상면 표고)] (런 = 디딤판마다, 계단참 = 1개). 평면도·머리 높이 기준
    """
    kind: StairPartKind = StairPartKind.FLIGHT
    n_risers: int = 0
    n_treads: int = 0
    t_range: tuple = (0.0, 0.0)
    surfaces: list = field(default_factory=list)
    shape: Optional[StairPartShape] = None


@dataclass
class StairData(CommonBIMData):
    """직선 계단 1개 (IFC: IfcStair 가 런·계단참을 묶음). level = 계단이 시작되는 층 이름
    Attributes:
        lower_floor: 시작 층 번호 (1 = 최하층), 위층 = lower_floor + 1
        direction: +1 = 종점 방향(+s)으로 오름, -1 = 시점 방향
        on_platform: 승강장 슬래브 상면에서 시작하면 True (최하층)
        n_risers / riser / tread: 전체 챌판 수, 실제 단높이, 단너비
        s_range / t_range: 계단 평면 범위 (첫 챌판 ~ 위층 도착 지점)
        opening_name: 자동으로 뚫은 슬래브 오프닝 이름 (OpeningSpec.name)
        parts: 런·계단참 (아래에서 위 순서)
    """
    lower_floor: int = 1
    direction: int = 1
    on_platform: bool = False
    n_risers: int = 0
    riser: float = 0.0
    tread: float = 0.0
    s_range: tuple = (0.0, 0.0)
    t_range: tuple = (0.0, 0.0)
    opening_name: str = ""
    parts: list = field(default_factory=list)

    @property
    def flights(self) -> list:
        return [p for p in self.parts if p.kind == StairPartKind.FLIGHT]

    @property
    def landings(self) -> list:
        return [p for p in self.parts if p.kind == StairPartKind.LANDING]

    @property
    def volume(self) -> float:
        return sum(p.shape.volume for p in self.parts if p.shape)
