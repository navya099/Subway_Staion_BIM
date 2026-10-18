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
    column: ColumnParameters = dataclasses.field(default_factory=ColumnParameters)  # 신규 추가
    align: AlignmentConfig = dataclasses.field(default_factory=AlignmentConfig)