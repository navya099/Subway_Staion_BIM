"""엘리베이터 배치 계산 (승강로·피트·천장 슬래브, 정지층 출입구, 카, 본체·승강장 슬래브 자동 오프닝).

모든 부재는 정거장 로컬 (s 구간) × (t 구간) × (수평 상·하면) 상자 = 띠 부재 1개 (helper.strip_member.Strip).
표고는 절대 표고, 기준은 승강로 중심 s 의 선형 표고 (승강로는 연직·수평이라 구배를 따르지 않음).
- 정지 바닥: 각 층 FL, 최하층에서 승강로가 승강장 슬래브 안이면 승강장 상면
- 승강로 벽: 피트 바닥 상면(최하 정지 바닥 − pit_depth) ~ 최상 정지 바닥 + overhead. 문 쪽 벽(관통형이면 반대쪽도)은
  정지층마다 문 크기 출입구를 뺀 조각으로 나눔 (decompose.subtract_rects)
- 승강로가 지나는 본체 슬래브 · 승강장 슬래브는 승강로 외곽 크기로 뚫리고, 피트 바닥 슬래브 하면 / 승강로 천장 슬래브 상면이
  어떤 슬래브 두께 안에 걸리면 그 슬래브 면까지 늘려 채움 (빈 틈이 생기지 않게)
- 카: 내공 중심, car_floor 층 정지 바닥에 카 바닥 상면. 바닥판·천장 = 카 외곽, 벽 4면, 문 쪽 벽은 문 자리를 비우고 닫힌 문 패널
"""
from config.widening import platform_ranges
from dataclasses import dataclass
from typing import Optional

from elevators.elevator_spec import ElevatorSpec
from elevators.elevator_type import ElevatorPartKind as K
from helper import prism_member as PM
from helper.strip_member import Strip, StripShape
from openings import decompose
from openings.opening_kind import OpeningKind
from openings.opening_spec import OpeningSpec

_EPS = 1e-6


@dataclass
class ElevatorPartLayout:
    code: str                    # 예: WALL_PS (승강로 +s 벽), CAR_WALL_PT, CAR_DOOR_PS
    kind: K
    t_range: tuple
    shape: StripShape            # 띠 1개 (상자)
    piece: int = 0               # 같은 부재(code)의 조각 번호

    @property
    def s_range(self) -> tuple:
        st = self.shape.strips[0]
        return st.s0, st.s1

    @property
    def z_range(self) -> tuple:
        st = self.shape.strips[0]
        return st.zb0, st.zt


@dataclass
class ElevatorLayout:
    name: str
    spec: ElevatorSpec
    on_platform: bool
    stops: dict                  # 층 번호 → 정지 바닥 절대 표고
    stop_rel: dict               # 층 번호 → 정지 바닥 (본체 FL 기준)
    parts: list                  # ElevatorPartLayout
    opening: Optional[OpeningSpec]          # 본체 슬래브 승강로 오프닝 (뚫을 슬래브가 없으면 None)
    platform_hole: Optional[tuple]          # (이름, s0, s1, t0, t1) 승강장 슬래브 구멍
    door_openings: list          # [(이름, 벽 code, 층, (s0, s1, t0, t1), z0, z1)] 승강로 출입구 (절대 표고)
    z_range: tuple               # 승강로 전체 (피트 슬래브 하면, 천장 슬래브 상면) 절대 표고

    @property
    def lower_floor(self) -> int:
        return self.spec.lower_floor

    @property
    def upper_floor(self) -> int:
        return self.spec.upper_floor

    def outer_rect(self) -> tuple:
        return self.spec.outer_rect()


def slab_ranges(st) -> dict:
    """본체 슬래브 번호 → (하면, 상면) (FL 기준). 0 = 바닥, i = i/i+1층 사이, 층수 = 천장"""
    out = {0: (-st.floor_t, 0.0), st.floors: (st.height - st.roof_t, st.height)}
    for i in range(1, st.floors):
        top = st.floor_level(i + 1)
        out[i] = (top - st.mid_t, top)
    return out


