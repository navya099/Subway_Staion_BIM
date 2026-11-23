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
    slide: tuple = None          # 문짝: ((ds, dt) 정거장 단위 방향, 최대 이동) — 애니메이션 (열림 비율 × 최대 이동)
    stop: int = None             # 승강장 문짝의 층

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

    def box(code, kind, s0, s1, t0, t1, z0, z1, piece=0, slide=None, stop=None):
        strip = Strip(s0, s1, base + z0, base + z0, base + z1, PM.curve_factor(cfg, s0, s1, (t0 + t1) / 2.0))
        parts.append(ElevatorPartLayout(code, kind, (t0, t1), StripShape(strips=[strip], width=t1 - t0), piece,
                                        slide=slide, stop=stop))

    zc = car_z(spec, rel)
    if not rel[k0] - _EPS <= zc <= rel[k1] + _EPS:
        raise ValueError(f"엘리베이터 {name}: 카 위치(정지층 + 오프셋 {spec.car_offset:g}m)가 운행 범위"
                         f"({st.level_name(k0)} ~ {st.level_name(k1)} 정지 바닥) 밖입니다")

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

    car_parts(spec, zc, spec.door_open, box)
    inner_face = lambda axis, sign: (s1 if sign > 0 else s0) if axis == "s" else (t1 if sign > 0 else t0)
    landing_doors(spec, rel, st, inner_face, box)
    if spec.fixtures:
        from finishes.finish_clear import room_finish_at

        def rc_face(axis, sign, n):                                # 승강로 바깥면 + 그 층 벽 마감 표면 거리
            out = ((S1 if sign > 0 else S0) if axis == "s" else (T1 if sign > 0 else T0))
            p = (out + sign * 0.3, tc) if axis == "s" else (sc, out + sign * 0.3)
            ft = room_finish_at(cfg, n, *p)
            return out + sign * (ft.face if ft is not None and ft.wall_t > 0 else 0.0)
        add_fixtures(spec, st, rel, box, rc_face, spec.door_w / 2.0 + 0.25, 0.12, spec.door_h + 0.18)
    if spec.ladder:
        pit_ladder(spec, rel, pit_top, inner_face, box, _car_bottom(spec, zc))
    opening = None
    if opened:
        opening = OpeningSpec(kind=OpeningKind.ELEVATOR, s_start=S0, length=S1 - S0, t_center=tc, width=T1 - T0,
                              slabs=sorted(opened), name=f"{name}_SHAFT")
    hole = (f"{name}_SHAFT", S0, S1, T0, T1) if plat_open else None
    return ElevatorLayout(name=name, spec=spec, on_platform=on_plat, stops={n: base + r for n, r in rel.items()},
                          stop_rel=rel, parts=parts, opening=opening, platform_hole=hole, door_openings=doors,
                          z_range=(base + lo, base + hi))


def car_z(spec, rel) -> float:
    """카 바닥 상면 (본체 FL 기준) = 카 정지층 정지 바닥 + car_offset (애니메이션: 정지층 사이 임의 높이)"""
    return rel[spec.stop_car] + spec.car_offset


def door_open_at(spec, floor: int) -> float:
    """층 floor 승강장 문의 열림 비율 (카가 그 층에 정확히 서 있을 때만 door_open, 아니면 닫힘)"""
    return spec.door_open if (floor == spec.stop_car and abs(spec.car_offset) < 1e-9) else 0.0


