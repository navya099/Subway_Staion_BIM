from dataclasses import dataclass, field

from bim_data.common_bim_data import CommonBIMData
from ventilations.vent_type import VentPartKind


@dataclass
class VentElementData(CommonBIMData):
    """환기구 부재 1개. IFC: 바닥·천장 = IfcSlab, 벽(바깥·중벽·끝·수직구) = IfcWall, 그릴 = IfcAirTerminal(GRILLE)
    Attributes:
        kind: 부재 종류
        code: 환기구 안의 부재 코드 (D1_FLOOR, V1_WALL_F, GRILL2 …)
        pieces: BoxPiece 목록 (그릴은 테두리 4개 + 살)
    """
    kind: VentPartKind = VentPartKind.FLOOR
    code: str = ""
    pieces: list = field(default_factory=list)

    @property
    def volume(self) -> float:
        return sum(p.volume for p in self.pieces)


@dataclass
class VentData(CommonBIMData):
    """환기구 1개 (IFC: IfcElementAssembly 가 부재를 묶음). level = 환기구가 붙는 층 이름
    Attributes:
        floor / side: 층, 붙은 측벽 (+1 = t 큰 쪽)
        cells: 련 수
        vertices: 해석된 경로 꼭짓점
        shafts: 수직 구간 시작 꼭짓점 번호, corners: 평면 꺾임 꼭짓점 번호
        grill_at_shaft: 그릴이 수직구 상단(True) / 덕트 끝 단면(False)
        elements: 콘크리트 부재, grills: 칸별 그릴
    """
    floor: int = 1
    side: int = 1
    cells: int = 1
    vertices: list = field(default_factory=list)
    shafts: list = field(default_factory=list)
    corners: list = field(default_factory=list)
    grill_at_shaft: bool = False
    elements: list = field(default_factory=list)
    grills: list = field(default_factory=list)

    def element(self, code: str) -> VentElementData:
        return next(e for e in self.elements + self.grills if e.code == code)

    @property
    def volume(self) -> float:
        """콘크리트 체적 (그릴 제외)"""
        return sum(e.volume for e in self.elements)