def _on_platform(cfg, spec, name) -> bool:
    pl = cfg.platform
    if spec.lower_floor != 1 or not pl.exists:
        return False
    _, _, t0, t1 = spec.outer_rect()
    for p0, p1 in platform_ranges(cfg):
        if p0 - _EPS <= t0 and t1 <= p1 + _EPS:
            return True
        if min(p1, t1) - max(p0, t0) > _EPS:
            raise ValueError(f"엘리베이터 {name}: 승강로 t {t0:g} ~ {t1:g} 이(가) 승강장 슬래브(t {p0:g} ~ {p1:g})에 걸쳐 있습니다. "
                             "승강장 안에 완전히 넣거나 승강장 밖으로 옮기세요")
    return False


def layout_elevator(cfg, spec: ElevatorSpec, name: str) -> ElevatorLayout:
    """엘리베이터 1대의 배치 (spec 의 기본 범위 검사는 elevator_check.check_elevator_spec 이 먼저 한다)"""
    st, pl = cfg.station, cfg.platform
    sc, tc = spec.s_center, spec.t_center
    base = cfg.lv(sc) - st.offset                                  # FL(z=0) 의 절대 표고
    on_plat = _on_platform(cfg, spec, name)
    k0, k1 = spec.lower_floor, spec.upper_floor
    rel = {n: (pl.top_level if (n == 1 and on_plat) else st.floor_level(n)) for n in range(k0, k1 + 1)}

    # ---- 높이 (FL 기준) 와 본체·승강장 슬래브 관통
    pit_top = rel[k0] - spec.pit_depth
    wall_top = rel[k1] + spec.overhead
    lo, hi = pit_top - spec.pit_slab_t, wall_top + spec.top_slab_t
    ranges = slab_ranges(st)
    for n in range(k0, k1 + 1):                                    # 출입구가 그 층 위 슬래브(번호 n)에 닿지 않을 것
        if rel[n] + spec.door_h > ranges[n][0] + _EPS:
            raise ValueError(f"엘리베이터 {name}: 문 높이({spec.door_h:g}m)가 {st.level_name(n)} 정지 바닥 위 내공 높이"
                             f"({ranges[n][0] - rel[n]:.3f}m)보다 큽니다")
    roof_bottom = ranges[st.floors][0]
    if hi > roof_bottom + _EPS:
        raise ValueError(f"엘리베이터 {name}: 승강로 천장 슬래브 상면(FL+{hi:.3f})이 본체 천장 슬래브 하면(FL+{roof_bottom:.3f})보다 "
                         "높습니다 (오버헤드·천장 슬래브 두께를 줄이세요)")
    opened = [n for n, (a, b) in ranges.items() if min(b, hi) - max(a, lo) > _EPS]
    plat_open = on_plat and min(pl.top_level, hi) - max(pl.plat_height, lo) > _EPS
    # 피트 슬래브 하면 / 천장 슬래브 상면이 뚫린 슬래브 두께 안에서 끝나면 그 슬래브 면까지 채움
    lo = min([lo] + [a for n, (a, b) in ranges.items() if n in opened and a < lo < b])
    hi = max([hi] + [b for n, (a, b) in ranges.items() if n in opened and a < hi < b])
    if k0 > 1 and lo < st.floor_level(k0 - 1) + _EPS:
        raise ValueError(f"엘리베이터 {name}: 피트 바닥(FL+{lo:.3f})이 아래층({st.level_name(k0 - 1)}) 바닥에 닿습니다 "
                         "(피트 깊이·피트 슬래브 두께를 줄이세요)")

    # ---- 부재 (상자 = 띠 1개)
    parts = []

    def box(code, kind, s0, s1, t0, t1, z0, z1, piece=0):
        strip = Strip(s0, s1, base + z0, base + z0, base + z1, PM.curve_factor(cfg, s0, s1, (t0 + t1) / 2.0))
        parts.append(ElevatorPartLayout(code, kind, (t0, t1), StripShape(strips=[strip], width=t1 - t0), piece))

    s0, s1, t0, t1 = spec.inner_rect()
    S0, S1, T0, T1 = spec.outer_rect()
    box("PIT", K.PIT_SLAB, S0, S1, T0, T1, lo, pit_top)
    box("TOP", K.TOP_SLAB, S0, S1, T0, T1, wall_top, hi)

    # 승강로 벽: (코드, 법선 축, 부호, 벽 평면 사각형 (s0, s1, t0, t1), 접선 축 구간)
    walls = [("WALL_PS", "s", 1, (s1, S1, T0, T1)), ("WALL_NS", "s", -1, (S0, s0, T0, T1)),
             ("WALL_PT", "t", 1, (s0, s1, t1, T1)), ("WALL_NT", "t", -1, (s0, s1, T0, t0))]
    door_faces = {(spec.door_axis, spec.door_sign)} | ({(spec.door_axis, -spec.door_sign)} if spec.through else set())
    doors = []
    for code, axis, sign, (a0, a1, b0, b1) in walls:
        tan0, tan1 = (b0, b1) if axis == "s" else (a0, a1)
        mid = tc if axis == "s" else sc
        holes = []
        if (axis, sign) in door_faces:
            for n in range(k0, k1 + 1):
                h = (mid - spec.door_w / 2.0, mid + spec.door_w / 2.0, rel[n], rel[n] + spec.door_h)
                holes.append(h)
                rect = (a0, a1, h[0], h[1]) if axis == "s" else (h[0], h[1], b0, b1)
                doors.append((f"{name}_{code}_{st.level_name(n)}", code, n, rect, base + h[2], base + h[3]))
        for k, (u0, u1, z0, z1) in enumerate(decompose.subtract_rects((tan0, tan1, pit_top, wall_top), holes), start=1):
            if axis == "s":
                box(code, K.HOIST_WALL, a0, a1, u0, u1, z0, z1, k)
            else:
                box(code, K.HOIST_WALL, u0, u1, b0, b1, z0, z1, k)

    # ---- 카 (car_floor 층에 정지)
    z = rel[spec.stop_car]
    cw = spec.car_wall_t
    if spec.door_axis == "s":
        hs, ht = spec.car_depth / 2.0, spec.car_width / 2.0
    else:
        hs, ht = spec.car_width / 2.0, spec.car_depth / 2.0
    ci = (sc - hs, sc + hs, tc - ht, tc + ht)                       # 카 내부
    co = (sc - hs - cw, sc + hs + cw, tc - ht - cw, tc + ht + cw)   # 카 외곽
    box("CAR_FLOOR", K.CAR_FLOOR, *co, z - spec.car_floor_t, z)
    box("CAR_ROOF", K.CAR_ROOF, *co, z + spec.car_height, z + spec.car_height + spec.car_roof_t)
    car_walls = [("PS", "s", 1, (ci[1], co[1], co[2], co[3])), ("NS", "s", -1, (co[0], ci[0], co[2], co[3])),
                 ("PT", "t", 1, (ci[0], ci[1], ci[3], co[3])), ("NT", "t", -1, (ci[0], ci[1], co[2], ci[2]))]
    for code, axis, sign, (a0, a1, b0, b1) in car_walls:
        tan0, tan1 = (b0, b1) if axis == "s" else (a0, a1)
        mid = tc if axis == "s" else sc
        hole = []
        if (axis, sign) in door_faces:
            d = (mid - spec.door_w / 2.0, mid + spec.door_w / 2.0, z, z + spec.door_h)
            hole = [d]
            if axis == "s":
                box(f"CAR_DOOR_{code}", K.CAR_DOOR, a0, a1, d[0], d[1], d[2], d[3])
            else:
                box(f"CAR_DOOR_{code}", K.CAR_DOOR, d[0], d[1], b0, b1, d[2], d[3])
        for k, (u0, u1, z0, z1) in enumerate(decompose.subtract_rects((tan0, tan1, z, z + spec.car_height), hole), start=1):
            if axis == "s":
                box(f"CAR_WALL_{code}", K.CAR_WALL, a0, a1, u0, u1, z0, z1, k)
            else:
                box(f"CAR_WALL_{code}", K.CAR_WALL, u0, u1, b0, b1, z0, z1, k)

    opening = None
    if opened:
        opening = OpeningSpec(kind=OpeningKind.ELEVATOR, s_start=S0, length=S1 - S0, t_center=tc, width=T1 - T0,
                              slabs=sorted(opened), name=f"{name}_SHAFT")
    hole = (f"{name}_SHAFT", S0, S1, T0, T1) if plat_open else None
    return ElevatorLayout(name=name, spec=spec, on_platform=on_plat, stops={n: base + r for n, r in rel.items()},
                          stop_rel=rel, parts=parts, opening=opening, platform_hole=hole, door_openings=doors,
                          z_range=(base + lo, base + hi))
