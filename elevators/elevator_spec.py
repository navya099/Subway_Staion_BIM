import dataclasses
from typing import Optional

DOOR_SIDES = ("+s", "-s", "+t", "-t")      # 승강장(문) 쪽: 종점 방향 / 시점 방향 / 왼쪽 / 오른쪽


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

    @property
    def stop_car(self) -> int:
        return self.lower_floor if self.car_floor is None else self.car_floor

    @property
    def door_axis(self) -> str:
        """문이 있는 면의 법선 축 's' | 't'"""
        return self.door_side[1]

    @property
    def door_sign(self) -> int:
        return 1 if self.door_side[0] == "+" else -1

    def inner_rect(self) -> tuple:
        """승강로 내공 (s0, s1, t0, t1)"""
        return (self.s_center - self.inner_s / 2.0, self.s_center + self.inner_s / 2.0,
                self.t_center - self.inner_t / 2.0, self.t_center + self.inner_t / 2.0)

    def outer_rect(self) -> tuple:
        """승강로 외곽 (s0, s1, t0, t1)"""
        s0, s1, t0, t1 = self.inner_rect()
        w = self.wall_t
        return (s0 - w, s1 + w, t0 - w, t1 + w)


def resolve_elevator_names(specs: list) -> list[str]:
    """엘리베이터별 이름 (지정한 이름 우선, 없으면 EV + 일련번호). 중복 이름은 오류"""
    names = [sp.name.strip() or f"EV{i}" for i, sp in enumerate(specs, start=1)]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ValueError(f"엘리베이터 이름이 중복됩니다: {', '.join(dup)}")
    return names
