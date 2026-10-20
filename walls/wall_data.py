from dataclasses import dataclass, field
from typing import Optional
from bim_data.common_bim_data import CommonBIMData
from walls.wall_shape import WallShape
from walls.wall_shape_type import WallShapeType


@dataclass
class WallData(CommonBIMData):
    """
    개별 벽체요소 데이터
    Attributes:
        shape_type: 모양(사각벽, 곡선벽)
        shape: 실제 형상 객체 (WallShape 상속 클래스)
    pos_x/pos_y: 벽체 평면 중심 (s, t), pos_z: 중심 s 위치의 벽체 하단 표고
    """
    shape_type: WallShapeType = WallShapeType.ETC
    shape: Optional[WallShape] = None