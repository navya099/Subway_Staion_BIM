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
import math
from dataclasses import dataclass
from typing import Optional

from config.widening import platform_ranges
from elevators.elevator_spec import ElevatorSpec
from elevators.elevator_type import ElevatorPartKind as K
from helper import prism_member as PM
from helper.strip_member import Strip, StripShape
from openings import decompose
from openings.opening_kind import OpeningKind
from openings.opening_spec import OpeningSpec
from helper.box_piece import BoxPiece
from helper.vertical_prism import VerticalPrism, circle_points

_EPS = 1e-6


@dataclass
class ElevatorPartLayout:
    code: str                    # 예: WALL_PS (승강로 +s 벽), CAR_WALL_PT, CAR_DOOR_PS
    kind: K
    t_range: tuple
    shape: StripShape            # 띠 1개 (상자) — solid 가 있으면 None
    piece: int = 0               # 같은 부재(code)의 조각 번호
    solid: object = None         # 상자가 아닌 조각 (세계 좌표 VerticalPrism 기둥 / BoxPiece 가로재), s_range·t_range 는 외접
    s_box: tuple = None          # solid 의 정거장 로컬 외접 s 범위

    @property
    def s_range(self) -> tuple:
        if self.solid is not None:
            return self.s_box
        st = self.shape.strips[0]
        return st.s0, st.s1

    @property
    def z_range(self) -> tuple:
        if self.solid is not None:
            return self.solid.z_range
        st = self.shape.strips[0]
        return st.zb0, st.zt

    @property
    def volume(self) -> float:
        return self.solid.volume if self.solid is not None else self.shape.volume


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
    ranges = slab_ranges(st)
    if spec.shaft == "glass":                                      # 투시형: 최상 정지층 위 슬래브 하면까지 (천장 슬래브 없음)
        wall_top = ranges[k1][0]
        if rel[k1] + spec.overhead > wall_top + _EPS:
            raise ValueError(f"엘리베이터 {name}: 오버헤드({spec.overhead:g}m)가 {st.level_name(k1)} 정지 바닥 ~ 위 슬래브 하면"
                             f"({wall_top - rel[k1]:.3f}m)보다 큽니다")
        lo, hi = pit_top - spec.pit_slab_t, wall_top
    else:
        wall_top = rel[k1] + spec.overhead
        lo, hi = pit_top - spec.pit_slab_t, wall_top + spec.top_slab_t
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

    if spec.shaft == "glass":
        return _layout_glass(cfg, spec, name, base, rel, on_plat, ranges, opened, plat_open, lo, pit_top, box, parts)
    s0, s1, t0, t1 = spec.inner_rect()
    S0, S1, T0, T1 = spec.outer_rect()
    box("PIT", K.PIT_SLAB, S0, S1, T0, T1, lo, pit_top)
    box("TOP", K.TOP_SLAB, S0, S1, T0, T1, wall_top, hi)

    # 승강로 벽: (코드, 법선 축, 부호, 벽 평면 사각형 (s0, s1, t0, t1), 접선 축 구간)
    walls = [("WALL_PS", "s", 1, (s1, S1, T0, T1)), ("WALL_NS", "s", -1, (S0, s0, T0, T1)),
             ("WALL_PT", "t", 1, (s0, s1, t1, T1)), ("WALL_NT", "t", -1, (s0, s1, T0, t0))]
    doors = []
    for code, axis, sign, (a0, a1, b0, b1) in walls:
        tan0, tan1 = (b0, b1) if axis == "s" else (a0, a1)
        mid = tc if axis == "s" else sc
        holes = []
        for n in range(k0, k1 + 1):
            if (axis, sign) in spec.doors_at(n):
                h = (mid - spec.door_w / 2.0, mid + spec.door_w / 2.0, rel[n], rel[n] + spec.door_h)
                holes.append(h)
                rect = (a0, a1, h[0], h[1]) if axis == "s" else (h[0], h[1], b0, b1)
                doors.append((f"{name}_{code}_{st.level_name(n)}", code, n, rect, base + h[2], base + h[3]))
        for k, (u0, u1, z0, z1) in enumerate(decompose.subtract_rects((tan0, tan1, pit_top, wall_top), holes), start=1):
            if axis == "s":
                box(code, K.HOIST_WALL, a0, a1, u0, u1, z0, z1, k)
            else:
                box(code, K.HOIST_WALL, u0, u1, b0, b1, z0, z1, k)

    _car(spec, rel, box)
    opening = None
    if opened:
        opening = OpeningSpec(kind=OpeningKind.ELEVATOR, s_start=S0, length=S1 - S0, t_center=tc, width=T1 - T0,
                              slabs=sorted(opened), name=f"{name}_SHAFT")
    hole = (f"{name}_SHAFT", S0, S1, T0, T1) if plat_open else None
    return ElevatorLayout(name=name, spec=spec, on_platform=on_plat, stops={n: base + r for n, r in rel.items()},
                          stop_rel=rel, parts=parts, opening=opening, platform_hole=hole, door_openings=doors,
                          z_range=(base + lo, base + hi))


