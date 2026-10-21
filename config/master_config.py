import dataclasses
import math

from columns.column_params import ColumnParameters
from config.alignment import Alignment
from config.alignment_config import AlignmentConfig
from config.station_config import StationParameters
from platforms.platform_params import PlatformParameters


@dataclasses.dataclass
class StationProjectConfig:
    """전체 BIM 프로젝트 마스터 컨피그 (모든 서브 요소 수집)"""
    station: StationParameters = dataclasses.field(default_factory=StationParameters)
    platform: PlatformParameters = dataclasses.field(default_factory=PlatformParameters)
    column: ColumnParameters = dataclasses.field(default_factory=ColumnParameters)
    align: Alignment = dataclasses.field(default_factory=AlignmentConfig)

    def __post_init__(self):
        # 층별 기둥 설정이 비어 있으면 전 층 기본 1열 배치로 채움
        if not self.column.floors:
            self.column.floors = ColumnParameters.uniform(self.station.floors).floors

    def validate(self):
        """모든 제원 검사 (GUI 입력 변환 직후, 엔진 생성 직전에 호출)"""
        self.station.validate()
        self.platform.validate()
        self.align.validate()
        if not self.align.is_straight:
            raise NotImplementedError("곡선/종곡선 선형은 아직 지원하지 않습니다. 정거장 부재를 측점 구간별로 나누어 "
                                      "배치하는 단계가 필요합니다 (현재는 직선 + 일정 구배 선형만 가능).")
        st, a = self.station, self.align
        eps = 1e-6
        if st.start_station < a.start_station - eps or st.start_station + st.length > a.end_station + eps:
            raise ValueError(
                f"정거장 구간 STA {st.start_station:.2f} ~ {st.start_station + st.length:.2f} 이(가) "
                f"선형 범위 STA {a.start_station:.2f} ~ {a.end_station:.2f} 를 벗어납니다")

    # ---------- 선형 접점: 엔진/내보내기는 이 메서드로만 선형에 접근한다 ----------
    def _sta(self, s: float) -> float:
        """정거장 로컬 거리 s(0~L) → 절대 측점"""
        return self.station.start_station + s

    def lv(self, s: float) -> float:
        """정거장 로컬 거리 s 에서의 선형 표고"""
        return self.align.elevation_at(self._sta(s))

    def theta_at(self, s: float) -> float:
        """정거장 로컬 거리 s 에서의 선형 진행 방향각 (rad)"""
        return self.align.azimuth_at(self._sta(s))

    def grade_permil(self, s: float = 0.0) -> float:
        """정거장 로컬 거리 s 에서의 종단 구배 (‰)"""
        return self.align.grade_at(self._sta(s)) * 1000.0

    def to_world(self, s: float, t: float) -> tuple[float, float]:
        """정거장 로컬 (s, t) → WCS 평면 좌표. t 는 선형 중심에서 진행방향 왼쪽(+)으로의 직교 거리"""
        sta = self._sta(s)
        x, y = self.align.point_at(sta)
        th = self.align.azimuth_at(sta)
        return x - t * math.sin(th), y + t * math.cos(th)

    def origin(self) -> tuple[float, float]:
        """정거장 시점(s=0)의 WCS 평면 좌표"""
        return self.to_world(0.0, 0.0)