def car_parts(spec, z: float, open_ratio: float, box):
    """카 묶음 (애니메이션: z = 카 바닥 상면(FL 기준), open_ratio = 카 문 열림 0~1 만 바꿔 다시 부르면 됨).
    바닥·천장 = 카 외곽, 벽 4면 (문 면은 문 자리를 비움, car_glass 면 문 없는 면 = 유리 CAR_GLASS),
    카 문 = 문 면마다 가운데 열림 두 짝 CAR_DOOR_{면}_N / _P (카 벽 바깥면 밖 평면, 접선 방향으로 open × 반폭만큼 밀림).
    box(code, kind, s0, s1, t0, t1, z0, z1, piece=0, slide=None)"""
    sc, tc = spec.car_center()
    door_faces = spec.door_faces_all()
    cw, dw = spec.car_wall_t, spec.door_w / 2.0
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
    # 열림 거리 상한 = 카 외곽 반폭 − 문 반폭 (문짝이 카 모서리를 넘으면 직각 면(90도형) 문짝과 부딪침)
    half_along = (ht if spec.door_axis == "s" else hs) + cw
    travel = max(0.0, min(dw, half_along - dw))
    o = min(max(open_ratio, 0.0), 1.0) * travel
    for code, axis, sign, (a0, a1, b0, b1) in car_walls:
        tan0, tan1 = (b0, b1) if axis == "s" else (a0, a1)
        mid = tc if axis == "s" else sc
        hole = []
        door = (axis, sign) in door_faces
        if door:
            hole = [(mid - dw, mid + dw, z, z + spec.door_h)]
            outer = co[1] if (axis, sign) == ("s", 1) else co[0] if axis == "s" else co[3] if sign > 0 else co[2]
            n0, n1 = (outer, outer + sign * cw) if sign > 0 else (outer + sign * cw, outer)
            for tag, u0, u1, d in (("N", mid - dw - o, mid - o, -1), ("P", mid + o, mid + dw + o, 1)):
                slide = ((0.0, d) if axis == "s" else (d, 0.0), travel)    # (정거장 (ds, dt) 단위 방향, 최대 이동)
                if axis == "s":
                    box(f"CAR_DOOR_{code}_{tag}", K.CAR_DOOR, n0, n1, u0, u1, z, z + spec.door_h, 0, slide)
                else:
                    box(f"CAR_DOOR_{code}_{tag}", K.CAR_DOOR, u0, u1, n0, n1, z, z + spec.door_h, 0, slide)
        kind = K.CAR_GLASS if (spec.car_glass and not door) else K.CAR_WALL
        for k, (u0, u1, z0, z1) in enumerate(decompose.subtract_rects((tan0, tan1, z, z + spec.car_height), hole), start=1):
            if axis == "s":
                box(f"CAR_WALL_{code}", kind, a0, a1, u0, u1, z0, z1, k)
            else:
                box(f"CAR_WALL_{code}", kind, u0, u1, b0, b1, z0, z1, k)


PORTAL_T = 0.05              # 깊은 문틀(car_gap)의 잼·상부·바닥판 두께


