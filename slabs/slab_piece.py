from dataclasses import dataclass
from typing import Optional

from slabs.slab_shape import SlabShape


@dataclass
class SlabPiece:
    """오프닝을 뺀 슬래브의 직사각형 조각 (슬래브와 같은 중심·형상 규약: pos_x/pos_y = (s, t) 중심, pos_z = 하단 표고)"""
    name: str = ""
    pos_x: float = 0.0
    pos_y: float = 0.0
    pos_z: float = 0.0
    shape: Optional[SlabShape] = None
