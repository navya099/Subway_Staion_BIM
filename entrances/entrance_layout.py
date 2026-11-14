"""출입구 배치 계산 (출구통로 끝에 이어지는 경사 박스 + 계단 + 에스컬레이터).

출입구 좌표 (u, t): 원점 = 통로 마지막 꼭짓점(이음면 중심), u = 통로 마지막 구간 방향(지상으로 오르는 방향), t = 왼쪽 +.
세계 평면에서 곧은 좌표계라 모든 부재를 띠(helper.strip_member.Strip: s = u)로 만들고, 표고는 절대 표고.

종단 규약 (1단계, 실무 도면 기준 단순화):
- 하부: 이음면(u=0) ~ 이음벽(두께 T) ~ 에스컬레이터 트러스 하단 끝(lower_margin) ~ 하부 WP. 하부 바닥 = 통로 끝 바닥 표고 Zp
- 에스컬레이터: 하부 WP(표고 Zp) 에서 경사각으로 올라 상부 WP 에서 지표 G 에 닿음
- 바닥 슬래브: 에스컬레이터 구역은 트러스 하면(양 끝 피트), 상부 트러스 끝 뒤는 지표까지 채움.
  계단 구역은 하부 피트가 끝나는 점(트러스 하면이 Zp 를 지나는 점)까지 Zp, 그 뒤 트러스 하면을 따르고 상부는 피트 높이 유지.
  하면은 바닥 상면선(피트 포함)을 직각 방향으로 두께 T 만큼 내린 선 → 피트 옆·끝은 하면까지 꽉 찬 콘크리트
- 계단: 별도 계단 슬래브(허리 두께) 위, 첫 챌판 = 하부 피트 끝 + stair_offset, 상부 착지 후 같은 높이로 상단 끝벽까지 이어짐.
  칸막이벽은 계단 구역 바닥에서 계단 슬래브 하면까지
- 천장 슬래브 하면 = max(통로 천장 높이 Zp + Hp, 스텝 코 선 + c) — c 는 에스컬레이터 머리 높이와 천장 아래 모든 계단 디딤판·계단참의
  머리 높이를 만족하는 최소값. 천장 상면이 지표 G 에 닿는 점(u_re)에서 끝나고 그 뒤는 지붕 없는 개구부
- 측벽: 바닥 상면 ~ 천장 하면 (개구부는 지표 + 파라펫), 상단 끝벽: 바닥 상면 ~ 지표 + 파라펫, 이음벽: 통로 내공 바깥 부분만
"""
import math
from dataclasses import dataclass, field
from types import SimpleNamespace

from escalators.escalator_layout import escalator_part_strips
from helper.box_piece import BoxPiece
from helper.strip_member import Strip
from stairs.stair_layout import plan_risers, stair_part_strips

TOL = 1e-9


@dataclass
class EntranceFrame:
    """출입구 좌표 (u, t) → 세계. strip_member 가 쓰는 cfg 인터페이스(to_world, sample_s, align.is_straight)를 흉내 낸다"""
    px: float
    py: float
    ux: float
    uy: float
    align: object = field(default_factory=lambda: SimpleNamespace(is_straight=True))

    def to_world(self, u: float, t: float) -> tuple[float, float]:
        return self.px + u * self.ux - t * self.uy, self.py + u * self.uy + t * self.ux

    @staticmethod
    def sample_s(a: float, b: float, step: float = 5.0) -> list[float]:
        return [a, b]


@dataclass
class EntrancePartLayout:
    code: str                 # FLOOR_S, FLOOR_E, ROOF, WALL_L, WALL_R, END_WALL_S, END_WALL_E, JOINT_WALL_L/R, PARTITION
    kind: str                 # FLOOR / ROOF / WALL
    t_range: tuple
    strips: list


@dataclass
class EntranceLayout:
    name: str
    spec: object              # EntranceSpec
    passage: str
    frame: EntranceFrame
    z_floor: float            # 통로 끝 바닥 표고 (하부 착지 높이)
    ground: float             # 지표 EL
    u: dict                   # 주요 위치 (wp_lo, wp_hi, truss_lo, truss_hi, cross, stair0, top, roof_end, ...)
    roof_clear: float         # 천장 하면 − 스텝 코 선 (연직)
    box_parts: list           # EntrancePartLayout
    haunches: list            # BoxPiece
    stair: object             # SimpleNamespace(parts, n_risers, riser, flight_risers, run)
    escalator: object         # SimpleNamespace(parts, run, rise) 또는 None


