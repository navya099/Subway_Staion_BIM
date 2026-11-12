from dataclasses import dataclass, field
from typing import Optional

from bim_data.common_bim_data import CommonBIMData
from escalators.escalator_type import EscalatorPartKind
from helper.strip_member import StripShape


@dataclass
class EscalatorPartData(CommonBIMData):
    """에스컬레이터 구성 부재 1개 (트러스 / 스텝 / 난간 패널 / 핸드레일).
    pos_x/pos_y: 평면 중심 (s, t), pos_z: 하면 최저 표고 (절대)
    Attributes:
        kind: 부재 종류
        side: 난간·핸드레일의 쪽 (+1 = t 큰 쪽, -1), 트러스·스텝은 0
        t_range: (t0, t1)
    """
    kind: EscalatorPartKind = EscalatorPartKind.TRUSS
    side: int = 0
    t_range: tuple = (0.0, 0.0)
    shape: Optional[StripShape] = None


@dataclass
class EscalatorData(CommonBIMData):
    """에스컬레이터 1대 (IFC: IfcTransportElement ESCALATOR 가 구성 부재를 묶음). level = 시작 층 이름
    Attributes:
        lower_floor / direction / on_platform: 시작 층, 오르는 방향(±1), 승강장 상면에서 시작 여부
        angle_deg / rise / run: 경사각, 층간 실제 표고차(하부 WP ~ 상부 WP), WP 간 수평 거리
        s_wp: (하부 WP s, 상부 WP s)
        s_range / t_range: 트러스 평면 범위
        opening_names: 자동으로 뚫은 오프닝 이름들 (위층 슬래브, 하부 피트)
        parts: 트러스, 스텝, 난간(좌/우), 핸드레일(좌/우)
    """
    lower_floor: int = 1
    direction: int = 1
    on_platform: bool = False
    angle_deg: float = 30.0
    rise: float = 0.0
    run: float = 0.0
    s_wp: tuple = (0.0, 0.0)
    s_range: tuple = (0.0, 0.0)
    t_range: tuple = (0.0, 0.0)
    opening_names: list = field(default_factory=list)
    parts: list = field(default_factory=list)

    def part(self, kind: EscalatorPartKind, side: int = 0):
        return next(p for p in self.parts if p.kind == kind and p.side == side)

    @property
    def volume(self) -> float:
        return sum(p.shape.volume for p in self.parts if p.shape)
