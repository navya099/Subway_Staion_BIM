from dataclasses import dataclass, field
from typing import Optional
from bim_data.common_bim_data import CommonBIMData
from walls.wall_shape import WallShape
from walls.wall_shape_type import WallRole, WallShapeType


@dataclass
class WallData(CommonBIMData):
    """
    개별 벽체요소 데이터
    Attributes:
        role: 위치 역할 (시점/종점 마감벽, 좌/우 외벽)
        shape_type: 모양(사각벽, 곡선벽)
        shape: 실제 형상 객체 (WallShape 상속 클래스). 오프닝을 뚫기 전 전체
        pieces: 오프닝(출구통로 접합부)을 뺀 직사각형 조각 (s–z 면에서 분해, 오프닝이 없으면 빈 목록)
        openings: 이 벽체의 오프닝 (OpeningData)
    pos_x/pos_y: 벽체 평면 중심 (s, t), pos_z: 중심 s 위치의 벽체 하단 표고
    """
    role: WallRole = WallRole.LEFT
    shape_type: WallShapeType = WallShapeType.ETC
    shape: Optional[WallShape] = None
    pieces: list = field(default_factory=list)
    openings: list = field(default_factory=list)

    @property
    def members(self) -> list:
        """작도·내보내기 대상 덩어리: 오프닝이 있으면 조각들, 없으면 전체"""
        return self.pieces if self.pieces else [self]

    @property
    def net_volume(self) -> float:
        return sum(m.shape.volume for m in self.members if m.shape)