class PL:
    """구간별 직선 함수 z(u). segs = [(u0, u1, z0, z1), ...] (u 오름차순, 경계에서 값이 뛰어도 됨)"""

    def __init__(self, segs):
        self.segs = [s for s in segs if s[1] - s[0] > TOL]

    def at(self, u: float, side: int = 1) -> float:
        """u 의 값. 경계에서 side=+1 이면 오른쪽 구간, -1 이면 왼쪽 구간 값"""
        for u0, u1, z0, z1 in (self.segs if side > 0 else reversed(self.segs)):
            if (u0 - TOL <= u < u1 - TOL) if side > 0 else (u0 + TOL < u <= u1 + TOL):
                return z0 + (z1 - z0) * (u - u0) / (u1 - u0)
        u0, u1, z0, z1 = self.segs[0] if u <= self.segs[0][0] else self.segs[-1]
        return z0 + (z1 - z0) * (u - u0) / (u1 - u0)

    @property
    def breaks(self) -> list:
        return sorted({x for s in self.segs for x in s[:2]})

    def offset(self, d: float) -> "PL":
        """직각 방향 평행 이동 (d > 0 위, < 0 아래). 이어진 구간의 꺾임점은 두 평행선의 교점, 값이 뛰는 경계는 그대로 뜀"""
        lines = []
        for u0, u1, z0, z1 in self.segs:
            m = (z1 - z0) / (u1 - u0)
            lines.append([u0, u1, m, z0 + d * math.sqrt(1.0 + m * m) - m * u0])   # z = m·u + q
        for i in range(len(lines) - 1):
            a, b = lines[i], lines[i + 1]
            continuous = abs(self.segs[i][3] - self.segs[i + 1][2]) < 1e-9 and abs(a[1] - b[0]) < TOL
            if continuous and abs(a[2] - b[2]) > 1e-12:
                x = (b[3] - a[3]) / (a[2] - b[2])
                x = min(max(x, a[0] + 1e-6), b[1] - 1e-6)
                a[1] = b[0] = x
        return PL([(u0, u1, m * u0 + q, m * u1 + q) for u0, u1, m, q in lines])


def strips_between(bottom: PL, top: PL, u_lo: float, u_hi: float, extra_breaks=()) -> list:
    """u_lo ~ u_hi 에서 하면 bottom, 상면 top 사이 띠 (두 함수의 모든 꺾임점·값 뜀에서 나눔, 높이 0 이하는 버림)"""
    cuts = sorted({u_lo, u_hi, *(x for x in bottom.breaks + top.breaks + list(extra_breaks) if u_lo + TOL < x < u_hi - TOL)})
    out = []
    for a, b in zip(cuts, cuts[1:]):
        if b - a <= 1e-9:
            continue
        zb0, zb1 = bottom.at(a, 1), bottom.at(b, -1)
        zt0, zt1 = top.at(a, 1), top.at(b, -1)
        if zt0 - zb0 > 1e-9 or zt1 - zb1 > 1e-9:
            if zt0 < zb0 - 1e-9 or zt1 < zb1 - 1e-9:             # 한쪽만 양수: 교차점에서 잘라 양수 쪽만
                x = a + (b - a) * (zb0 - zt0) / ((zt1 - zt0) - (zb1 - zb0))
                if zt0 < zb0:
                    a, zb0, zt0 = x, bottom.at(x, 1), top.at(x, 1)
                else:
                    b, zb1, zt1 = x, bottom.at(x, -1), top.at(x, -1)
            out.append(Strip(a, b, zb0, zb1, zt0, zt1=zt1))
    return out


def _const(u0, u1, z):
    return (u0, u1, z, z)


