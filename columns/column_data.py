from dataclasses import dataclass
from typing import Optional
from bim_data.common_bim_data import CommonBIMData
from columns.column_shape_type import ColumnShapeType
from columns.column_shape import ColumnShape


@dataclass
class ColumnData(CommonBIMData):
    """
    개별 기둥요소 데이터
    Attributes:
        shape_type: 모양(사각기둥, 원기둥)
        shape: 실제 형상 객체 (ColumnShape 상속 클래스)
    """
    shape_type: ColumnShapeType = ColumnShapeType.ETC
    shape: Optional[ColumnShape] = None