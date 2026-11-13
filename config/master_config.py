import dataclasses
import math

from columns.column_params import ColumnParameters
from config.alignment import Alignment
from config.alignment_config import AlignmentConfig
from config.station_config import StationParameters
from escalators.escalator_check import check_escalator_layouts, layout_escalators
from openings.opening_check import check_openings
from passages.passage_check import check_passage_layouts, layout_passages
from platforms.platform_params import PlatformParameters
from stairs.stair_check import check_stair_layouts, layout_stairs


@dataclasses.dataclass
class StationProjectConfig:
    """전체 BIM 프로젝트 마스터 컨피그 (모든 서브 요소 수집)"""
    station: StationParameters = dataclasses.field(default_factory=StationParameters)
    platform: PlatformParameters = dataclasses.field(default_factory=PlatformParameters)
    column: ColumnParameters = dataclasses.field(default_factory=ColumnParameters)
    align: Alignment = dataclasses.field(default_factory=AlignmentConfig)
    openings: list = dataclasses.field(default_factory=list)      # list[OpeningSpec]: 슬래브 오프닝 (직접 입력)
    stairs: list = dataclasses.field(default_factory=list)        # list[StairSpec]: 직선 계단 (위층 슬래브 오프닝 자동 생성)
    escalators: list = dataclasses.field(default_factory=list)    # list[EscalatorSpec]: 에스컬레이터 (위층 오프닝·하부 피트 자동 생성)
    passages: list = dataclasses.field(default_factory=list)      # list[PassageSpec]: 출구통로 (본체 측벽 오프닝 자동 생성)

    def __post_init__(self):
        # 층별 기둥 설정이 비어 있으면 전 층 기본 1열 배치로 채움
        if not self.column.floors:
            self.column.floors = ColumnParameters.uniform(self.station.floors).floors

    def validate(self):
        """모든 제원 검사 (GUI 입력 변환 직후, 엔진 생성 직전에 호출)"""
        self.station.validate()
        self.platform.validate()
        self.align.validate()
        st, a = self.station, self.align
        eps = 1e-6
        if st.start_station < a.start_station - eps or st.start_station + st.length > a.end_station + eps:
            raise ValueError(
                f"정거장 구간 STA {st.start_station:.2f} ~ {st.start_station + st.length:.2f} 이(가) "
                f"선형 범위 STA {a.start_station:.2f} ~ {a.end_station:.2f} 를 벗어납니다")
        if not a.is_straight:
            # 곡선 안쪽 가장자리가 곡률 중심을 넘지 않도록: |곡률| * 반폭 < 0.5 (곡선반경 > 정거장 폭)
            half_w = st.width / 2.0 + st.max_wall_t                    # 가장 바깥 외곽 기준
            k_max = max(abs(self.curvature_at(s)) for s in self.sample_s(0.0, st.length, 2.0))
            if k_max * half_w >= 0.5:
                raise ValueError(f"곡선반경({1.0 / k_max:.1f}m)이 정거장 외곽 폭({2 * half_w:g}m)에 비해 너무 작아 "
                                 "곡선 안쪽 벽체가 겹칩니다 (반경 > 외곽 폭 필요)")
        # 계단·에스컬레이터·오프닝은 선형 표고를 쓰므로 정거장 구간 검사 뒤에 (자동 오프닝도 함께 검사)
        stairs, escs = layout_stairs(self), layout_escalators(self)
        check_openings(self.station, self.openings + self._auto_openings(stairs, escs))
        check_stair_layouts(self, stairs)
        check_escalator_layouts(self, escs, stairs)
        check_passage_layouts(self, layout_passages(self))

    def stair_layouts(self) -> list:
        """계단별 배치 계산 결과 (StairLayout). 계단 엔진·슬래브 엔진이 같은 결과를 쓴다"""
        return layout_stairs(self)

    def escalator_layouts(self) -> list:
        """에스컬레이터별 배치 계산 결과 (EscalatorLayout). 에스컬레이터·슬래브·승강장 엔진이 같은 결과를 쓴다"""
        return layout_escalators(self)

    @staticmethod
    def _auto_openings(stairs: list, escs: list) -> list:
        out = [lay.opening for lay in stairs]
        for lay in escs:
            out.append(lay.opening)
            if lay.pit_opening:
                out.append(lay.pit_opening)
        return out

    def all_openings(self) -> list:
        """직접 입력한 오프닝 + 계단·에스컬레이터가 자동으로 뚫는 오프닝 (슬래브 엔진이 이 목록으로 슬래브를 뚫는다)"""
        return list(self.openings) + self._auto_openings(self.stair_layouts(), self.escalator_layouts())

    def passage_layouts(self) -> list:
        """출구통로별 배치 계산 결과 (PassageLayout). 통로·벽체 엔진이 같은 결과를 쓴다"""
        return layout_passages(self)

    def wall_openings(self) -> list:
        """본체 측벽 오프닝 [(이름, 층, side, s0, s1, z_rel0, z_rel1)]: 출구통로 접합부 (z_rel = 바닥 슬래브 상면 기준)"""
        return [lay.wall_opening for lay in self.passage_layouts()]

    def platform_holes(self) -> list:
        """승강장 슬래브에 뚫는 구멍 [(이름, s0, s1, t0, t1)]: 승강장 위 에스컬레이터의 하부 피트"""
        return [lay.platform_hole for lay in self.escalator_layouts() if lay.platform_hole]

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

    def curvature_at(self, s: float) -> float:
        """정거장 로컬 거리 s 에서의 평면 곡률 (1/m, 좌회전 +)"""
        return self.align.curvature_at(self._sta(s))

    def sample_s(self, s0: float, s1: float, step: float = 5.0) -> list[float]:
        """정거장 로컬 구간 [s0, s1] 의 折線 근사용 측점. 직선은 [s0, s1] 뿐이라 부재가 단일 각기둥이 된다"""
        if self.align.is_straight:
            return [s0, s1]
        base = self.station.start_station
        return [a - base for a in self.align.sample_stations(base + s0, base + s1, step)]

    def to_world(self, s: float, t: float) -> tuple[float, float]:
        """정거장 로컬 (s, t) → WCS 평면 좌표. t 는 선형 중심에서 진행방향 왼쪽(+)으로의 직교 거리"""
        sta = self._sta(s)
        x, y = self.align.point_at(sta)
        th = self.align.azimuth_at(sta)
        return x - t * math.sin(th), y + t * math.cos(th)

    def origin(self) -> tuple[float, float]:
        """정거장 시점(s=0)의 WCS 평면 좌표"""
        return self.to_world(0.0, 0.0)