def layout_entrance(cfg, spec, name: str, passage_layouts: list) -> EntranceLayout:
    pl = next((p for p in passage_layouts if p.name == spec.passage), None)
    if pl is None:
        raise ValueError(f"출입구 {name}: 이어 붙일 출구통로 '{spec.passage}' 가 없습니다")
    va, vb = pl.vertices[-2], pl.vertices[-1]
    L = math.hypot(vb.x - va.x, vb.y - va.y)
    frame = EntranceFrame(vb.x, vb.y, (vb.x - va.x) / L, (vb.y - va.y) / L)
    zp, G = vb.z, spec.ground_el
    hp, a_p = pl.spec.inner_height, pl.spec.half_in
    T = spec.wall_t
    W = spec.inner_width
    a, b = W / 2.0, W / 2.0 + T
    if W < 2 * a_p - 1e-6:
        raise ValueError(f"출입구 {name}: 내공 폭({W:g}m)이 통로 내공 폭({2 * a_p:g}m)보다 좁습니다")
    if G - zp < 2.0:
        raise ValueError(f"출입구 {name}: 지표 EL({G:g})이 통로 끝 바닥({zp:.3f})보다 충분히 높지 않습니다")
    if zp + hp + T >= G - 1e-6:
        raise ValueError(f"출입구 {name}: 토피가 부족합니다 (통로 끝 천장 상면 {zp + hp + T:.3f} ≥ 지표 {G:g})")
    zones = spec.zones()
    if spec.escalator and zones["escalator"][1] - zones["escalator"][0] < spec.esc_truss_width - 1e-9:
        raise ValueError(f"출입구 {name}: 에스컬레이터 구역 폭({spec.escalator_zone:g}m)이 트러스 외폭보다 좁습니다")

    # ---------- 에스컬레이터 (없으면 같은 규칙의 가상 경사선으로 박스 형상만 정함)
    esp = spec.escalator_spec() if spec.escalator else None
    tan = math.tan(math.radians(spec.esc_angle_deg))
    D = spec.esc_truss_depth
    truss_lo = T + spec.lower_margin
    u_wp = truss_lo + spec.esc_lower_ext
    run_e = (G - zp) / tan
    u_up = u_wp + run_e
    truss_hi = u_up + spec.esc_upper_ext
    u_cross = u_wp + D / tan                          # 트러스 하면이 하부 바닥(Zp)을 다시 지나는 점 = 하부 피트 끝

    def nose(u):
        if u <= u_wp:
            return zp
        if u >= u_up:
            return G
        return zp + (u - u_wp) * tan

    # ---------- 바닥 상면 (계단 구역 S / 에스컬레이터 구역 E), 하면은 공통 — 끝은 상단 끝벽이 정해진 뒤 맞춤
    def s_top_for(end_u):
        return PL([_const(0.0, u_cross, zp), (u_cross, u_up, zp, G - D), _const(u_up, end_u, G - D)])

    # ---------- 계단: 첫 챌판 위치 = 하부 피트 끝(u_cross). 계단이 바닥 아래로 내려가면 하부 수평부 쪽으로 자동으로 앞당김
    ssp = spec.stair_spec()
    n, r, counts, run_s = plan_risers(G - zp, ssp)
    s_probe = s_top_for(u_up + run_s + 100.0)
    u_min = T + spec.lower_margin                     # 앞당길 수 있는 한계: 하부 이음벽 안쪽 면 + 여유

    def lowest(u0):
        """첫 챌판이 u0 일 때 (계단 슬래브 하면 − 계단 구역 바닥 상면) 최소값과 그 위치"""
        parts_ = stair_part_strips(ssp, counts, r, zp, lambda x: s_probe.at(u0 + x), lambda x: u0 + x, lambda *_: 1.0)
        return min([(st.zb0 - s_probe.at(st.s0, 1), st.s0) for p_ in parts_ for st in p_.strips] +
                   [(st.zb1 - s_probe.at(st.s1, -1), st.s1) for p_ in parts_ for st in p_.strips])

    def too_low(u0, gap):
        span = run_s + ssp.tread
        return ValueError(
            f"출입구 {name}: 계단이 박스 바닥 아래로 {-gap[0]:.2f}m 내려갑니다 (첫 챌판 u = {u0:.2f}m, 문제 위치 u = {gap[1]:.2f}m). "
            f"계단 평균 기울기 {math.degrees(math.atan((G - zp) / span)):.1f}° < 바닥(에스컬레이터) {spec.esc_angle_deg:g}° — "
            "계단참 길이·단너비를 줄이거나 런 높이 상한을 키워 계단을 가파르게 하세요")

    if spec.stair_offset is not None:                 # 직접 지정
        u_s0 = u_cross + spec.stair_offset
        if spec.stair_offset > 1e-9 or u_s0 < u_min - 1e-9:
            raise ValueError(f"출입구 {name}: 계단 첫 챌판 위치 조정(stair_offset)은 0 이하이고, 첫 챌판이 하부 수평부 안"
                             f"(u ≥ {u_min:.2f}m)에 있어야 합니다")
        gap = lowest(u_s0)
        if gap[0] < -1e-6:
            raise too_low(u_s0, gap)
    elif lowest(u_cross)[0] >= -1e-6:                 # 자동: 피트 끝에서 시작해도 바닥 위
        u_s0 = u_cross
    else:
        gap = lowest(u_min)
        if gap[0] < -1e-6:                            # 하부 수평부 끝까지 앞당겨도 바닥 아래
            raise too_low(u_min, gap)
        ok, bad = u_min, u_cross                      # 바닥 위에 머무는 가장 늦은 시작점 (앞당길수록 높아짐 → 이분법)
        for _ in range(60):
            mid = 0.5 * (ok + bad)
            if lowest(mid)[0] >= -1e-6:
                ok = mid
            else:
                bad = mid
        u_s0 = ok
    arrive = u_s0 + run_s + ssp.tread                 # 계단 위 지표 높이 디딤판 끝
    u_top = max(truss_hi if spec.escalator else u_up, arrive) + spec.top_margin

    # ---------- 바닥 (계단 구역 S / 에스컬레이터 구역 E), 하면은 공통
    end = u_top + T
    tb_segs = [_const(truss_lo - T, u_wp, zp - D), (u_wp, u_up, zp - D, G - D), _const(u_up, end, G - D)]
    e_top = PL([_const(0.0, truss_lo, zp), _const(truss_lo, u_wp, zp - D), (u_wp, u_up, zp - D, G - D),
                _const(u_up, truss_hi, G - D), _const(truss_hi, end, G)]) if spec.escalator else None
    s_top = s_top_for(end)
    bottom = PL([_const(0.0, truss_lo - T, zp - T)] + PL(tb_segs).offset(-T).segs)

    # ---------- 천장: 하면 = max(Zp + Hp, 코 선 + c), c 는 머리 높이 조건의 최소값 (천장 끝 위치와 함께 반복 계산)
    stair_parts = stair_part_strips(ssp, counts, r, zp, lambda x: s_top.at(u_s0 + x), lambda x: u_s0 + x,
                                    lambda *_: 1.0, top_extra=u_top - arrive)
    surfaces = [(u_s0 + ua, u_s0 + ub, zt) for p in stair_parts for ua, ub, zt in p.surfaces]
    c = spec.esc_headroom
    for _ in range(50):
        flat = max(hp, c)                                # 하부 천장 하면 높이 (통로 천장 또는 머리 높이 중 큰 쪽)
        u_k = u_wp + (flat - c) / tan                    # 천장 하면이 수평 → 경사로 꺾이는 점
        far = u_up + 50.0
        roof_bot = PL([_const(0.0, u_k, zp + flat), (u_k, far, zp + flat, zp + flat + (far - u_k) * tan)])
        roof_top = roof_bot.offset(T)
        u_re = next(u0 + (u1 - u0) * (G - z0) / (z1 - z0) for u0, u1, z0, z1 in roof_top.segs if z1 > G >= z0)
        need = max([c] + [zt + spec.stair_headroom - nose(x) for ua, ub, zt in surfaces for x in (ua, ub) if x < u_re])
        if need <= c + 1e-9:
            break
        c = need
    else:
        raise ValueError(f"출입구 {name}: 천장 높이 계산이 수렴하지 않습니다")

    # ---------- 박스 부재
    zs = zones
    parts = []

    def add(code, kind, t_range, strips):
        if strips:
            parts.append(EntrancePartLayout(code, kind, t_range, strips))

    if spec.escalator:
        sp0, sp1 = zs["partition"]
        e_side = spec.escalator_side
        boundary = sp1 if e_side > 0 else sp0                         # 계단·칸막이(S) | 에스컬레이터(E) 경계
        t_s = (-b, boundary) if e_side > 0 else (boundary, b)
        t_e = (boundary, b) if e_side > 0 else (-b, boundary)
        add("FLOOR_S", "FLOOR", t_s, strips_between(bottom, s_top, 0.0, end))
        add("FLOOR_E", "FLOOR", t_e, strips_between(bottom, e_top, 0.0, end))
    else:
        e_side = 1
        t_s = (-b, b)
        add("FLOOR_S", "FLOOR", t_s, strips_between(bottom, s_top, 0.0, end))
    add("ROOF", "ROOF", (-b, b), strips_between(roof_bot, roof_top, 0.0, u_re))
    wall_top = PL([(u0, min(u1, u_re), z0, z0 + (z1 - z0) * (min(u1, u_re) - u0) / (u1 - u0))
                   for u0, u1, z0, z1 in roof_bot.segs if u0 < u_re] + [_const(u_re, end, G + spec.parapet)])
    for code, t_rng in (("WALL_L", (a, b)), ("WALL_R", (-b, -a))):
        on_e = spec.escalator and ((t_rng[0] > 0) == (e_side > 0))
        add(code, "WALL", t_rng, strips_between(e_top if on_e else s_top, wall_top, 0.0, u_top))
    parapet = PL([_const(0.0, end, G + spec.parapet)])
    add("END_WALL_S", "WALL", t_s, strips_between(s_top, parapet, u_top, end))
    if spec.escalator:
        add("END_WALL_E", "WALL", t_e, strips_between(e_top, parapet, u_top, end))
    roof_lo = PL([_const(0.0, T, roof_bot.at(0.0))])
    if a - a_p > 1e-6:
        add("JOINT_WALL_L", "WALL", (a_p, a), strips_between(PL([_const(0.0, T, zp)]), roof_lo, 0.0, T))
        add("JOINT_WALL_R", "WALL", (-a, -a_p), strips_between(PL([_const(0.0, T, zp)]), roof_lo, 0.0, T))
    if spec.escalator:                                # 칸막이벽: 계단 구역 바닥 ~ 계단 슬래브 하면
        st_bot = PL(sorted((s.s0, s.s1, s.zb0, s.zb1) for p in stair_parts for s in p.strips))
        add("PARTITION", "WALL", zs["partition"], strips_between(s_top, st_bot, u_s0, u_top))

    # ---------- 천장 헌치 (천장 하면 구간마다 곧은 조각, 연직 단면이라 꺾임점에서 정확히 맞닿음)
    haunches = []
    if spec.haunch_w > 0 and spec.haunch_h > 0:
        hw, hh = spec.haunch_w, spec.haunch_h
        for u0, u1, z0, z1 in roof_bot.segs:
            u1 = min(u1, u_re)
            if u1 - u0 <= 1e-9:
                continue
            for sect in ([(a, -hh), (a - hw, 0.0), (a, 0.0)], [(-a, -hh), (-a, 0.0), (-a + hw, 0.0)]):
                haunches.append(BoxPiece(ox=frame.px, oy=frame.py, ux=frame.ux, uy=frame.uy, a0=u0, a1=u1, sect=sect,
                                         z0=z0, slope=(roof_bot.at(u1, -1) - z0) / (u1 - u0)))

    # ---------- 계단·에스컬레이터 부재 (출입구 좌표의 띠)
    stair = SimpleNamespace(parts=stair_parts, n_risers=n, riser=r, flight_risers=counts, run=run_s, start=u_s0)
    escalator = None
    if spec.escalator:
        eparts, _, _ = escalator_part_strips(esp, lambda x: nose(u_wp + x), zp, run_e, lambda x: u_wp + x, lambda *_: 1.0)
        escalator = SimpleNamespace(parts=eparts, run=run_e, rise=G - zp, spec=esp)

    return EntranceLayout(
        name=name, spec=spec, passage=spec.passage, frame=frame, z_floor=zp, ground=G,
        u=dict(wp_lo=u_wp, wp_hi=u_up, truss_lo=truss_lo, truss_hi=truss_hi, cross=u_cross, stair0=u_s0,
               arrive=arrive, top=u_top, end=end, roof_end=u_re, roof_knee=u_k),
        roof_clear=c, box_parts=parts, haunches=haunches, stair=stair, escalator=escalator)
