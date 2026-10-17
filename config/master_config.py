import dataclasses
from config.cadconfig import StationParameters
from platforms.platform_params import PlatformParameters


@dataclasses.dataclass
class StationProjectConfig:
    """전체 BIM 프로젝트 마스터 컨피그 (모든 서브 요소 수집)"""
    station: StationParameters = dataclasses.field(default_factory=StationParameters)
    platform: PlatformParameters = dataclasses.field(default_factory=PlatformParameters)

    # 추후 확장 예시:
    # column: ColumnParameters = dataclasses.field(default_factory=ColumnParameters)
    # stair: StairParameters = dataclasses.field(default_factory=StairParameters)