def landing_doors(spec, rel, st, face_n, box, floors=None, sill_in=0.0):
    """정지층마다 문 면의 승강장 문 두 짝 LDOOR_{면}_{층}_N / _P (승강로 안쪽 평면 — face_n(axis, sign) = 문 평면 바깥쪽 경계,
    그 안쪽으로 door_gap 띄우고 두께 door_t, 열림 = door_open_at).
    car_gap 을 주면 문짝 안쪽 면 = 카 문 바깥면 + car_gap (더 안쪽일 때만) 이고, 그 사이를 깊은 문틀 LPORT_{면}_{층}
    (양 잼·상부·바닥판)으로 메움. sill_in = 바닥판이 시작하는 깊이 (face_n 에서 안쪽, 투시형 금속 패널 띠 두께만큼)"""
    sc, tc = spec.s_center, spec.t_center
    dw = spec.door_w / 2.0
    cs, ct = spec.car_center()
    for n in (floors if floors is not None else range(spec.lower_floor, spec.upper_floor + 1)):
        for axis, sign in sorted(spec.doors_at(n)):
            travel = dw
            if spec.car_gap is not None and len({a for a, _ in spec.door_faces_all()}) > 1:     # 90도형: 카 모서리에서 직각 면 문짝과
                travel = max(0.0, min(dw, spec.car_half("t" if axis == "s" else "s") - spec.car_wall_t - dw))   # 부딪치지 않게 카 외곽까지
            o = door_open_at(spec, n) * travel
            code = ("P" if sign > 0 else "N") + axis.upper()
            base = face_n(axis, sign)
            f = base - sign * spec.door_gap
            mid = tc if axis == "s" else sc
            if spec.car_gap is not None:
                deep = (cs if axis == "s" else ct) + sign * (spec.car_half(axis) + spec.car_gap + spec.door_t)
                if sign * (f - deep) > _EPS:
                    f = deep
                    c, w = f"LPORT_{code}_{st.level_name(n)}", PORTAL_T
                    sill0 = base - sign * sill_in

                    def put(k, a, b, u0, u1, z0, z1, axis=axis, c=c):
                        if abs(a - b) < _EPS:
                            return
                        a, b = sorted((a, b))
                        if axis == "s":
                            box(c, K.DOOR_FRAME, a, b, u0, u1, z0, z1, k)
                        else:
                            box(c, K.DOOR_FRAME, u0, u1, a, b, z0, z1, k)
                    zf = rel[n]
                    put(1, base, f, mid - dw - w, mid - dw, zf, zf + spec.door_h)
                    put(2, base, f, mid + dw, mid + dw + w, zf, zf + spec.door_h)
                    put(3, base, f, mid - dw - w, mid + dw + w, zf + spec.door_h, zf + spec.door_h + w)
                    put(4, sill0, f - sign * spec.door_t, mid - dw - w, mid + dw + w, zf - w, zf)
            n0, n1 = sorted((f, f - sign * spec.door_t))
            for tag, u0, u1, d in (("N", mid - dw - o, mid - o, -1), ("P", mid + o, mid + dw + o, 1)):
                slide = ((0.0, d) if axis == "s" else (d, 0.0), travel)
                c = f"LDOOR_{code}_{st.level_name(n)}_{tag}"
                if axis == "s":
                    box(c, K.LANDING_DOOR, n0, n1, u0, u1, rel[n], rel[n] + spec.door_h, 0, slide, n)
                else:
                    box(c, K.LANDING_DOOR, u0, u1, n0, n1, rel[n], rel[n] + spec.door_h, 0, slide, n)


def add_fixtures(spec, st, rel, box, face_n, panel_off, panel_w, ind_z):
    """정지층 문마다 호출 버튼 판·버튼·층 표시기 (face_n(axis, sign, 층) = 붙는 면의 법선 좌표)"""
    from elevators.hall_fixture import hall_fixtures, right_sign
    for n in range(spec.lower_floor, spec.upper_floor + 1):
        for axis, sign in sorted(spec.doors_at(n)):
            mid = spec.t_center if axis == "s" else spec.s_center
            for code, kind, (n0, n1), (v0, v1), (z0, z1) in hall_fixtures(
                    axis, sign, face_n(axis, sign, n), mid, rel[n], st.level_name(n), n, panel_at=mid + right_sign(axis, sign) * panel_off,
                    panel_w=panel_w, ind_z=ind_z, up=n < spec.upper_floor, down=n > spec.lower_floor):
                if axis == "s":
                    box(code, kind, n0, n1, v0, v1, z0, z1, 0, None, n)
                else:
                    box(code, kind, v0, v1, n0, n1, z0, z1, 0, None, n)


