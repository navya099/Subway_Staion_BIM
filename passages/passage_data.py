from dataclasses import dataclass, field

from bim_data.common_bim_data import CommonBIMData
from passages.passage_type import PassagePartKind


@dataclass
class PassageElementData(CommonBIMData):
    """출구통로 부재 1개 (구간별 바닥·천장 슬래브, 측벽). IFC: IfcSlab / IfcWall
    Attributes:
        kind: 바닥 / 천장 / 벽
        seg: 1 = 첫 구간, 2 = 꺾임 후 구간
        pieces: BoxPiece 목록 (구배·수평 구간, 헌치 삼각 조각 포함)
    """
    kind: PassagePartKind = PassagePartKind.FLOOR
    seg: int = 1
    pieces: list = field(default_factory=list)

    @property
    def volume(self) -> float:
        return sum(p.volume for p in self.pieces)


@dataclass
class PassageData(CommonBIMData):
    """출구통로 1개 (IFC: IfcElementAssembly 가 부재를 묶음). level = 통로가 붙는 층 이름
    Attributes:
        floor / side / turn / s_center: 층, 측벽 방향, 꺾임 방향, 중심 STA(s)
        frame: 통로 좌표계 (PassageFrame)
        bent: L자 여부
        opening_name: 본체 측벽 오프닝 이름
        elements: 부재 목록
    """
    floor: int = 1
    side: int = 1
    turn: int = 1
    s_center: float = 0.0
    frame: object = None
    bent: bool = False
    opening_name: str = ""
    elements: list = field(default_factory=list)

    def element(self, code: str) -> PassageElementData:
        return next(e for e in self.elements if e.name.endswith("_" + code))

    @property
    def volume(self) -> float:
        return sum(e.volume for e in self.elements)
