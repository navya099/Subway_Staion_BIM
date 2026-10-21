from dataclasses import dataclass
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
        shape: 실제 형상 객체 (WallShape 상속 클래스)
    pos_x/pos_y: 벽체 평면 중심 (s, t), pos_z: 중심 s 위치의 벽체 하단 표고
    """
    role: WallRole = WallRole.LEFT
    shape_type: WallShapeType = WallShapeType.ETC
    shape: Optional[WallShape] = None