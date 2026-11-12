from dataclasses import dataclass
from typing import Optional

from bim_data.common_bim_data import CommonBIMData
from openings.opening_kind import OpeningKind
from slabs.slab_shape import SlabShape


@dataclass
class OpeningData(CommonBIMData):
    """슬래브에 뚫린 오프닝 1개 (오프닝 1개가 여러 슬래브를 뚫으면 슬래브마다 1개씩 만들어짐)
    pos_x/pos_y: 오프닝 평면 중심 (s, t), pos_z: 중심 s 위치의 슬래브 하단 표고.
    shape: 슬래브와 같은 두께의 직사각 각기둥 (슬래브 부재와 같은 기하 규약)
    """
    kind: OpeningKind = OpeningKind.STAIR
    slab_name: str = ""
    shape: Optional[SlabShape] = None
    s_range: tuple = (0.0, 0.0)
    t_range: tuple = (0.0, 0.0)
