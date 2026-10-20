import dataclasses

from columns.column_params import ColumnParameters
from config.alignment_config import AlignmentConfig
from config.station_config import StationParameters
from platforms.platform_params import PlatformParameters


@dataclasses.dataclass
class StationProjectConfig:
    """전체 BIM 프로젝트 마스터 컨피그 (모든 서브 요소 수집)"""
    station: StationParameters = dataclasses.field(default_factory=StationParameters)
    platform: PlatformParameters = dataclasses.field(default_factory=PlatformParameters)
    column: ColumnParameters = dataclasses.field(default_factory=ColumnParameters)
    align: AlignmentConfig = dataclasses.field(default_factory=AlignmentConfig)

    def __post_init__(self):
        # 층별 기둥 설정이 비어 있으면 전 층 기본 1열 배치로 채움
        if not self.column.floors:
            self.column.floors = ColumnParameters.uniform(self.station.floors).floors

    def lv(self, s: float) -> float:
        """정거장 로컬 거리 s(0~L)에서의 선형 표고 (정거장 시작 측점 반영)"""
        return self.align.calc_align_lv(self.station.start_station + s)

    def origin(self) -> tuple[float, float]:
        """정거장 시점(s=0)의 WCS 평면 좌표"""
        return self.align.origin_at(self.station.start_station)
