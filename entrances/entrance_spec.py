import dataclasses
from typing import Optional

from escalators.escalator_spec import EscalatorSpec
from stairs.stair_spec import StairSpec


@dataclasses.dataclass
class EntranceSpec:
    """출입구 1개의 입력 제원. 출구통로 끝(마지막 꼭짓점, 이음면)에서 통로 마지막 구간 방향으로 이어지는 경사 박스.

    - 박스 안에 계단(별도 계단 슬래브)과 에스컬레이터를 나란히 둔다: 내공 폭 = 계단 폭 + 칸막이벽 + 에스컬레이터 구역 폭
    - 높이는 지표 EL 과 통로 끝 바닥 표고의 차이로 모두 자동 계산 (계단 단수·계단참, 에스컬레이터 WP, 박스 길이)
    - 종단(1단계): 바닥 = 에스컬레이터 트러스 하면(양 끝 피트), 천장 = 에스컬레이터 스텝 코 선과 나란한 직선(하부는 통로 천장 높이),
      천장은 상면이 지표면에 닿는 곳에서 끝나고 그 뒤 상단 끝벽까지는 지붕 없는 개구부(측벽은 지표 + 파라펫 높이)
    - 벽·슬래브는 하나의 두께, 상부 헌치는 천장 슬래브 아래 양쪽 모서리

    Attributes:
        passage: 이어 붙일 출구통로 이름
        ground_el: 지상 도착부 지표면 절대 표고 (m)
        stair_width / partition_t / escalator_zone: 계단 폭, 칸막이벽 두께, 에스컬레이터 구역 폭 (m)
        escalator: 에스컬레이터를 둘지 (False 면 내공 폭 = 계단 폭, 칸막이벽 없음)
        escalator_side: 에스컬레이터 쪽 +1 = 오르는 방향 왼쪽(+t), -1 = 오른쪽
        wall_t: 벽·슬래브 두께 (m)
        haunch_w / haunch_h: 천장 헌치 수평 / 연직 크기 (m, 0 이면 없음)
        lower_margin: 하부 이음벽 안쪽 면 ~ 에스컬레이터 트러스 하단 끝 (m)
        top_margin: 계단·에스컬레이터 상단 끝 ~ 상단 끝벽 안쪽 면 (m)
        parapet: 개구부 측벽·끝벽의 지표면 위 높이 (m)
        stair_offset: 계단 첫 챌판 위치 = 하부 피트 끝 + stair_offset (m, 0 이하). None 이면 자동: 피트 끝에서 시작하되
                      계단 슬래브가 바닥 아래로 내려가면 바닥 위에 머물 때까지 하부 수평부 쪽으로 앞당김
        riser_max / tread / flight_rise_max / landing_len / stair_slab_t / stair_headroom: 계단 규칙 (계단 객체와 같은 의미)
        esc_*: 에스컬레이터 제원 (에스컬레이터 객체와 같은 의미)
        name: 비우면 EN + 일련번호
    """
    passage: str = ""
    ground_el: float = 0.0
    stair_width: float = 1.75
    partition_t: float = 0.2
    escalator_zone: float = 3.31
    escalator: bool = True
    escalator_side: int = 1
    wall_t: float = 0.8
    haunch_w: float = 0.3
    haunch_h: float = 0.3
    lower_margin: float = 1.0
    top_margin: float = 1.0
    parapet: float = 0.3
    stair_offset: Optional[float] = None    # None = 자동 (피트 끝에서 시작, 바닥 아래로 가면 하부 수평부 쪽으로 앞당김)
    riser_max: float = 0.18
    tread: float = 0.30
    flight_rise_max: float = 3.0
    landing_len: float = 1.0           # 실무 도면 기준 (출입구 계단참 0.9 ~ 1.1m)
    stair_slab_t: float = 0.2
    stair_headroom: float = 2.1
    esc_angle_deg: float = 30.0
    esc_step_width: float = 1.0
    esc_truss_width: float = 1.6
    esc_truss_depth: float = 1.15
    esc_lower_ext: float = 2.4
    esc_upper_ext: float = 2.8
    esc_lower_flat_steps: int = 2
    esc_upper_flat_steps: int = 3
    esc_step_depth: float = 0.4
    esc_handrail_height: float = 1.0
    esc_headroom: float = 2.3
    name: str = ""

    @property
    def inner_width(self) -> float:
        if not self.escalator:
            return self.stair_width
        return self.stair_width + self.partition_t + self.escalator_zone

    def zones(self) -> dict:
        """폭 방향 구역 (t 범위, 출입구 좌표: 오르는 방향 왼쪽 +). stair / partition / escalator"""
        a = self.inner_width / 2.0
        if not self.escalator:
            return {"stair": (-a, a)}
        if self.escalator_side > 0:                  # 왼쪽(+t) 에 에스컬레이터
            return {"stair": (-a, -a + self.stair_width),
                    "partition": (-a + self.stair_width, -a + self.stair_width + self.partition_t),
                    "escalator": (a - self.escalator_zone, a)}
        return {"escalator": (-a, -a + self.escalator_zone),
                "partition": (a - self.stair_width - self.partition_t, a - self.stair_width),
                "stair": (a - self.stair_width, a)}

    def stair_spec(self) -> StairSpec:
        t0, t1 = self.zones()["stair"]
        return StairSpec(lower_floor=1, s_start=0.0, direction=1, t_center=(t0 + t1) / 2.0, width=t1 - t0,
                         riser_max=self.riser_max, tread=self.tread, flight_rise_max=self.flight_rise_max,
                         landing_len=self.landing_len, waist_t=self.stair_slab_t, headroom=self.stair_headroom)

    def escalator_spec(self) -> EscalatorSpec:
        t0, t1 = self.zones()["escalator"]
        return EscalatorSpec(lower_floor=1, s_wp=0.0, direction=1, t_center=(t0 + t1) / 2.0,
                             angle_deg=self.esc_angle_deg, step_width=self.esc_step_width,
                             truss_width=self.esc_truss_width, truss_depth=self.esc_truss_depth,
                             lower_ext=self.esc_lower_ext, upper_ext=self.esc_upper_ext,
                             lower_flat_steps=self.esc_lower_flat_steps, upper_flat_steps=self.esc_upper_flat_steps,
                             step_depth=self.esc_step_depth, handrail_height=self.esc_handrail_height,
                             headroom=self.esc_headroom)


def resolve_entrance_names(specs: list) -> list[str]:
    names = [sp.name.strip() or f"EN{i}" for i, sp in enumerate(specs, start=1)]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ValueError(f"출입구 이름이 중복됩니다: {', '.join(dup)}")
    return names
