import dataclasses

from columns.column_shape_type import ColumnShapeType


@dataclasses.dataclass
class ColumnSpec:
    """기둥 1개의 단면 규격
    Attributes:
        shape_type: 사각기둥 / 원기둥
        width: 사각기둥 폭 (선형 진행 방향, m)
        depth: 사각기둥 두께 (선형 직교 방향, m)
        radius: 원기둥 반지름 (m)  (지름 1.0m → 0.5)
    """
    shape_type: ColumnShapeType = ColumnShapeType.RECTANGLE
    width: float = 0.8
    depth: float = 0.8
    radius: float = 0.5

    @property
    def half_s(self) -> float:
        return self.radius if self.shape_type == ColumnShapeType.CIRCLE else self.width / 2.0

    @property
    def half_t(self) -> float:
        return self.radius if self.shape_type == ColumnShapeType.CIRCLE else self.depth / 2.0


@dataclasses.dataclass
class ColumnRowSpec:
    """기둥 1열 배치
    Attributes:
        t_offset: 선형 직교 방향 위치 (m, 중심선 0, 진행방향 기준 오른쪽 +)
        interval: 열 안의 종방향 배치 간격 (m)
        start_offset: 시점 마감벽 안쪽 면에서 첫 기둥 중심까지 거리 (m). 종점도 대칭 적용
        pattern: 열을 따라 순환 반복되는 기둥 규격 (혼합 배치는 2개 이상)
    """
    t_offset: float = 0.0
    interval: float = 10.0
    start_offset: float = 1.0
    pattern: list = dataclasses.field(default_factory=lambda: [ColumnSpec()])


@dataclasses.dataclass
class FloorColumnSpec:
    """한 층의 기둥 열 목록"""
    rows: list = dataclasses.field(default_factory=lambda: [ColumnRowSpec()])


@dataclasses.dataclass
class ColumnParameters:
    """중앙 기둥 제원 및 배치 파라미터
    Attributes:
        sync_with_platform: 최하층 기둥 바닥을 승강장 상면에 맞출지 여부
        floors: {층 번호(1=최하층): FloorColumnSpec}. 키에 없는 층에는 기둥이 없음
    """
    sync_with_platform: bool = True
    floors: dict = dataclasses.field(default_factory=dict)

    @property
    def target_floors(self) -> list[int]:
        return sorted(self.floors)

    @classmethod
    def uniform(cls, floor_count: int, interval: float = 10.0, spec: ColumnSpec | None = None,
                sync_with_platform: bool = True) -> "ColumnParameters":
        """모든 층에 같은 규격을 1열(중앙)로 배치"""
        spec = spec or ColumnSpec()
        floors = {n: FloorColumnSpec(rows=[ColumnRowSpec(interval=interval, pattern=[spec])])
                  for n in range(1, floor_count + 1)}
        return cls(sync_with_platform=sync_with_platform, floors=floors)
