from dataclasses import dataclass, field
from typing import Optional

from bim_data.common_bim_data import CommonBIMData
from helper.strip_member import StripShape


@dataclass
class EntranceElementData(CommonBIMData):
    """출입구 박스 부재 1개 (바닥·천장 슬래브, 측벽·끝벽·이음벽·칸막이벽). IFC: IfcSlab / IfcWall
    Attributes:
        kind: FLOOR / ROOF / WALL
        code: 부재 코드 (FLOOR_S, ROOF, WALL_L, END_WALL_E, JOINT_WALL_R, PARTITION ...)
        t_range: 출입구 좌표 t 범위
        shape: 띠 부재 형상 (출입구 좌표 s = u)
        pieces: 띠 외 조각 (천장 헌치 BoxPiece · 바깥면 사선 전이 쐐기 TaperPiece, 세계 좌표)
    """
    kind: str = "WALL"
    code: str = ""
    t_range: tuple = (0.0, 0.0)
    shape: Optional[StripShape] = None
    pieces: list = field(default_factory=list)

    @property
    def volume(self) -> float:
        return (self.shape.volume if self.shape else 0.0) + sum(p.volume for p in self.pieces)


@dataclass
class EntranceFinishData(CommonBIMData):
    """출입구 내부 마감 부재 1개 (바닥 마감재·채움 / 벽 마감·막이 / 천장판 / 천장틀). IFC: IfcCovering (FLOORING·CLADDING·CEILING) /
    천장틀 IfcMember. kind = FLOOR / FILL / WALL / CEILING / FRAME, shape = 출입구 좌표 띠"""
    kind: str = "WALL"
    code: str = ""
    t_range: tuple = (0.0, 0.0)
    shape: Optional[StripShape] = None

    @property
    def volume(self) -> float:
        return self.shape.volume if self.shape else 0.0


@dataclass
class EntranceData(CommonBIMData):
    """출입구 1개 (IFC: IfcElementAssembly 가 박스 부재·계단(IfcStair)·에스컬레이터(IfcTransportElement)를 묶음).
    level = 이어 붙은 출구통로의 층 이름
    Attributes:
        passage: 출구통로 이름, frame: 출입구 좌표계(EntranceFrame), layout: 배치 계산 결과(EntranceLayout)
        elements: 박스 부재, stair: StairData(출입구 좌표 띠, 계단 없으면 None), escalator: 첫 EscalatorData 또는 None,
        escalators: 에스컬레이터 대마다 EscalatorData
    """
    passage: str = ""
    floor: int = 1
    frame: object = None
    layout: object = None
    elements: list = field(default_factory=list)
    stair: object = None
    escalator: object = None
    escalators: list = field(default_factory=list)

    finishes: list = field(default_factory=list)       # EntranceFinishData (내부 마감, 마감 끔 = [])

    def element(self, code: str) -> EntranceElementData:
        return next(e for e in self.elements if e.code == code)

    @property
    def box_volume(self) -> float:
        return sum(e.volume for e in self.elements)
