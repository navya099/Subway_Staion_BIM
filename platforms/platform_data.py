from dataclasses import dataclass
from typing import Optional
from bim_data.common_bim_data import CommonBIMData
from platforms.platform_shape import PlatformShape
from platforms.platform_type import PlatformPart, PlatformSide


@dataclass
class PlatformData(CommonBIMData):
    """
    개별 승강장 요소 데이터
    Attributes:
        part: 구성 부재 (슬래브 / 지지벽체)
        side: 좌/우 (상대식)
        shape: 실제 형상 객체 (PlatformShape 상속 클래스)
    pos_x/pos_y: 승강장 평면 중심 (s, t), pos_z: 중심 s 위치의 승강장 슬래브 하단 표고
    """
    part: PlatformPart = PlatformPart.SLAB
    side: PlatformSide = PlatformSide.LEFT
    shape: Optional[PlatformShape] = None
