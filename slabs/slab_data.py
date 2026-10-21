from dataclasses import dataclass
from typing import Optional
from bim_data.common_bim_data import CommonBIMData
from slabs.slab_shape import SlabShape
from slabs.slab_shape_type import SlabKind, SlabShapeType


@dataclass
class SlabData(CommonBIMData):
    """
    개별 슬래브 요소 데이터
    Attributes:
        kind: 용도 (바닥/중간/천장)
        shape_type: 모양
        shape: 실제 형상 객체 (SlabShape 상속 클래스)
    pos_x/pos_y: 슬래브 평면 중심 (s, t), pos_z: 중심 s 위치의 슬래브 하단 표고
    """
    kind: SlabKind = SlabKind.FLOOR
    shape_type: SlabShapeType = SlabShapeType.ETC
    shape: Optional[SlabShape] = None