def _car(spec, rel, box):
    """카 (car_floor 층에 정지): 바닥·천장 = 카 외곽, 벽 4면, 문 면(정지층 전체의 문 면)은 문 자리를 비우고 닫힌 문"""
    sc, tc = spec.s_center, spec.t_center
    door_faces = spec.door_faces_all()
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


def _layout_glass(cfg, spec, name, base, rel, on_plat, ranges, opened, plat_open, lo, pit_top, box, parts):
    """투시형 승강로 (실무 표준도 068·069): RC 피트 + 모서리 강관 기둥 + 가로재 + 층마다 유리 + 천장 위 금속 패널 띠 + 카.
    면 코드 PS/NS (±s 면), PT/NT (±t 면). ±s 면 유리·패널이 t 방향 외곽 전체, ±t 면은 그 사이 (모서리 겹침 없음)"""
    st, pl = cfg.station, cfg.platform
    sc, tc = spec.s_center, spec.t_center
    k0, k1 = spec.lower_floor, spec.upper_floor
    S0, S1, T0, T1 = spec.outer_rect()
    top = ranges[k1][0]                                            # 위 슬래브 하면 (기둥·패널 위 끝)
    w, gt, pt = spec.wall_t, spec.glass_t, spec.panel_t
    dw, oh = spec.door_w / 2.0, spec.door_open_h()

    # ---- RC 피트: 바닥 슬래브(외곽 = 슬래브 오프닝) + 둘레 벽(외곽 바깥 wall_t, 피트 바닥 ~ 그 위 첫 슬래브(·승강장 슬래브) 하면)
    box("PIT", K.PIT_SLAB, S0, S1, T0, T1, lo, pit_top)
    bottoms = [a for a, b in ranges.values() if lo + _EPS < a < rel[k0] + _EPS]
    if on_plat:
        bottoms.append(pl.plat_height)
    zw = min(bottoms) if bottoms else rel[k0]
    if zw - lo > _EPS:
        box("PIT_WALL_PS", K.PIT_WALL, S1, S1 + w, T0 - w, T1 + w, lo, zw)
        box("PIT_WALL_NS", K.PIT_WALL, S0 - w, S0, T0 - w, T1 + w, lo, zw)
        box("PIT_WALL_PT", K.PIT_WALL, S0, S1, T1, T1 + w, lo, zw)
        box("PIT_WALL_NT", K.PIT_WALL, S0, S1, T0 - w, T0, lo, zw)

    def face_box(axis, sign, d):
        """면 판 (두께 d, 바깥면 = 외곽): (법선 축 구간, 접선 구간). ±s 면이 t 외곽 전체, ±t 면은 그 사이"""
        if axis == "s":
            return ((S1 - d, S1) if sign > 0 else (S0, S0 + d)), (T0, T1)
        return ((T1 - d, T1) if sign > 0 else (T0, T0 + d)), (S0 + d, S1 - d)
    faces = [("PS", "s", 1), ("NS", "s", -1), ("PT", "t", 1), ("NT", "t", -1)]

    def put(code, kind, axis, nrm, tan, z0, z1, piece):
        if axis == "s":
            box(code, kind, nrm[0], nrm[1], tan[0], tan[1], z0, z1, piece)
        else:
            box(code, kind, tan[0], tan[1], nrm[0], nrm[1], z0, z1, piece)

    doors, joints = [], []
    acc = spec.glass_z0
    for h in spec.glass_rows:
        joints.append((acc, acc + h))
        acc += h
    for n in range(k0, k1 + 1):
        lvl = st.level_name(n)
        zg1 = rel[n] + spec.glass_z0 + spec.glass_height
        if zg1 > ranges[n][0] + _EPS:
            raise ValueError(f"엘리베이터 {name}: {lvl} 유리 윗면(FL+{zg1:.3f})이 위 슬래브 하면(FL+{ranges[n][0]:.3f})보다 높습니다 "
                             "(유리 줄 높이를 줄이세요)")
        z_pan = (rel[n + 1] + spec.glass_z0) if n < k1 else top
        on = spec.doors_at(n)
        for tag, axis, sign in faces:
            nrm, tan = face_box(axis, sign, gt)
            mid = tc if axis == "s" else sc
            if (axis, sign) in on:
                cols = [(tan[0], mid - dw, False), (mid - dw, mid + dw, True), (mid + dw, tan[1], False)]
                rect = (nrm[0], nrm[1], mid - dw, mid + dw) if axis == "s" else (mid - dw, mid + dw, nrm[0], nrm[1])
                doors.append((f"{name}_GLASS_{tag}_{lvl}", f"GLASS_{tag}_{lvl}", n, rect, base + rel[n], base + rel[n] + oh))
            else:
                k = max(1, math.ceil((tan[1] - tan[0]) / spec.glass_max_w - 1e-9))
                cols = [(tan[0] + (tan[1] - tan[0]) * i / k, tan[0] + (tan[1] - tan[0]) * (i + 1) / k, False) for i in range(k)]
            piece = 0
            for u0, u1, is_door in cols:
                for z0, z1 in joints:
                    if is_door and z1 <= oh + _EPS:
                        continue                                    # 문 자리 (그 위 줄만 유리)
                    piece += 1
                    put(f"GLASS_{tag}_{lvl}", K.GLASS, axis, nrm, (u0, u1), rel[n] + z0, rel[n] + z1, piece)
            if z_pan - zg1 > _EPS:                                  # 천장 위 금속 패널 띠
                pn, ptan = face_box(axis, sign, pt)
                put(f"PANEL_{tag}_{lvl}", K.PANEL, axis, pn, ptan, zg1, z_pan, 0)

    # ---- 모서리 강관 기둥 (피트 바닥 ~ 위 슬래브 하면) · 가로재 (기둥 선, 유리 가로 줄눈·윗면 높이, 문 자리 끊김)
    r, ci = spec.col_d / 2.0, spec.col_inset
    cs, ct = (S0 + ci, S1 - ci), (T0 + ci, T1 - ci)
    for s, sa in zip(cs, "NP"):
        for t, ta in zip(ct, "NP"):
            x, y = cfg.to_world(s, t)
            parts.append(ElevatorPartLayout(f"COL_{sa}{ta}", K.COLUMN, (t - r, t + r), None, 0,
                                            VerticalPrism(circle_points(x, y, r), base + pit_top, base + top), (s - r, s + r)))
    ox, oy = cfg.to_world(sc, tc)
    ps_, pt_ = cfg.to_world(sc + 1.0, tc), cfg.to_world(sc, tc + 1.0)
    ls_, lt_ = math.hypot(ps_[0] - ox, ps_[1] - oy), math.hypot(pt_[0] - ox, pt_[1] - oy)
    dir_s = ((ps_[0] - ox) / ls_, (ps_[1] - oy) / ls_)                # 단위 벡터 (곡선 선형에서 s 1m 의 현은 1 이 아님)
    dir_t = ((pt_[0] - ox) / lt_, (pt_[1] - oy) / lt_)
    rg = spec.girt_d / 2.0
    for n in range(k0, k1 + 1):
        lvl = st.level_name(n)
        on = spec.doors_at(n)
        for tag, axis, sign in faces:
            if axis == "s":                                         # ±s 면 가로재: 축 = t 방향, s = 기둥 선
                line, lo_a, hi_a, mid, a_off = cs[1 if sign > 0 else 0], ct[0] + r, ct[1] - r, tc, tc
                ux, uy = dir_t
                v_c = -(line - sc)                                  # t 축의 왼쪽 = −s
            else:                                                   # ±t 면 가로재: 축 = s 방향, t = 기둥 선
                line, lo_a, hi_a, mid, a_off = ct[1 if sign > 0 else 0], cs[0] + r, cs[1] - r, sc, sc
                ux, uy = dir_s
                v_c = line - tc
            piece = 0
            for _, z1 in joints:
                spans = [(lo_a, hi_a)]
                if (axis, sign) in on and z1 < oh - _EPS:
                    spans = [(lo_a, mid - dw), (mid + dw, hi_a)]
                for a0, a1 in spans:
                    if a1 - a0 <= _EPS:
                        continue
                    piece += 1
                    sect = [(v_c + rg * math.cos(2 * math.pi * j / 12), rg * math.sin(2 * math.pi * j / 12)) for j in range(12)]
                    bp = BoxPiece(ox=ox, oy=oy, ux=ux, uy=uy, a0=a0 - a_off, a1=a1 - a_off, sect=sect, z0=base + rel[n] + z1)
                    sbox = (line - rg, line + rg) if axis == "s" else (a0, a1)
                    trng = (a0, a1) if axis == "s" else (line - rg, line + rg)
                    parts.append(ElevatorPartLayout(f"GIRT_{tag}_{lvl}", K.GIRT, trng, None, piece, bp, sbox))

    _car(spec, rel, box)
    opening = None
    if opened:
        opening = OpeningSpec(kind=OpeningKind.ELEVATOR, s_start=S0, length=S1 - S0, t_center=tc, width=T1 - T0,
                              slabs=sorted(opened), name=f"{name}_SHAFT")
    hole = (f"{name}_SHAFT", S0, S1, T0, T1) if plat_open else None
    return ElevatorLayout(name=name, spec=spec, on_platform=on_plat, stops={n: base + v for n, v in rel.items()},
                          stop_rel=rel, parts=parts, opening=opening, platform_hole=hole, door_openings=doors,
                          z_range=(base + lo, base + top))