def pit_ladder(spec, rel, pit_top, face_n, box, car_box=None):
    """피트 점검 사다리 (실무 표준도 069 상세 6): 최하 정지층 대표 문 반대 면 가운데, 그 면(face_n)에서 안쪽 0.15 에 레일 두 개
    (□0.03, 간격 0.45) + 가로대(0.3 간격), 피트 바닥 ~ 최하 정지 바닥"""
    axis, sign = spec.door_axis, -spec.door_sign
    c = face_n(axis, sign) - sign * 0.15
    n0, n1 = c - 0.015, c + 0.015
    mid = spec.t_center if axis == "s" else spec.s_center
    z0, z1 = pit_top, rel[spec.lower_floor] - (PORTAL_T if spec.car_gap is not None else 0.0)     # 깊은 문틀 바닥판 아래까지
    if car_box is not None and z1 > car_box[0]:
        z1 = car_box[0]                                             # 카가 최하층에 서 있으면 카 바닥 아래까지
    if z1 - z0 < 0.3:
        return

    def put(code, u0, u1, za, zb, piece=0):
        if axis == "s":
            box(code, K.LADDER, n0, n1, u0, u1, za, zb, piece)
        else:
            box(code, K.LADDER, u0, u1, n0, n1, za, zb, piece)
    put("LADDER", mid - 0.24, mid - 0.21, z0, z1, 1)
    put("LADDER", mid + 0.21, mid + 0.24, z0, z1, 2)
    k, z = 3, z0 + 0.235
    while z + 0.03 <= z1 - 1e-9:
        put("LADDER", mid - 0.21, mid + 0.21, z, z + 0.03, k)
        k, z = k + 1, z + 0.3


def _car_bottom(spec, zc):
    """사다리 위 끝 상한: 카 평면이 사다리 평면을 덮으면 카 바닥판 하면 (아니면 None)"""
    axis = spec.door_axis
    half = (spec.car_depth / 2.0 + spec.car_wall_t) - spec.door_sign * (spec.car_shift()[0] + spec.car_shift()[1])   # 사다리 쪽
    inner = (spec.inner_s if axis == "s" else spec.inner_t) / 2.0
    return (zc - spec.car_floor_t,) if half > inner - 0.18 else None


