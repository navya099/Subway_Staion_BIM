import dataclasses


@dataclasses.dataclass
class ColumnParameters:
    """중앙 기둥 제원 및 배치 파라미터
    Attributes:
        interval: 배치 간격
        width: 기둥 폭 (선형 진행 방향, m)
        depth: 기둥 두께 (선형 직교 방향, m)
        sync_with_platform: 승강장층(최하층) 기둥 높이/위치 동기화 여부
        target_floors: 기둥을 배치할 층 번호 리스트
        custom_height_offset: 개별 조정용 오프셋
    """
    interval: float = 3  # 기둥 종방향 배치 간격 (m)
    width: float = 1  # 기둥 폭 (선형 진행 방향, m)
    depth: float = 0.4  # 기둥 두께 (선형 직교 방향, m)

    # 층별 적용 및 승강장 동기화 옵션
    sync_with_platform: bool = True  # 승강장층(최하층) 기둥 높이/위치 동기화 여부
    target_floors: list[int] = dataclasses.field(default_factory=lambda: [1, 2])  # 기둥을 배치할 층 번호 리스트 (1부터 시작)

    # 개별 조정용 오프셋 (동기화가 False일 때 활용)
    custom_height_offset: float = 0.0