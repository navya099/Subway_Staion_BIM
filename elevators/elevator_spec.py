import dataclasses
from typing import Optional

DOOR_SIDES = ("+s", "-s", "+t", "-t")      # 승강장(문) 쪽: 종점 방향 / 시점 방향 / 왼쪽 / 오른쪽
SHAFTS = ("rc", "glass")                   # 승강로 형식: RC 벽 (정거장 밖·확폭 구간) / 투시형 강관 + 유리 (정거장 내부, 실무 표준도)


@dataclasses.dataclass
class ElevatorSpec:
    """엘리베이터 1대의 입력 제원 (정거장 내부: lower_floor ~ upper_floor 사이의 모든 층에 정지).

    - 승강로(콘크리트) = 내공 inner_s × inner_t 둘레의 벽 + 피트 바닥 슬래브 + 오버헤드 위 천장 슬래브.
      벽은 피트 바닥(최하 정지층 바닥 − pit_depth) ~ 최상 정지층 바닥 + overhead. 정지층마다 문 쪽 벽에 문 크기 출입구.
    - 승강로가 지나는 본체 슬래브(·승강장 슬래브)에는 승강로 외곽 크기 오프닝이 자동으로 뚫리고,
      피트·천장 슬래브가 그 슬래브 두께 안에서 끝나면 슬래브 면까지 채운다 (본체 바닥 아래로 내린 피트 포함).
    - 최하층에서 평면이 승강장 슬래브 안이면 그 층 정지 바닥 = 승강장 상면 (걸치면 오류).
    - 카 = 바닥판·벽·천장·문(닫힌 상태). car_floor 층에 정지한 위치 (카 바닥 상면 = 그 층 정지 바닥).

    Attributes:
        lower_floor / upper_floor: 최하·최상 정지층 (1 = 최하층, lower < upper)
        car_floor: 카가 서 있는 층 (None 이면 최하 정지층)
        s_center / t_center: 승강로 내공 중심 (정거장 로컬 s, t — t 는 왼쪽 +)
        inner_s / inner_t: 승강로 내공 (s 방향 / t 방향, m)
        wall_t: 승강로 벽 두께
        door_side: 문(승강장) 쪽 '+s' | '-s' | '+t' | '-t',  through: 관통형(반대쪽에도 문)
        door_w / door_h: 출입구(승강로·카 문) 폭 / 높이
        pit_depth / pit_slab_t: 피트 깊이(최하 정지 바닥 ~ 피트 바닥 상면) / 피트 바닥 슬래브 두께
        overhead / top_slab_t: 오버헤드(최상 정지 바닥 ~ 승강로 천장 하면) / 승강로 천장 슬래브 두께
        car_width / car_depth / car_height: 카 내부 폭(문 면과 나란) / 깊이 / 높이
        car_floor_t / car_wall_t / car_roof_t: 카 바닥판 / 벽·문 / 천장 두께
        name: 비우면 EV + 일련번호
        shaft: 승강로 형식 'rc' (RC 벽 + 피트·천장 슬래브, 모델 기본) | 'glass' (투시형 — 실무 표준도 068·069: 토목은 슬래브
               오프닝·RC 피트만, 건축은 강관 골조 + 유리 + 천장 위 금속 패널). glass 일 때:
               - 유리 바깥면 = 내공에서 glass_offset 바깥 (승강로 외곽 = 슬래브 오프닝), 유리 두께 glass_t, 층마다 정지 바닥 +
                 glass_z0 부터 glass_rows(아래부터 줄 높이) 합까지, 세로 줄눈 = 문 면은 문 양옆, 아니면 glass_max_w 이하로 고르게
               - 모서리 강관 기둥 col_d (중심 = 유리 바깥면에서 col_inset 안쪽), 피트 바닥 ~ 최상 정지층 위 슬래브 하면
               - 가로재 강관 girt_d: 기둥 선을 따라 유리 가로 줄눈·윗면 높이 (문 자리 끊김)
               - 금속 패널 띠(panel_t): 유리 윗면 ~ 다음 정지층 유리 아래 (슬래브 두께·천장 속), 최상층은 위 슬래브 하면까지
               - RC 피트: 피트 바닥 슬래브 + 둘레 벽(외곽 바깥 wall_t, 피트 바닥 ~ 그 위 첫 슬래브 하면). 오버헤드는 위 슬래브 하면 안
        car_offset / door_open: 애니메이션 대비 — 카 바닥 = 카 정지층 정지 바닥 + car_offset (정지층 범위 안),
                     door_open = 카 문·(카가 정지층에 딱 서 있으면) 그 층 승강장 문 열림 비율 0~1 (가운데 열림 두 짝, 반폭만큼 밀림)
        car_glass: 투시형 카 (문 없는 카 벽 = 유리), door_frame_w: 투시형 승강장 문틀 폭, door_t / door_gap: 승강장 문짝 두께 /
                   승강로 안쪽 면에서 띄움, spider / spider_d: DPG 스파이더 크기·깊이, ladder: 피트 점검 사다리
        door_floors: 층별 문 방향 (최하 정지층부터, 항목마다 '+t' 또는 '+t/-s' 처럼 여러 면, None = 모든 층 door_side(+관통형))
                     — 실무 90도형 (층마다 다른 면)
    """
    lower_floor: int = 1
    upper_floor: int = 2
    car_floor: Optional[int] = None
    s_center: float = 0.0
    t_center: float = 0.0
    inner_s: float = 2.4
    inner_t: float = 2.4
    wall_t: float = 0.3
    door_side: str = "+t"
    through: bool = False
    door_w: float = 0.9
    door_h: float = 2.1
    pit_depth: float = 1.5
    pit_slab_t: float = 0.6
    overhead: float = 4.0
    top_slab_t: float = 0.3
    car_width: float = 1.6
    car_depth: float = 1.5
    car_height: float = 2.3
    car_floor_t: float = 0.1
    car_wall_t: float = 0.05
    car_roof_t: float = 0.1
    name: str = ""
    shaft: str = "rc"
    door_floors: Optional[list] = None
    glass_offset: float = 0.42       # 내공 → 유리 바깥면 (실무 3,840 = 3,000 + 420 × 2)
    glass_t: float = 0.012           # T12 강화유리
    glass_z0: float = 0.07           # 유리 아래 끝 (정지 바닥 위)
    glass_rows: tuple = (1.3, 1.2, 0.5)   # 유리 가로 줄 높이 (아래부터)
    glass_max_w: float = 2.0         # 문 없는 면 유리 한 장 최대 폭
    col_d: float = 0.1398            # 모서리 기둥 Ø139.8
    col_inset: float = 0.25          # 기둥 중심 ← 유리 바깥면
    girt_d: float = 0.0891           # 가로재 Ø89.1
    panel_t: float = 0.05            # 금속 패널 띠 (□50 각관 + T1.2 갈바륨)
    # 2단계: 애니메이션 대비 (카 이동·문 열림) + 문·문틀·부속
    car_offset: float = 0.0          # 카 바닥 = 카 정지층 정지 바닥 + 오프셋 (m, 정지층 사이 이동)
    door_open: float = 0.0           # 문 열림 비율 0~1 (카 문 + 카가 서 있는 층 승강장 문)
    car_glass: bool = False          # 투시형 카 (문 없는 카 벽 = 유리)
    door_frame_w: float = 0.1        # 투시형 승강장 문틀 폭 (유리 문 자리 = 문 폭 + 2 × 문틀)
    door_t: float = 0.03             # 승강장 문짝 두께
    door_gap: float = 0.04           # 승강장 문짝 ← 승강로 안쪽 면 (유리 안쪽 면 / RC 벽 안쪽 면)
    spider: float = 0.1              # DPG 스파이더 철물 크기 (유리 줄눈 교차점, 유리 안쪽)
    spider_d: float = 0.03           # 스파이더 깊이 (< door_gap)
    ladder: bool = True              # 피트 점검 사다리

    def doors_at(self, floor: int) -> set:
        """그 층 문 면 {('s'|'t', ±1)}"""
        if self.door_floors:
            k = floor - self.lower_floor
            item = self.door_floors[k] if 0 <= k < len(self.door_floors) else ""
            return {(d[1], 1 if d[0] == "+" else -1) for d in str(item).split("/") if d}
        out = {(self.door_axis, self.door_sign)}
        return out | ({(self.door_axis, -self.door_sign)} if self.through else set())

    def door_faces_all(self) -> set:
        """정지층 전체의 문 면 (카 문)"""
        return set().union(*(self.doors_at(n) for n in range(self.lower_floor, self.upper_floor + 1)))

    @property
    def glass_height(self) -> float:
        return float(sum(self.glass_rows))

    def door_open_h(self) -> float:
        """투시형 유리의 문 자리 높이 = 문 높이 이상인 첫 가로 줄눈 (없으면 문 높이)"""
        z = self.glass_z0
        for h in self.glass_rows:
            z += h
            if z >= self.door_h - 1e-9:
                return z
        return self.door_h

    @property
    def stop_car(self) -> int:
        return self.lower_floor if self.car_floor is None else self.car_floor

    @property
    def main_side(self) -> str:
        """대표 문 면 (카 방향 기준): 층별 문 방향이 있으면 최하 정지층의 첫 면, 아니면 door_side"""
        if self.door_floors:
            first = [d for d in str(self.door_floors[0]).split("/") if d]
            if first:
                return first[0]
        return self.door_side

    @property
    def door_axis(self) -> str:
        """대표 문 면의 법선 축 's' | 't' (카 폭 = 이 면과 나란)"""
        return self.main_side[1]

    @property
    def door_sign(self) -> int:
        return 1 if self.main_side[0] == "+" else -1

    def inner_rect(self) -> tuple:
        """승강로 내공 (s0, s1, t0, t1)"""
        return (self.s_center - self.inner_s / 2.0, self.s_center + self.inner_s / 2.0,
                self.t_center - self.inner_t / 2.0, self.t_center + self.inner_t / 2.0)

    def outer_rect(self) -> tuple:
        """승강로 외곽 (s0, s1, t0, t1) — RC = 벽 바깥면, 투시형 = 유리 바깥면 (슬래브 오프닝)"""
        s0, s1, t0, t1 = self.inner_rect()
        w = self.glass_offset if self.shaft == "glass" else self.wall_t
        return (s0 - w, s1 + w, t0 - w, t1 + w)


def resolve_elevator_names(specs: list) -> list[str]:
    """엘리베이터별 이름 (지정한 이름 우선, 없으면 EV + 일련번호). 중복 이름은 오류"""
    names = [sp.name.strip() or f"EV{i}" for i, sp in enumerate(specs, start=1)]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ValueError(f"엘리베이터 이름이 중복됩니다: {', '.join(dup)}")
    return names