def _layout_glass(cfg, spec, name, base, rel, on_plat, ranges, opened, plat_open, lo, pit_top, box, parts):
    """투시형 승강로 (실무 표준도 068·069): RC 피트 + 모서리 강관 기둥 + 가로재 + 층마다 유리 + 천장 위 금속 패널 띠 + 카.
    면 코드 PS/NS (±s 면), PT/NT (±t 면). ±s 면 유리·패널이 t 방향 외곽 전체, ±t 면은 그 사이 (모서리 겹침 없음)"""
    st, pl = cfg.station, cfg.platform
    sc, tc = spec.s_center, spec.t_center
    k0, k1 = spec.lower_floor, spec.upper_floor
    S0, S1, T0, T1 = spec.outer_rect()
    top = ranges[k1][0]                                            # 위 슬래브 하면 (기둥·패널 위 끝)
    w, gt, pt = spec.wall_t, spec.glass_t, spec.panel_t
    dw, oh = spec.door_w / 2.0 + spec.door_frame_w, spec.door_open_h()    # 유리 문 자리 반폭 (문 + 문틀)
    fw, sp_, sd = spec.door_frame_w, spec.spider, spec.spider_d

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
            if (axis, sign) in on:                                  # 승강장 문틀 (유리 평면, 양옆 잼 + 상부)
                put(f"DFRAME_{tag}_{lvl}", K.DOOR_FRAME, axis, nrm, (mid - dw, mid - dw + fw), rel[n], rel[n] + oh, 1)
                put(f"DFRAME_{tag}_{lvl}", K.DOOR_FRAME, axis, nrm, (mid + dw - fw, mid + dw), rel[n], rel[n] + oh, 2)
                if oh - spec.door_h > _EPS:
                    put(f"DFRAME_{tag}_{lvl}", K.DOOR_FRAME, axis, nrm, (mid - dw + fw, mid + dw - fw),
                        rel[n] + spec.door_h, rel[n] + oh, 3)
            # DPG 스파이더: 유리 줄눈 교차점 (유리 안쪽 면에서 깊이 spider_d), 문틀 자리 제외, 모서리는 직각 면과 겹치지 않게 안쪽으로
            outer = (S1 if sign > 0 else S0) if axis == "s" else (T1 if sign > 0 else T0)
            g_in = outer - sign * gt
            sn = tuple(sorted((g_in, g_in - sign * sd)))
            e0, e1 = (T0 + gt, T1 - gt) if axis == "s" else (S0 + gt + sd, S1 - gt - sd)
            us = sorted({c[0] for c in cols} | {c[1] for c in cols})
            if (axis, sign) in on:
                us = [u for u in us if abs(u - (mid - dw)) > _EPS and abs(u - (mid + dw)) > _EPS]
            zs = [spec.glass_z0] + [j[1] for j in joints]
            piece = 0
            for u in us:
                ua, ub = ((e0, e0 + sp_) if abs(u - tan[0]) < _EPS else (e1 - sp_, e1) if abs(u - tan[1]) < _EPS
                          else (u - sp_ / 2.0, u + sp_ / 2.0))
                for i, z in enumerate(zs):
                    za, zb = (z, z + sp_) if i == 0 else (z - sp_, z) if i == len(zs) - 1 else (z - sp_ / 2.0, z + sp_ / 2.0)
                    piece += 1
                    put(f"SPIDER_{tag}_{lvl}", K.SPIDER, axis, sn, (ua, ub), rel[n] + za, rel[n] + zb, piece)
            if z_pan - zg1 > _EPS:                                  # 천장 위 금속 패널 띠
                pn, ptan = face_box(axis, sign, pt)
                if n < k1 and (axis, sign) in spec.doors_at(n + 1):    # 위층 문 자리: 위층 바닥까지 (문틀·문짝 아래)
                    put(f"PANEL_{tag}_{lvl}", K.PANEL, axis, pn, ptan, zg1, rel[n + 1], 1)
                    for k, (u0, u1) in enumerate(((ptan[0], mid - dw), (mid + dw, ptan[1])), start=2):
                        if u1 - u0 > _EPS:
                            put(f"PANEL_{tag}_{lvl}", K.PANEL, axis, pn, (u0, u1), rel[n + 1], z_pan, k)
                else:
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

    zc = car_z(spec, rel)
    car_parts(spec, zc, spec.door_open, box)
    glass_in = lambda axis, sign: ((S1 if sign > 0 else S0) if axis == "s" else (T1 if sign > 0 else T0)) - sign * gt
    landing_doors(spec, rel, st, glass_in, box, sill_in=max(0.0, pt - gt))
    if spec.fixtures:                                              # 문틀(유리 평면) 앞: 오른쪽 잼에 호출 판, 상부에 표시기
        glass_out = lambda axis, sign, n: (S1 if sign > 0 else S0) if axis == "s" else (T1 if sign > 0 else T0)
        add_fixtures(spec, st, rel, box, glass_out, spec.door_w / 2.0 + fw / 2.0, min(0.08, 0.8 * fw),
                     max((spec.door_h + oh) / 2.0, spec.door_h + 0.1))
    if spec.ladder:
        outer_face = lambda axis, sign: (S1 if sign > 0 else S0) if axis == "s" else (T1 if sign > 0 else T0)
        pit_ladder(spec, rel, pit_top, outer_face, box, _car_bottom(spec, zc))
    opening = None
    if opened:
        opening = OpeningSpec(kind=OpeningKind.ELEVATOR, s_start=S0, length=S1 - S0, t_center=tc, width=T1 - T0,
                              slabs=sorted(opened), name=f"{name}_SHAFT")
    hole = (f"{name}_SHAFT", S0, S1, T0, T1) if plat_open else None
    return ElevatorLayout(name=name, spec=spec, on_platform=on_plat, stops={n: base + v for n, v in rel.items()},
                          stop_rel=rel, parts=parts, opening=opening, platform_hole=hole, door_openings=doors,
                          z_range=(base + lo, base + top))
