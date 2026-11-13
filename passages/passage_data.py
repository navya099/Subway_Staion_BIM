from dataclasses import dataclass, field

from bim_data.common_bim_data import CommonBIMData
from passages.passage_type import PassagePartKind


@dataclass
class PassageElementData(CommonBIMData):
    """출구통로 부재 1개 (평면 직선 구간별 바닥·천장 슬래브, 좌·우 벽). IFC: IfcSlab / IfcWall
    Attributes:
        kind: 바닥 / 천장 / 벽
        run: 평면 직선 구간 번호 (꺾이는 꼭짓점마다 1 씩 증가)
        pieces: BoxPiece 목록 (경사 변화점마다 나뉜 조각, 헌치 삼각 조각 포함)
    """
    kind: PassagePartKind = PassagePartKind.FLOOR
    run: int = 1
    pieces: list = field(default_factory=list)

    @property
    def volume(self) -> float:
        return sum(p.volume for p in self.pieces)


@dataclass
class PassageData(CommonBIMData):
    """출구통로 1개 (IFC: IfcElementAssembly 가 부재를 묶음). level = 통로가 붙는 층 이름
    Attributes:
        floor / side: 층, 붙은 측벽 (+1 = t 큰 쪽)
        vertices: 해석된 경로 꼭짓점 (ResolvedVertex: 세계 x, y, 바닥 표고 z, 정거장 s, t)
        corners: 꺾이는 꼭짓점 번호 (0 부터)
        opening_name: 본체 측벽 오프닝 이름
        elements: 부재 목록
    """
    floor: int = 1
    side: int = 1
    vertices: list = field(default_factory=list)
    corners: list = field(default_factory=list)
    opening_name: str = ""
    elements: list = field(default_factory=list)

    def element(self, code: str) -> PassageElementData:
        return next(e for e in self.elements if e.name.endswith("_" + code))

    @property
    def volume(self) -> float:
        return sum(e.volume for e in self.elements)
