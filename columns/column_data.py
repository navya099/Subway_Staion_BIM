from dataclasses import dataclass

from bim_data.common_bim_data import CommonBIMData
from columns.column_shape_type import ColumnShapeType


@dataclass
class ColumnData(CommonBIMData):
    """
    개별 기둥요소 데이터
    Attributes:
        shape_type: 모양(사각기둥, 원기둥)
        shape: 실제 객체
    """
    shape_type: ColumnShapeType = ColumnShapeType.ETC
    shape = None
