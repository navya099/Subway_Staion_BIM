import dataclasses
from typing import Optional

from escalators.escalator_spec import EscalatorSpec
from stairs.stair_spec import StairSpec


@dataclasses.dataclass
class EntranceSpec:
    """출입구 1개의 입력 제원. 출구통로 끝(마지막 꼭짓점, 이음면)에서 통로 마지막 구간 방향으로 이어지는 경사 박스.

    - 박스 안에 계단(별도 계단 슬래브)과 에스컬레이터를 나란히 둔다: 내공 폭 = 계단 폭 + 칸막이벽 + 에스컬레이터 구역 폭
    - 높이는 지표 EL 과 통로 끝 바닥 표고의 차이로 모두 자동 계산 (계단 단수·계단참, 에스컬레이터 WP, 박스 길이)
    - 종단: 바닥 = 에스컬레이터 트러스 하면(양 끝 피트), 천장 하면 = 통로 천장 높이 · 에스컬레이터 스텝 코 선 + 머리 높이 ·
      계단 피치선(디딤판 코를 잇는 선, 계단참은 수평) + 계단 머리 높이 중 가장 높은 것 (실무 도면처럼 계단참에서 꺾임).
      천장은 상면이 지표 − 흙 덮개(roof_cover)에 닿는 곳에서 끝나고 그 뒤 상단 끝벽까지는 지붕 없는 개구부(측벽은 지표 + 파라펫)
    - 벽·슬래브 두께 = wall_t 하나, 또는 두께 구간(thickness_zones: 출입구 진행 거리 u 구간마다 두께 — 실무 도면 700/800/900)이면
      구간마다 바깥면이 계단식으로 바뀜 (내공 고정). 상부 헌치는 천장 슬래브 아래 양쪽 모서리. 바닥 아래 버림 콘크리트(lean_t)

    Attributes:
        passage: 이어 붙일 출구통로 이름
        ground_el: 지상 도착부 지표면 절대 표고 (m). None 이면 정거장 공통 지표 EL (StationParameters.ground_el)
        stair_width / partition_t / escalator_zone: 계단 폭, 칸막이벽 두께, 에스컬레이터 구역 폭 (m)
        escalator: 에스컬레이터를 둘지 (False 면 내공 폭 = 계단 폭, 칸막이벽 없음)
        stair: 계단을 둘지 (False 면 에스컬레이터만 — 내공 폭 = 에스컬레이터 구역 × 대수, 칸막이벽 없음)
        escalator_count: 에스컬레이터 대수 (모두 같은 제원, 트러스끼리 이격 없이 붙여 나란히 — 실무). 에스컬레이터 구역 폭 =
                         escalator_zone(1대일 때 구역, 양쪽 벽·칸막이 여유 포함) + (대수 − 1) × 트러스 외폭
        escalator_side: 에스컬레이터 쪽 +1 = 오르는 방향 왼쪽(+t), -1 = 오른쪽
        wall_t: 벽·슬래브 두께 (m, 두께 구간이 없을 때·첫 구간 앞)
        thickness_zones: 두께 구간 [(u 시작, 두께), ...] — u = 이음면(통로 끝)에서 출입구 진행 거리 (m). 그 u 부터 다음 구간 앞까지
                         측벽·천장·바닥 슬래브 두께. 비우면 wall_t 일정
        roof_cover: 천장 슬래브가 끝나는 흙 덮개 두께 (m, 천장 상면이 지표 − roof_cover 에 닿는 곳에서 끝남, 0 = 지표에 닿는 곳)
        lean_t / lean_ext: 바닥 슬래브 아래 버림 콘크리트 두께 (0 = 없음) / 외곽 밖으로 나오는 폭 (m)
        top_rise: 상부 승강구(계단·에스컬레이터 위 끝, 도착부 바닥)를 지표보다 높이는 높이 (m, 0 = 지표). 주면 상단 끝벽은 승강구 높이까지만
                  (앞면 개방 = 출구), 박스 앞에 바깥 경사로(ramp_width 폭, 기울기 1/ramp_ratio, 에스컬레이터 쪽 벽 옆)와 계단(나머지 폭,
                  단높이 상한 out_riser_max, 단너비 out_tread)이 지표까지 내려감
        open_narrow: 지붕 없는 개구부(천장 슬래브 끝 u_re 뒤)의 내공 축소 (한쪽, m, 0 = 같음) — 실무 평면도: 내공 5,260 → 4,860.
                     계단은 벽 쪽 변이 그만큼 좁아짐, 에스컬레이터는 벽 쪽 여유가 그 이상이어야 함
        open_wall_t: 개구부 측벽 두께 (m, None = 두께 구간 그대로)
        taper_ratio: 바깥면 사선 전이 (전이 길이 / 바깥면 차, 0 = 직각 계단) — 두께가 바뀌는 곳(두께 구간 경계·개구부 시작)에서
                     두꺼운 쪽 바깥면이 얇은 구간 안으로 사선으로 줄어듦. 실무 평면도 2 (차 100 → 200, 차 600 → 1,200)
        outdoor: 박스 앞 바깥 접근 형식 (top_rise > 0 일 때) — 'steps' = 바깥 경사로·계단 (위 top_rise 설명), 'forecourt' = 앞마당
                 접속 슬래브 (실무 상세 "a": 상단 끝벽 바깥면부터 개구부 내공 폭 전체, 승강구 높이로 평탄 fc_flat 뒤 기울기 1/ramp_ratio 로
                 지표까지 내려감 — 포장 fc_pave_t 아래 슬래브 fc_slab_t + 버림 fc_lean_t, 끝에 끝단 보 fc_beam_t × (평탄부 슬래브 하면
                 아래 fc_beam_h) + 안쪽 헌치 fc_haunch_w × fc_haunch_h, 그 아래 기초 버림 fc_foot_w × fc_foot_t)
        fc_length: 앞마당 길이 = 상단 끝벽 바깥면 ~ 끝단 보 바깥면 (m, 실무 2,850 + 보 300)
        fc_flat: 앞마당 평탄 길이 (m, None = 자동: 포장 윗면이 끝단 보 바깥면에서 지표에 닿게 = fc_length − top_rise × ramp_ratio)
        fc_material: 앞마당 포장 재질
        finish: 내부 마감 종류 (마감을 켤 때, 비우면 붙은 출구통로의 마감 종류 — 통로의 finish, 비우면 '통로')
        haunch_w / haunch_h: 천장 헌치 수평 / 연직 크기 (m, 0 이면 없음)
        lower_margin: 하부 이음벽 안쪽 면 ~ 에스컬레이터 트러스 하단 끝 (m)
        top_margin: 계단·에스컬레이터 상단 끝 ~ 상단 끝벽 안쪽 면 (m)
        parapet: 파라펫(개구부 측벽·끝벽·천장 끝 가로 파라펫) 윗면의 지표(GL) 위 높이 (m, 실무 GL+300). 상부 승강구를 높이면
                 top_rise 이상이어야 함
        parapet_t: 파라펫 두께 (m, None = 예전: 가로 파라펫 = 천장 끝 두께, 측벽·끝벽은 벽 두께 그대로). 주면 천장 끝 가로 파라펫
                   (천장 슬래브 끝면에서 안쪽으로 그 두께, 실무 상세 "d" 300)과 개구부 측벽·끝벽(높임 없을 때)의 지표 위 부분이 그 두께
                   (내공면 고정, 바깥면만 얇아짐)
        top_ffl: 상부 승강구 바닥 마감 두께 (m, 0 = 없음, 실무 100) — 에스컬레이터 구역 승강구 슬래브 윗면·상단 끝벽 윗면(높임)이 그만큼
                 낮아지고 그 위에 승강구 바닥 마감 부재 (마감을 꺼도 있음, 재질 top_material). 계단 구역은 계단 마감이 맡음
        canopy: 지붕 없는 개구부 위 캐노피 (철골 + 평판 유리 지붕, 모델 기본 끔·GUI 켬). 기둥(cp_post 정사각) = 개구부 측벽
                (파라펫) 두께 가운데 선, 파라펫 윗면 ~ 보 하면, 천장 끝 ~ 상단 끝벽 안쪽 면을 간격 ≤ cp_spacing 로 고르게. 보(cp_beam_w ×
                cp_beam_h) = 기둥 선 위 테두리 보(뒤 = 가로 파라펫 바깥면 ~ 앞 = 상단 끝벽 바깥면 + cp_front) + 기둥마다·앞뒤 끝 가로 보.
                보 하면 = 앞 끝에서 승강구 + cp_height, 뒤로 cp_slope 기울기로 낮아짐(배수). 유리(cp_glass_t) = 보 위, 옆은 기둥 선
                너머 cp_side
        cp_sign: 캐노피 앞 가로 보 아래 출구 사인 (폭 cp_sign_w × 높이 cp_sign_h × 두께 cp_sign_t, 바깥(+u)을 향함). 번호·목적지 =
                 exit_number / exit_dest (비우면 사인 설정 출구 안내 → 통로 순번), 이미지 = 역 안 출구 사인과 같은 그림
        landing_t: 에스컬레이터 구역 승강구 슬래브 두께 (m, 실무 200) — 트러스 위 끝 ~ 상단 끝벽, 아래는 빈 공간(바닥 = 트러스 하면 높이)
        stair_offset: 계단 첫 챌판 위치 = 하부 피트 끝 + stair_offset (m, 0 이하). None 이면 자동: 피트 끝에서 시작하되
                      계단 슬래브가 바닥 아래로 내려가면 바닥 위에 머물 때까지 하부 수평부 쪽으로 앞당김
        riser_max / tread / flight_rise_max / landing_len / stair_slab_t / stair_headroom: 계단 규칙 (계단 객체와 같은 의미)
        esc_*: 에스컬레이터 제원 (에스컬레이터 객체와 같은 의미 — 곡선 전이·스커트·데크·유리·뉴얼 상세 포함, 볼라드는 아직 없음)
        name: 비우면 EN + 일련번호
    """
    passage: str = ""
    ground_el: Optional[float] = None
    stair_width: float = 1.75
    partition_t: float = 0.2
    escalator_zone: float = 3.31
    escalator: bool = True
    escalator_side: int = 1
    stair: bool = True
    escalator_count: int = 1
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
    # 에스컬레이터 상세 형상 (정거장 에스컬레이터와 같은 의미, 리팩토링 2단계)
    esc_lower_radius: float = 1.0
    esc_upper_radius: float = 1.5
    esc_skirt_height: float = 0.12
    esc_deck_width: float = 0.12
    esc_glass_t: float = 0.012
    esc_newel_ext: float = 0.3
    esc_newel_radius: float = 0.3
    thickness_zones: list = dataclasses.field(default_factory=list)
    finish: str = ""                 # 내부 마감 종류 (마감표 이름, 비우면 붙은 출구통로의 마감 종류)
    top_rise: float = 0.0            # 상부 승강구 지표 위 높이
    ramp_width: float = 1.2          # 바깥 경사로 폭 (0 = 없음)
    ramp_ratio: float = 12.0         # 바깥 경사로 기울기 1/n
    out_riser_max: float = 0.15      # 바깥 계단 단높이 상한
    out_tread: float = 0.35          # 바깥 계단 단너비
    out_base: float = 0.15           # 바깥 경사로·계단 바닥 (지표 아래 깊이)
    open_narrow: float = 0.0         # 개구부 내공 축소 (한쪽)
    open_wall_t: Optional[float] = None   # 개구부 측벽 두께 (None = 두께 구간)
    taper_ratio: float = 0.0         # 바깥면 사선 전이 길이 / 바깥면 차 (0 = 직각)
    outdoor: str = "steps"           # 바깥 접근 형식: steps (경사로·계단) | forecourt (앞마당 접속 슬래브)
    fc_length: float = 3.15          # 앞마당 길이 (끝벽 바깥면 ~ 끝단 보 바깥면)
    fc_flat: Optional[float] = None  # 앞마당 평탄 길이 (None = 자동)
    fc_pave_t: float = 0.1           # 포장 두께
    fc_slab_t: float = 0.3           # 접속 슬래브 두께
    fc_lean_t: float = 0.14          # 슬래브 아래 버림
    fc_beam_t: float = 0.3           # 끝단 보 폭
    fc_beam_h: float = 0.535         # 끝단 보 하면 = 평탄부 슬래브 하면 아래 깊이
    fc_haunch_w: float = 0.29        # 끝단 보 안쪽 헌치 (수평 / 연직)
    fc_haunch_h: float = 0.12
    fc_foot_w: float = 0.61          # 끝단 보 아래 기초 버림 폭 / 두께
    fc_foot_t: float = 0.14
    fc_material: str = "화강석"       # 앞마당 포장 재질
    parapet_t: Optional[float] = None  # 파라펫 두께 (None = 천장 끝·벽 두께)
    top_ffl: float = 0.0             # 상부 승강구 바닥 마감 두께
    landing_t: float = 0.2           # 에스컬레이터 구역 승강구 슬래브 두께
    top_material: str = "화강석"      # 상부 승강구 바닥 마감 재질
    canopy: bool = False             # 캐노피 (철골 + 유리 지붕)
    cp_height: float = 3.0           # 앞 끝 보 하면 = 승강구 + 높이
    cp_slope: float = 0.03           # 지붕 기울기 (뒤로 낮아짐)
    cp_front: float = 0.6            # 앞 내밈 (상단 끝벽 바깥면 너머)
    cp_side: float = 0.3             # 옆 내밈 (기둥 선 너머 유리)
    cp_post: float = 0.2             # 기둥 (정사각 한 변)
    cp_spacing: float = 4.0          # 기둥 간격 상한
    cp_beam_w: float = 0.15          # 보 폭
    cp_beam_h: float = 0.3           # 보 높이
    cp_glass_t: float = 0.024        # 유리 두께
    cp_sign: bool = True             # 캐노피 앞 출구 사인
    cp_sign_w: float = 2.4
    cp_sign_h: float = 0.6
    cp_sign_t: float = 0.15
    exit_number: str = ""            # 출구 번호 (비우면 사인 설정 / 통로 순번)
    exit_dest: str = ""              # 목적지 (줄바꿈 구분, 비우면 사인 설정)
    roof_cover: float = 0.0
    lean_t: float = 0.0
    lean_ext: float = 0.155

    def thick_at(self, u: float) -> float:
        """u 자리의 벽·슬래브 두께 (두께 구간)"""
        t = self.wall_t
        for u0, th in sorted(self.thickness_zones):
            if u >= u0 - 1e-9:
                t = th
        return t

    def thick_cuts(self, lo: float, hi: float) -> list:
        """lo ~ hi 사이 두께가 바뀌는 u"""
        return sorted({u0 for u0, _ in self.thickness_zones if lo + 1e-9 < u0 < hi - 1e-9})

    @property
    def n_escalators(self) -> int:
        return max(1, int(self.escalator_count)) if self.escalator else 0

    @property
    def escalator_group_width(self) -> float:
        """에스컬레이터 구역 전체 폭 = 1대 구역 + (대수 − 1) × 트러스 외폭 (트러스끼리 붙음)"""
        return self.escalator_zone + (self.n_escalators - 1) * self.esc_truss_width if self.escalator else 0.0

    @property
    def inner_width(self) -> float:
        w = self.stair_width if self.stair else 0.0
        if self.escalator:
            w += self.escalator_group_width + (self.partition_t if self.stair else 0.0)
        return w

    def zones(self) -> dict:
        """폭 방향 구역 (t 범위, 출입구 좌표: 오르는 방향 왼쪽 +). stair / partition / escalator(에스컬레이터 구역 전체) /
        escalators(대마다 구역, 칸막이벽 쪽부터 — 계단이 없으면 −t 쪽부터)"""
        a = self.inner_width / 2.0
        if not self.escalator:
            return {"stair": (-a, a)}
        n, tw = self.n_escalators, self.esc_truss_width
        m = (self.escalator_zone - tw) / 2.0          # 벽·칸막이 쪽 여유 (1대일 때와 같음), 대 사이는 0 (트러스끼리 붙음)
        if not self.stair:                           # 에스컬레이터만
            return {"escalator": (-a, a), "escalators": [(-a + m + k * tw, -a + m + (k + 1) * tw) for k in range(n)]}
        if self.escalator_side > 0:                  # 왼쪽(+t) 에 에스컬레이터 — 칸막이 쪽부터
            b = -a + self.stair_width + self.partition_t
            return {"stair": (-a, -a + self.stair_width), "partition": (-a + self.stair_width, b),
                    "escalator": (b, a), "escalators": [(b + m + k * tw, b + m + (k + 1) * tw) for k in range(n)]}
        b = a - self.stair_width - self.partition_t
        return {"escalator": (-a, b), "escalators": [(b - m - (k + 1) * tw, b - m - k * tw) for k in range(n)],
                "partition": (b, a - self.stair_width), "stair": (a - self.stair_width, a)}

    def stair_spec(self) -> StairSpec:
        t0, t1 = self.zones()["stair"]
        return StairSpec(lower_floor=1, s_start=0.0, direction=1, t_center=(t0 + t1) / 2.0, width=t1 - t0,
                         riser_max=self.riser_max, tread=self.tread, flight_rise_max=self.flight_rise_max,
                         landing_len=self.landing_len, waist_t=self.stair_slab_t, headroom=self.stair_headroom)

    def escalator_spec(self, k: int = 0) -> EscalatorSpec:
        """k 번째 에스컬레이터 (칸막이벽 쪽부터, 모두 같은 제원) — t 범위 = 그 대의 트러스 자리"""
        t0, t1 = self.zones()["escalators"][k]
        return EscalatorSpec(lower_floor=1, s_wp=0.0, direction=1, t_center=(t0 + t1) / 2.0,
                             angle_deg=self.esc_angle_deg, step_width=self.esc_step_width,
                             truss_width=self.esc_truss_width, truss_depth=self.esc_truss_depth,
                             lower_ext=self.esc_lower_ext, upper_ext=self.esc_upper_ext,
                             lower_flat_steps=self.esc_lower_flat_steps, upper_flat_steps=self.esc_upper_flat_steps,
                             step_depth=self.esc_step_depth, handrail_height=self.esc_handrail_height,
                             headroom=self.esc_headroom, lower_radius=self.esc_lower_radius,
                             upper_radius=self.esc_upper_radius, skirt_height=self.esc_skirt_height,
                             deck_width=self.esc_deck_width, glass_t=self.esc_glass_t, newel_ext=self.esc_newel_ext,
                             newel_radius=self.esc_newel_radius, bollard_count=0)


def resolve_entrance_names(specs: list) -> list[str]:
    names = [sp.name.strip() or f"EN{i}" for i, sp in enumerate(specs, start=1)]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ValueError(f"출입구 이름이 중복됩니다: {', '.join(dup)}")
    return names
