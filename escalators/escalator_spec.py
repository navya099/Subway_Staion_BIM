import dataclasses
import math

# 형상 상수 (입력 항목으로 두지 않는 세부 치수, m)
STEP_PLATE_T = 0.10        # 스텝 판 두께: 스텝 층의 하면 = 스텝 코 선 − (단높이 + 판 두께)
STEP_RISER_T = 0.03        # 스텝 챌판 판 두께 (개별 스텝)
SKIRT_GAP = 0.005          # 스텝 가장자리 ~ 스커트 패널 (상세 2단계)
SKIRT_T = 0.01             # 스커트 패널 두께
DECK_T = 0.03              # 안쪽·바깥 데크 두께
LANDING_PLATE_T = 0.03     # 승강구 바닥판·콤플레이트·바깥 덮개판 두께 (윗면 = 바닥 마감면, 상세 4단계)
COMB_L = 0.25              # 콤플레이트 길이 (진행방향)
CLAD_T = 0.02              # 트러스 외장 패널 두께 (옆·아래, 트러스 외폭·높이 안)
BALUSTRADE_GAP = 0.02      # 스텝 가장자리 ~ 난간 패널 안쪽 면
BALUSTRADE_T = 0.03        # 난간 패널 두께
HANDRAIL_W = 0.08          # 핸드레일 단면 폭
HANDRAIL_H = 0.08          # 핸드레일 단면 높이


