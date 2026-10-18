from dataclasses import dataclass, field
from typing import List, Optional
from columns.column_data import ColumnData


@dataclass
class ColumnPackage:
    """
    층별/구역별 기둥 요소 그룹 데이터 패키지
    Attributes:
        package_id: 패키지/그룹 ID (예: "PKG_B1F_COLUMNS")
        level: 소속 층 (예: "B1F", "B2F")
        columns: 패키지에 포함된 기둥 데이터 리스트
        description: 그룹 설명
    """
    package_id: str = ""
    level: str = ""
    columns: List[ColumnData] = field(default_factory=list)
    description: str = ""

    def add_column(self, column: ColumnData):
        """패키지에 기둥 객체 추가"""
        self.columns.append(column)

    @property
    def total_count(self) -> int:
        """패키지 내 전체 기둥 개수"""
        return len(self.columns)

    @property
    def total_volume(self) -> float:
        """
        패키지 내 모든 기둥의 총 콘크리트 체적(m³) 산출
        (각 ColumnData의 shape.volume 연산 활용)
        """
        total = 0.0
        for col in self.columns:
            if col.shape and hasattr(col.shape, 'volume'):
                total += col.shape.volume
        return total

    def get_column_by_name(self, name: str) -> Optional[ColumnData]:
        """이름으로 개별 기둥 검색"""
        for col in self.columns:
            if col.name == name:
                return col
        return None