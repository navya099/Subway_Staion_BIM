from abc import ABC
from dataclasses import dataclass
from shapes.base_shape import BaseShape


@dataclass
class BoxShape(BaseShape):
    """환승통로, 환기구 등 박스 형상 객체 정의
    Attributes:
        width: 박스 전체 폭
        height: 박스 전체 높이
        length: 박스 전체 길이
        wall_t: 외벽 두께
        slab_b: 바닥 슬래브 두께
        slab_t: 천장 슬래브 두께
        use_top_hunch: 상부 헌치 사용 여부
        top_hunch_w: 상부 헌치 수평 크기 (m)
        top_hunch_h: 상부 헌치 수직 크기 (m)
        use_bottom_hunch: 하부 헌치 사용 여부
        bottom_hunch_w: 하부 헌치 수평 크기 (m)
        bottom_hunch_h: 하부 헌치 수직 크기 (m)
        is_start_closed: 시점 폐합 여부
        start_wall_t: 시점 마감벽 두께
        is_end_closed: 종점 폐합 여부
        end_wall_t: 종점 마감벽 두께
        cells: 련수
    """
    width: float = 20.0  # 박스 전체 폭
    height: float = 12.0  # 박스 전체 높이
    length: float = 200.0  # 박스 전체 길이
    wall_t: float = 1.0  # 외벽 두께
    slab_b: float = 1.2  # 바닥 슬래브 두께
    slab_t: float = 1.0  # 천장 슬래브 두께

    # 🌟 상/하부 헌치 개별 분리
    use_top_hunch: bool = True  # 상부 헌치 사용 여부
    top_hunch_w: float = 0.3  # 상부 헌치 수평 크기 (m)
    top_hunch_h: float = 0.3  # 상부 헌치 수직 크기 (m)

    use_bottom_hunch: bool = False  # 하부 헌치 사용 여부
    bottom_hunch_w: float = 0.0  # 하부 헌치 수평 크기 (m)
    bottom_hunch_h: float = 0.0  # 하부 헌치 수직 크기 (m)

    # 폐합 및 마감벽 관련 속성
    is_start_closed: bool = False  # 시점 폐합 여부
    start_wall_t: float = 1.0  # 시점 마감벽 두께
    is_end_closed: bool = False  # 종점 폐합 여부
    end_wall_t: float = 1.0  # 종점 마감벽 두께

    # 기타
    cells: int = 1  # 련수

    @property
    def volume(self) -> float:
        """시·종단 마감벽 및 상/하부 헌치를 모두 고려한 정밀 콘크리트 체적 계산"""
        # 1. 전체 외형 체적 (외곽 크기 기준)
        ext_vol = self.width * self.height * self.length

        # 2. 내부 빈 공간(Void)의 유효 길이 계산 (마감벽 두께 반영)
        eff_length = self.length
        if self.is_start_closed:
            eff_length -= self.start_wall_t
        if self.is_end_closed:
            eff_length -= self.end_wall_t

        eff_length = max(0.0, eff_length)

        # 3. 기본 내부 빈 공간 단면적 및 체적 계산
        int_w = self.width - (2.0 * self.wall_t)
        int_h = self.height - (self.slab_b + self.slab_t)
        int_vol = max(0.0, int_w * int_h * eff_length)

        # 4. 상부 헌치 부피 반영 (유효 길이 기준)
        if self.use_top_hunch and self.top_hunch_w > 0 and self.top_hunch_h > 0:
            top_hunch_area = self.top_hunch_w * self.top_hunch_h  # 2개소 삼각형 면적 합산
            top_hunch_vol = top_hunch_area * eff_length
            int_vol -= top_hunch_vol  # 내부 빈 공간에서 차감

        # 5. 하부 헌치 부피 반영 (유효 길이 기준)
        if self.use_bottom_hunch and self.bottom_hunch_w > 0 and self.bottom_hunch_h > 0:
            bottom_hunch_area = self.bottom_hunch_w * self.bottom_hunch_h
            bottom_hunch_vol = bottom_hunch_area * eff_length
            int_vol -= bottom_hunch_vol

        # 마감벽 구간은 int_vol(유효 길이 기준)에서 이미 제외되어 속찬 콘크리트로 계산됨 → 별도 보정 불필요
        return ext_vol - int_vol
