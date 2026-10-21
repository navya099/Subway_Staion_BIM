from dataclasses import dataclass
from typing import Optional

from bim_data.common_bim_data import CommonBIMData
from boxes.box_shape import BoxShape


@dataclass
class BoxData(CommonBIMData):
    """
    개별 박스요소 데이터
    Attributes:
        shape: 실제 형상 객체
    """
    shape: Optional[BoxShape] = None