@dataclasses.dataclass
class EscalatorSpec:
    """에스컬레이터 1대의 입력 제원 (정거장 로컬 좌표). lower_floor 층에서 바로 위층까지 오른다.

    기준점은 하부 WP(경사선 = 스텝 코 선이 아래층 바닥면과 만나는 점). 상부 WP 는 층간 표고차와 경사각으로 자동 계산한다.
    스텝 코 선: 하부 WP 앞은 아래층 바닥면, WP 사이는 경사선, 상부 WP 뒤는 위층 바닥면.
    트러스(외형)는 스텝 코 선 아래로 연직 truss_depth 만큼의 띠이며, 하부 WP 에서 lower_ext 앞 ~ 상부 WP 에서 upper_ext 뒤까지.
    트러스가 바닥 아래로 들어가는 하부 피트는 아래층 바닥 슬래브(또는 승강장 슬래브)에, 위층 슬래브를 지나가는 구간과
    머리 높이가 부족한 구간은 위층 슬래브에 오프닝이 자동으로 뚫린다.

    Attributes:
        lower_floor: 시작 층 (1 = 최하층). 1 ~ 층수-1
        s_wp: 하부 WP 의 진행방향 위치 s (m, 내공 시점 기준)
        direction: 오르는 방향. +1 = 종점 방향(+s), -1 = 시점 방향(−s)
        t_center: 에스컬레이터 중심의 선형 직교 방향 위치 (m, 왼쪽 +)
        angle_deg: 경사각 (°)
        step_width: 스텝 폭 (m, S1000 형 = 1.0)
        truss_width: 트러스 외폭 (m) = 평면 폭
        truss_depth: 트러스 연직 높이 (m) = 피트 깊이
        lower_ext / upper_ext: 하부 WP → 트러스 하단 끝 / 상부 WP → 트러스 상단 끝 수평 거리 (m)
        lower_flat_steps / upper_flat_steps: 하부 / 상부 평탄 스텝 수
        step_depth: 스텝 깊이 (m, 수평). 단높이 = step_depth · tan(경사각)
        handrail_height: 핸드레일 높이 (m, 스텝 코 선 기준 연직)
        headroom: 스텝 코 선 위 최소 유효 높이 (m) (마감을 켜면 아래층 천장판 하면이 슬래브 하면보다 낮을 때 천장판 하면 기준)
        side_clear: 위층 자동 오프닝 옆 여유 (m, 트러스 외폭 양쪽에 더함, 기본 0)
        lower_radius / upper_radius: 하부(오목)·상부(볼록) 곡선 전이 반경 (m, 일반값 1.0 / 1.5, 0 = 꺾임)
        skirt_height: 스텝 코 선 위 스커트 높이 = 데크 하면 (m, 상세 2단계 — 그 위 데크 두께, 그 위 유리)
        deck_width: 안쪽 데크 폭 (스커트 안쪽 면 ~ 유리, m), glass_t: 난간 유리 두께 (m).
        newel_ext: 난간·핸드레일이 스텝 구간 양끝 너머로 나가는 수평 길이 (m, 상세 3단계), newel_radius: 끝 뉴얼 반원 바깥 반경 (m)
        단면(스텝 가장자리 → 바깥): 틈 SKIRT_GAP · 스커트 SKIRT_T · (데크 폭 안에서) · 유리 · 바깥 데크(트러스 바깥까지)
        name: 비우면 ES + 일련번호
    """
    lower_floor: int = 1
    s_wp: float = 0.0
    direction: int = 1
    t_center: float = 0.0
    t_ref: str = "center"        # t 기준점 (계단과 같음, 폭 = 트러스 외폭) — 검증 전에 중심으로 풀림
    angle_deg: float = 30.0
    step_width: float = 1.0
    truss_width: float = 1.6
    truss_depth: float = 1.15
    lower_ext: float = 2.4
    upper_ext: float = 2.8
    lower_flat_steps: int = 2
    upper_flat_steps: int = 3
    step_depth: float = 0.4
    handrail_height: float = 1.0
    headroom: float = 2.3
    name: str = ""
    side_clear: float = 0.0
    lower_radius: float = 1.0
    upper_radius: float = 1.5
    skirt_height: float = 0.12
    deck_width: float = 0.12
    glass_t: float = 0.012
    newel_ext: float = 0.3
    newel_radius: float = 0.3

    @property
    def tan(self) -> float:
        return math.tan(math.radians(self.angle_deg))

    @property
    def riser(self) -> float:
        """스텝 단높이 (경사부)"""
        return self.step_depth * self.tan

    @property
    def t_lo(self) -> float:
        """트러스(평면) t 범위 하한"""
        return self.t_center - self.truss_width / 2.0

    @property
    def t_hi(self) -> float:
        return self.t_center + self.truss_width / 2.0

    def balustrade_t(self, side: int) -> tuple[float, float]:
        """난간 패널 t 범위. side = +1 (t 큰 쪽, 진행방향 왼쪽) / -1"""
        a = self.step_width / 2.0 + BALUSTRADE_GAP
        lo, hi = a, a + BALUSTRADE_T
        return (self.t_center + lo, self.t_center + hi) if side > 0 else (self.t_center - hi, self.t_center - lo)

    def _span(self, side: int, a: float, b: float) -> tuple:
        """중심에서 a ~ b 떨어진 띠 (side 쪽)"""
        return (self.t_center + a, self.t_center + b) if side > 0 else (self.t_center - b, self.t_center - a)

    def detail_t(self, side: int) -> dict:
        """상세 단면 t 범위 (스텝 가장자리 → 바깥): SKIRT, INNER_DECK(스커트 안쪽 면 ~ 유리), GLASS, OUTER_DECK(유리 ~ 트러스 바깥)"""
        w = self.step_width / 2.0
        k0 = w + SKIRT_GAP
        g0 = k0 + self.deck_width
        g1 = g0 + self.glass_t
        return {"SKIRT": self._span(side, k0, k0 + SKIRT_T), "INNER_DECK": self._span(side, k0, g0),
                "GLASS": self._span(side, g0, g1), "OUTER_DECK": self._span(side, g1, self.truss_width / 2.0)}

    def handrail_t(self, side: int) -> tuple[float, float]:
        """핸드레일 t 범위 (난간 패널 중심에 놓임)"""
        c = sum(self.balustrade_t(side)) / 2.0
        return c - HANDRAIL_W / 2.0, c + HANDRAIL_W / 2.0


def resolve_escalator_names(specs: list) -> list[str]:
    """에스컬레이터별 이름 (지정한 이름 우선, 없으면 ES + 일련번호). 중복 이름은 오류"""
    names = [sp.name.strip() or f"ES{i}" for i, sp in enumerate(specs, start=1)]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ValueError(f"에스컬레이터 이름이 중복됩니다: {', '.join(dup)}")
    return names
