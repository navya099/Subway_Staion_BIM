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
import dataclasses
import math
from dataclasses import dataclass, field
from types import SimpleNamespace

from escalators.escalator_layout import escalator_part_strips
from helper.box_piece import BoxPiece
from helper.strip_member import Strip
from helper.taper_piece import TaperPiece
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
    code: str                 # FLOOR_S, FLOOR_E, ROOF, WALL_L, WALL_R, END_WALL_S, END_WALL_E, JOINT_WALL_L/R, PARTITION, LEAN
    kind: str                 # FLOOR / ROOF / WALL / LEAN (버림 콘크리트)   (두께 구간이 둘 이상이면 측벽·바닥·천장·버림은 _Z{k})
    t_range: tuple
    strips: list
    thick: float = None       # 부재 두께 (벽·슬래브: 그 구간 두께)
    pieces: list = field(default_factory=list)   # 바깥면 사선 전이 쐐기 (TaperPiece, 세계 좌표)


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
    escalator: object         # 첫 에스컬레이터 SimpleNamespace(parts, run, rise …) 또는 None (escalators[0])
    spec_stair_finish: object = None   # 계단 마감 설정 StairFinish (마감 끔 = None)
    finish: list = field(default_factory=list)     # 내부 마감 [(코드, 종류, 재질, t 범위, 띠)] (entrance_finish, 마감 끔 = [])
    finish_type: object = None         # 내부 마감 종류 FinishType (마감 끔 = None)
    ceiling_raise: float = 0.0         # 천장판·천장틀 두께만큼 올린 천장 슬래브 높이
    escalators: list = field(default_factory=list)  # 에스컬레이터 대마다 (모두 같은 제원·u, t 만 다름)
    top_level: float = None            # 상부 승강구 바닥 표고 (지표 + top_rise)


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


def _clip(pl: PL, lo: float, hi: float) -> PL:
    """lo ~ hi 로 자른 PL"""
    out = []
    for u0, u1, z0, z1 in pl.segs:
        a, b = max(u0, lo), min(u1, hi)
        if b - a > TOL:
            f = lambda x: z0 + (z1 - z0) * (x - u0) / (u1 - u0)
            out.append((a, b, f(a), f(b)))
    return PL(out)


def envelope(funcs) -> PL:
    """위쪽 포락선. funcs = [(PL, lo, hi)] — 각 함수는 lo ~ hi 에서만 (교차점에서 나누고, 이어진 같은 기울기 구간은 합침)"""
    lo_all, hi_all = min(f[1] for f in funcs), max(f[2] for f in funcs)
    xs = sorted({x for f, lo, hi in funcs for x in [lo, hi] + f.breaks if lo_all - TOL <= x <= hi_all + TOL})
    segs = []
    for a, b in zip(xs, xs[1:]):
        if b - a <= 1e-9:
            continue
        act = [f for f, lo, hi in funcs if lo <= a + TOL and b <= hi + TOL]
        if not act:
            continue
        ends = [(f.at(a, 1), f.at(b, -1)) for f in act]
        cut = {a, b}
        for i in range(len(act)):
            for j in range(i + 1, len(act)):
                d0, d1 = ends[i][0] - ends[j][0], ends[i][1] - ends[j][1]
                if d0 * d1 < 0:
                    cut.add(a + (b - a) * d0 / (d0 - d1))
        cs = sorted(cut)
        for x0, x1 in zip(cs, cs[1:]):
            if x1 - x0 <= 1e-9:
                continue
            val = lambda e, x: e[0] + (e[1] - e[0]) * (x - a) / (b - a)
            k = max(range(len(act)), key=lambda i: val(ends[i], 0.5 * (x0 + x1)))
            segs.append((x0, x1, val(ends[k], x0), val(ends[k], x1)))
    merged = []
    for sg in segs:                                       # 이어진 같은 기울기 구간 합침
        if merged:
            p = merged[-1]
            m0, m1 = (p[3] - p[2]) / (p[1] - p[0]), (sg[3] - sg[2]) / (sg[1] - sg[0])
            if abs(p[1] - sg[0]) < TOL and abs(p[3] - sg[2]) < 1e-9 and abs(m0 - m1) < 1e-9:
                merged[-1] = (p[0], sg[1], p[2], sg[3])
                continue
        merged.append(sg)
    return PL(merged)


def pitch_points(surfaces, tread: float, riser: float) -> list:
    """계단 피치선 꼭짓점 [(u, z)]: 첫 디딤판 코 한 단 앞의 바닥 ~ 디딤판 코들 (계단참·도착부처럼 긴 면은 끝 한 단 앞까지 수평).
    surfaces = [(u 시작 = 코, u 끝, 상면 z)] (오름차순)"""
    pts = [(surfaces[0][0] - tread, surfaces[0][2] - riser)]
    for ua, ub, zt in surfaces:
        pts.append((ua, zt))
        if ub - ua > 1.5 * tread:
            pts.append((ub - tread, zt))
    out = []
    for u, z in pts:
        if out and u <= out[-1][0] + 1e-9:
            continue
        out.append((u, z))
    return out


def split_strips(strips, u: float):
    """띠 목록을 u 에서 둘로 (앞 < u ≤ 뒤), 걸친 띠는 잘라 나눔"""
    lo, hi = [], []
    for st in strips:
        if st.s1 <= u + 1e-9:
            lo.append(st)
        elif st.s0 >= u - 1e-9:
            hi.append(st)
        else:
            lo.append(dataclasses.replace(st, s1=u, zb1=st.zb_at(u), zt1=None if st.zt1 is None else st.zt_at(u)))
            hi.append(dataclasses.replace(st, s0=u, zb0=st.zb_at(u), zt=st.zt_at(u)))
    return lo, hi


def splice_parts(full, narrow, u: float, full_rng: tuple, narrow_rng: tuple) -> list:
    """개구부 내공 축소 계단: u 앞은 전체 폭 계단(full), 뒤는 좁힌 계단(narrow)의 같은 순번 부재 (계단 구조 PartLayout /
    계단 마감 FinishPart — 폭만 다르고 u 배치는 같음). t 범위가 같으면 한 부재로 합치고 다르면 둘로 나눔 (디딤판 목록은 앞 부재)"""
    out = []
    for p, q in zip(full, narrow):
        lo, _ = split_strips(p.strips, u)
        _, hi = split_strips(q.strips, u)
        pr = p.t_range if p.t_range is not None else full_rng
        qr = q.t_range if q.t_range is not None else narrow_rng
        if lo and hi and abs(pr[0] - qr[0]) < 1e-9 and abs(pr[1] - qr[1]) < 1e-9:
            out.append(dataclasses.replace(p, strips=lo + hi))
            continue
        if lo:
            out.append(dataclasses.replace(p, strips=lo))
        if hi:
            extra = {"columns": q.columns} if hasattr(q, "columns") else {"surfaces": [], "n_risers": 0}
            out.append(dataclasses.replace(q, strips=hi, t_range=qr, **extra))
    return out


def taper_pieces(frame, O, Ot: float, sgn: int, bot, top, lo: float, hi: float) -> list:
    """바깥면 사선 전이 쐐기: t = 얇은 구간 바깥면 Ot ~ 사선 O(u) (sgn = 쪽), bot ~ top 사이 (lo ~ hi)"""
    out = []
    if hi - lo <= 1e-9:
        return out
    for st in strips_between(bot, top, lo, hi):
        o0, o1 = max(O(st.s0), Ot), max(O(st.s1), Ot)
        if max(o0, o1) - Ot <= 1e-9:
            continue
        if sgn > 0:
            ta0, tb0, ta1, tb1 = Ot, o0, Ot, o1
        else:
            ta0, tb0, ta1, tb1 = -o0, -Ot, -o1, -Ot
        out.append(TaperPiece(frame.px, frame.py, frame.ux, frame.uy, st.s0, st.s1, ta0, tb0, ta1, tb1,
                              st.zb0, st.zb1, st.zt, st.zt_end))
    return out


def outdoor_approach(spec, a: float, u0: float, G: float, Gt: float, side: int) -> list:
    """박스 앞(u0 부터 바깥) 경사로·계단 [(코드, 종류, t 범위, 띠)]. 경사로 = side 쪽 벽 옆 폭 ramp_width (Gt → G, 기울기 1/ramp_ratio),
    계단 = 나머지 폭 (단수 = 올림(높이 / 단높이 상한), 첫 단은 승강구에서 한 단 내려간 높이). 바닥 = 지표 − out_base"""
    h = Gt - G
    zb = G - spec.out_base
    out = []
    rw = min(max(spec.ramp_width, 0.0), 2 * a)
    if rw > 1e-9:
        t_r = (a - rw, a) if side > 0 else (-a, -a + rw)
        L = h * spec.ramp_ratio
        out.append(("OUT_RAMP", "RAMP", t_r, [Strip(u0, u0 + L, zb, zb, Gt, zt1=G)]))
    sw = 2 * a - rw
    if sw > 1e-9:
        t_s = (-a, a - rw) if side > 0 else (-a + rw, a)
        n = max(1, math.ceil(h / spec.out_riser_max - 1e-9))
        r = h / n
        strips = [Strip(u0 + (k - 1) * spec.out_tread, u0 + k * spec.out_tread, zb, zb, Gt - k * r) for k in range(1, n)]
        if strips:
            out.append(("OUT_STAIR", "STEPS", t_s, strips))
    return out


def layout_entrance(cfg, spec, name: str, passage_layouts: list) -> EntranceLayout:
    pl = next((p for p in passage_layouts if p.name == spec.passage), None)
    if pl is None:
        raise ValueError(f"출입구 {name}: 이어 붙일 출구통로 '{spec.passage}' 가 없습니다")
    va, vb = pl.vertices[-2], pl.vertices[-1]
    L = math.hypot(vb.x - va.x, vb.y - va.y)
    frame = EntranceFrame(vb.x, vb.y, (vb.x - va.x) / L, (vb.y - va.y) / L)
    G = spec.ground_el if spec.ground_el is not None else cfg.station.ground_el
    if G is None:
        raise ValueError(f"출입구 {name}: 지표 EL 을 입력하세요 (출입구마다 또는 정거장 공통 지표 EL)")
    zp = vb.z
    hp, a_p = pl.spec.inner_height, pl.spec.half_in
    T = spec.thick_at(0.0)                            # 이음면 쪽 벽·슬래브 두께 (두께 구간)
    W = spec.inner_width
    a = W / 2.0
    if W < 2 * a_p - 1e-6:
        raise ValueError(f"출입구 {name}: 내공 폭({W:g}m)이 통로 내공 폭({2 * a_p:g}m)보다 좁습니다")
    if G - zp < 2.0:
        raise ValueError(f"출입구 {name}: 지표 EL({G:g})이 통로 끝 바닥({zp:.3f})보다 충분히 높지 않습니다")
    if zp + hp + T >= G - spec.roof_cover - 1e-6:
        raise ValueError(f"출입구 {name}: 토피가 부족합니다 (통로 끝 천장 상면 {zp + hp + T:.3f} ≥ 지표 {G:g}"
                         + (f" − 흙 덮개 {spec.roof_cover:g}" if spec.roof_cover else "") + ")")
    Gt = G + spec.top_rise                            # 상부 승강구 바닥 (지표 + 높임) — 계단·에스컬레이터 위 끝, 도착부
    zones = spec.zones()
    if spec.escalator and spec.escalator_zone < spec.esc_truss_width - 1e-9:
        raise ValueError(f"출입구 {name}: 에스컬레이터 구역 폭({spec.escalator_zone:g}m)이 트러스 외폭보다 좁습니다")

    # ---------- 에스컬레이터 (없으면 같은 규칙의 가상 경사선으로 박스 형상만 정함)
    # 스텝 코 선 = 정거장 에스컬레이터와 같은 곡선 전이 NoseLine. 아래 = 통로 끝 바닥 마감면(통로 마감이 있으면 그 마감 높이), 위 = 지표
    from escalators.escalator_geom import NoseLine, layout_steps, step_range
    from passages.passage_finish import passage_finish_type
    pft = passage_finish_type(cfg, pl.spec)
    zl = zp + (pft.ffl if pft is not None else 0.0)    # 하부 승강구 바닥 마감면 (스텝 면 기준)
    esps = [spec.escalator_spec(k) for k in range(spec.n_escalators)]
    tan = math.tan(math.radians(spec.esc_angle_deg))
    D = spec.esc_truss_depth
    truss_lo = T + spec.lower_margin
    u_wp = truss_lo + spec.esc_lower_ext
    run_e = (Gt - zl) / tan
    u_up = u_wp + run_e
    truss_hi = u_up + spec.esc_upper_ext
    u_cross = u_wp + (D - (zl - zp)) / tan            # 트러스 하면이 하부 구조 바닥(Zp)을 다시 지나는 점 = 하부 피트 끝
    nl = NoseLine(zl, run_e, tan, lambda x: zl, lambda x: Gt, spec.esc_lower_radius, spec.esc_upper_radius)
    nose_bps = [u_wp + x for x in nl.breakpoints()]

    def nose(u):
        return nl(u - u_wp)

    def nose_pl(lo, hi, dz):
        """lo ~ hi 의 코 선 + dz (전이부 표본점에서 꺾인 PL)"""
        xs = sorted({lo, hi, *(x for x in nose_bps if lo < x < hi)})
        return [(a, b, nose(a) + dz, nose(b) + dz) for a, b in zip(xs, xs[1:])]

    # ---------- 바닥 상면 (계단 구역 S / 에스컬레이터 구역 E), 하면은 공통 — 끝은 상단 끝벽이 정해진 뒤 맞춤
    def s_top_for(end_u):
        return PL([_const(0.0, u_cross, zp), (u_cross, u_up, zp, Gt - D), _const(u_up, end_u, Gt - D)])

    # ---------- 계단: 첫 챌판 위치 = 하부 피트 끝(u_cross). 계단이 바닥 아래로 내려가면 하부 수평부 쪽으로 자동으로 앞당김
    # 계단 마감(마감을 켜고 계단 마감을 쓰면): 디딤판 = 통로 끝 바닥 마감면 ~ 지표를 같은 단높이로, 구조 = 매끈한 경사 슬래브 + 계단석
    fs = getattr(cfg, "finish_settings", None)
    fin = fs.stair_finish() if (fs is not None and spec.stair) else None
    z_st = zl if fin is not None else zp              # 첫 챌판 아래 걷는 면 (마감면 / 구조 바닥)
    if spec.stair:
        ssp = spec.stair_spec()
        n, r, counts, run_s = plan_risers(Gt - z_st, ssp)
    else:                                             # 에스컬레이터만: 계단 없음
        ssp, n, r, counts, run_s = None, 0, 0.0, [], 0.0
    s_probe = s_top_for(u_up + run_s + 100.0)
    u_min = T + spec.lower_margin                     # 앞당길 수 있는 한계: 하부 이음벽 안쪽 면 + 여유
    if fin is not None:
        fin.check(r)
        st_side = fin.side_t
        if not spec.escalator:                         # 옆면 마감: 칸막이벽 위로 드러나는 에스컬레이터 쪽만 (벽 쪽은 벽 마감)
            sides = (0.0, 0.0)
        else:
            sides = (0.0, st_side) if spec.escalator_side > 0 else (st_side, 0.0)

    def make_stair(u0, floor_pl, extra=0.0, sp=None):
        """첫 챌판 u0 의 계단 (구조 부재, 마감 부재). sp = 계단 제원 (비우면 계단 구역 전체 폭)"""
        sp = sp or ssp
        if fin is None:
            return stair_part_strips(sp, counts, r, zp, lambda x: floor_pl.at(u0 + x), lambda x: u0 + x,
                                     lambda *_: 1.0, top_extra=extra), []
        from stairs.stair_finish import finished_stair
        return finished_stair(sp, fin, counts, r, z_st, lambda x: floor_pl.at(u0 + x), lambda x: u0 + x,
                              lambda *_: 1.0, sides, top_extra=extra)

    def lowest(u0):
        """첫 챌판이 u0 일 때 (계단 슬래브 하면 − 계단 구역 바닥 상면) 최소값과 그 위치"""
        parts_ = make_stair(u0, s_probe)[0]
        return min([(st.zb0 - s_probe.at(st.s0, 1), st.s0) for p_ in parts_ for st in p_.strips] +
                   [(st.zb1 - s_probe.at(st.s1, -1), st.s1) for p_ in parts_ for st in p_.strips])

    def too_low(u0, gap):
        span = run_s + ssp.tread
        return ValueError(
            f"출입구 {name}: 계단이 박스 바닥 아래로 {-gap[0]:.2f}m 내려갑니다 (첫 챌판 u = {u0:.2f}m, 문제 위치 u = {gap[1]:.2f}m). "
            f"계단 평균 기울기 {math.degrees(math.atan((Gt - z_st) / span)):.1f}° < 바닥(에스컬레이터) {spec.esc_angle_deg:g}° — "
            "계단참 길이·단너비를 줄이거나 런 높이 상한을 키워 계단을 가파르게 하세요")

    if not spec.stair:
        u_s0 = truss_lo
    elif spec.stair_offset is not None:               # 직접 지정
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
    arrive = u_s0 + run_s + ssp.tread if spec.stair else 0.0     # 계단 위 지표 높이 디딤판 끝
    u_top = max(truss_hi if spec.escalator else u_up, arrive) + spec.top_margin

    # ---------- 두께 구간: [(u0, u1, 두께)] — 측벽·바닥·천장 바깥면이 구간마다 바뀜 (내공 고정)
    T_end = spec.thick_at(u_top)
    end = u_top + T_end
    far = u_up + 50.0
    cuts = [0.0] + spec.thick_cuts(0.0, far) + [far]
    zone_iv = [(u0, u1, spec.thick_at(u0)) for u0, u1 in zip(cuts, cuts[1:]) if u1 - u0 > 1e-9]
    zoned = len([z for z in zone_iv if z[0] < end - 1e-9]) > 1

    def offset_zoned(pl, sign):
        """구간마다 그 두께만큼 직각 평행 이동 (구간 경계에서 값이 뜀)"""
        segs = []
        for u0, u1, th in zone_iv:
            sub = _clip(pl, u0, u1)
            if sub.segs:
                segs += sub.offset(sign * th).segs
        return PL(segs)

    # ---------- 바닥 (계단 구역 S / 에스컬레이터 구역 E), 하면은 공통 (구조 상면선을 구간 두께만큼 내림)
    struct_top = PL([_const(0.0, truss_lo - T, zp), _const(truss_lo - T, u_wp, zl - D), (u_wp, u_up, zl - D, Gt - D),
                     _const(u_up, far, Gt - D)])
    e_top = PL([_const(0.0, truss_lo, zp)] + nose_pl(truss_lo, truss_hi, -D) +           # 트러스 하면 (곡선 전이 따라)
               [_const(truss_hi, end, Gt)]) if spec.escalator else None
    s_top = s_top_for(end)
    bottom = offset_zoned(struct_top, -1)

    # ---------- 천장 하면 = 위쪽 포락선: 통로 천장 높이 · 스텝 코 선 + 에스컬레이터 머리 높이 · 계단 피치선 + 계단 머리 높이
    # (계단 피치선 = 디딤판 코를 잇는 선, 계단참은 수평 → 실무 도면처럼 계단참에서 천장이 꺾임)
    stair_parts, stair_finish = make_stair(u_s0, s_top, u_top - arrive) if spec.stair else ([], [])   # 이미 출입구 좌표
    surfaces = sorted((u_s0 + ua, u_s0 + ub, zt) for p in stair_parts for ua, ub, zt in p.surfaces)
    # 내부 마감 종류 (마감 켤 때): 출입구 finish, 비우면 붙은 통로의 마감 종류. 천장이 있으면 천장판·틀만큼 천장 슬래브를 올림
    eft = None
    if fs is not None and fs.enabled:
        eft = fs.for_room("통로", (getattr(spec, "finish", "") or "").strip() or (getattr(pl.spec, "finish", "") or ""))
    from entrances.entrance_finish import ceiling_raise, layout_entrance_finish
    rz = ceiling_raise(spec, eft)
    eh, sh = spec.esc_headroom + rz, spec.stair_headroom + rz
    flat_pl = PL([_const(0.0, far, zp + hp)])
    esc_pl = PL(nose_pl(0.0, far, eh))
    heads = [(flat_pl, 0.0, far), (esc_pl, 0.0, far)]
    if surfaces:
        pitch = pitch_points(surfaces, ssp.tread, r)
        stair_pl = PL([(p[0], q[0], p[1] + sh, q[1] + sh) for p, q in zip(pitch, pitch[1:])])
        heads.append((stair_pl, pitch[0][0], pitch[-1][0]))
    roof_bot = envelope(heads)
    roof_top = offset_zoned(roof_bot, +1)
    target = G - spec.roof_cover                        # 천장 상면이 이 높이에 닿는 곳에서 끝 (흙 덮개)
    u_re = None
    for u0, u1, z0, z1 in roof_top.segs:
        if z0 >= target - 1e-12:
            u_re = u0
            break
        if z1 >= target:
            u_re = u0 + (u1 - u0) * (target - z0) / (z1 - z0)
            break
    if u_re is None:
        raise ValueError(f"출입구 {name}: 천장 슬래브가 지표에 닿지 않습니다 (지표 EL·흙 덮개 확인)")
    gaps = [(z - nose(x)) for u0, u1, z0, z1 in roof_bot.segs if u0 < u_re
            for x, z in ((u0, z0), (min(u1, u_re), roof_bot.at(min(u1, u_re), -1)))]
    c = min(gaps)

    # ---------- 평면 구간 [(u0, u1, 두께, 내공 반폭, 벽 두께)]: 두께 구간 + 개구부(u_re 뒤)는 내공 축소·개구부 벽 두께
    a_o = a - spec.open_narrow
    opened = spec.open_narrow > 0 or spec.open_wall_t is not None
    plan_iv = []
    for u0, u1, th in zone_iv:
        for lo, hi, op in (((u0, min(u1, u_re), False), (max(u0, u_re), u1, True)) if opened else ((u0, u1, False),)):
            if hi - lo > 1e-9:
                tw = spec.open_wall_t if (op and spec.open_wall_t is not None) else th
                plan_iv.append((lo, hi, th, a_o if op else a, tw))
    zoned = len([z for z in plan_iv if z[0] < end - 1e-9]) > 1

    def iv_at(u):
        return next((iv for iv in plan_iv if iv[0] - 1e-9 <= u < iv[1] - 1e-9), plan_iv[-1])
    u_k = next((u0 for u0, u1, z0, z1 in roof_bot.segs if z0 > zp + hp + 1e-9 or z1 > zp + hp + 1e-9), 0.0)

    # ---------- 박스 부재 (두께 구간이 둘 이상이면 측벽·바닥·천장·버림을 구간마다 _Z{k})
    zs = zones
    parts = []

    def add(code, kind, t_range, strips, thick=None):
        if strips:
            parts.append(EntrancePartLayout(code, kind, t_range, strips, thick))

    def add_zoned(code, kind, t_of, bot, top, lo, hi):
        """평면 구간마다 부재 (t_of(내공 반폭, 벽 두께) = t 범위)"""
        for k, (u0, u1, th, ai, tw) in enumerate(plan_iv, start=1):
            a0, a1 = max(lo, u0), min(hi, u1)
            if a1 - a0 > 1e-9:
                add(f"{code}_Z{k}" if zoned else code, kind, t_of(ai, tw), strips_between(bot, top, a0, a1),
                    tw if kind == "WALL" else th)

    if spec.escalator and spec.stair:
        sp0, sp1 = zs["partition"]
        e_side = spec.escalator_side
        boundary = sp1 if e_side > 0 else sp0                         # 계단·칸막이(S) | 에스컬레이터(E) 경계
        t_s = (lambda ai, tw: (-(ai + tw), boundary)) if e_side > 0 else (lambda ai, tw: (boundary, ai + tw))
        t_e = (lambda ai, tw: (boundary, ai + tw)) if e_side > 0 else (lambda ai, tw: (-(ai + tw), boundary))
        add_zoned("FLOOR_S", "FLOOR", t_s, bottom, s_top, 0.0, end)
        add_zoned("FLOOR_E", "FLOOR", t_e, bottom, e_top, 0.0, end)
    elif spec.escalator:                              # 에스컬레이터만: 바닥 전폭이 트러스 하면을 따름
        e_side = spec.escalator_side
        t_s = None
        t_e = lambda ai, tw: (-(ai + tw), ai + tw)
        add_zoned("FLOOR_E", "FLOOR", t_e, bottom, e_top, 0.0, end)
    else:
        e_side = 1
        t_s = lambda ai, tw: (-(ai + tw), ai + tw)
        add_zoned("FLOOR_S", "FLOOR", t_s, bottom, s_top, 0.0, end)
    add_zoned("ROOF", "ROOF", lambda ai, tw: (-(ai + tw), ai + tw), roof_bot, roof_top, 0.0, u_re)
    # 개구부 시작부 가로 파라펫 (천장 슬래브 끝에서 그 두께만큼, 천장 상면 ~ 지표 + 파라펫, 외곽 전폭 — 흙막이 겸 난간벽)
    T_re = spec.thick_at(u_re)
    if spec.parapet > 0 and u_re - T_re > 1e-6:
        add("PARAPET", "WALL", (-(a + T_re), a + T_re),
            strips_between(roof_top, PL([_const(0.0, far, Gt + spec.parapet)]), u_re - T_re, u_re), T_re)
    wall_top = PL([(u0, min(u1, u_re), z0, z0 + (z1 - z0) * (min(u1, u_re) - u0) / (u1 - u0))
                   for u0, u1, z0, z1 in roof_bot.segs if u0 < u_re] + [_const(u_re, end, Gt + spec.parapet)])
    for code, side in (("WALL_L", 1), ("WALL_R", -1)):
        on_e = spec.escalator and (not spec.stair or (side > 0) == (e_side > 0))
        add_zoned(code, "WALL", (lambda ai, tw, sd=side: (ai, ai + tw) if sd > 0 else (-(ai + tw), -ai)),
                  e_top if on_e else s_top, wall_top, 0.0, u_top)
    # 상단 끝벽: 높임이 있으면 승강구 바닥 높이까지만 (앞면 개방 = 출구, 앞에 바깥 경사로·계단), 없으면 지표 + 파라펫 (예전)
    parapet = PL([_const(0.0, end, Gt if spec.top_rise > 0 else G + spec.parapet)])
    _, _, _, ai_e, tw_e = iv_at(u_top)               # 상단 끝벽 자리의 평면 구간 (개구부면 축소된 내공·개구부 벽 두께)
    if spec.stair:
        add("END_WALL_S", "WALL", t_s(ai_e, tw_e), strips_between(s_top, parapet, u_top, end), T_end)
    if spec.escalator:
        add("END_WALL_E", "WALL", t_e(ai_e, tw_e), strips_between(e_top, parapet, u_top, end), T_end)
    roof_lo = PL([_const(0.0, T, roof_bot.at(0.0))])
    if a - a_p > 1e-6:
        add("JOINT_WALL_L", "WALL", (a_p, a), strips_between(PL([_const(0.0, T, zp)]), roof_lo, 0.0, T), T)
        add("JOINT_WALL_R", "WALL", (-a, -a_p), strips_between(PL([_const(0.0, T, zp)]), roof_lo, 0.0, T), T)
    if spec.escalator and spec.stair:                 # 칸막이벽: 계단 구역 바닥 ~ 계단 슬래브 하면
        st_bot = PL(sorted((s.s0, s.s1, s.zb0, s.zb1) for p in stair_parts for s in p.strips))
        add("PARTITION", "WALL", zs["partition"], strips_between(s_top, st_bot, u_s0, u_top), spec.partition_t)
    if spec.lean_t > 0:                               # 버림 콘크리트: 바닥 하면 아래, 외곽 밖으로 lean_ext
        add_zoned("LEAN", "LEAN", lambda ai, tw: (-(ai + tw + spec.lean_ext), ai + tw + spec.lean_ext),
                  bottom.offset(-spec.lean_t), bottom, 0.0, end)

    # ---------- 바깥 경사로·계단 (높임이 있을 때, 박스 앞 u ≥ end): 경사로 = 에스컬레이터 쪽 벽 옆 폭 ramp_width, 나머지 = 계단
    if spec.top_rise > 0:
        for code, kind, t_rng, strips in outdoor_approach(spec, ai_e, end, G, Gt, spec.escalator_side if spec.escalator else 1):
            add(code, kind, t_rng, strips)

    # ---------- 바깥면 사선 전이 (taper_ratio > 0): 평면 구간 경계에서 바깥면(내공 반폭 + 벽 두께)이 바뀌면 두꺼운 쪽 바깥면이
    # 얇은 구간 안으로 길이 = 기울기 × 차 만큼 사선으로 줄어듦. 쐐기는 바닥(바닥 하면 ~ 상면)·측벽(~ 벽 윗면)·천장 부재의 조각
    if spec.taper_ratio > 0:
        by_code = {p.code: p for p in parts}
        r_t = spec.taper_ratio
        ivs = [iv for iv in plan_iv if iv[0] < end - 1e-9]
        for j in range(len(ivs) - 1):
            L_, R_ = ivs[j], ivs[j + 1]
            ub, O1, O2 = R_[0], L_[3] + L_[4], R_[3] + R_[4]
            d = O1 - O2
            if abs(d) < 1e-9:
                continue
            if d > 0:                                    # 앞 구간이 두꺼움 → 뒤(얇은) 구간 안으로
                kt, Ot, lo, hi = j + 2, O2, ub, min(ub + r_t * d, R_[1])
                O = (lambda u, ub=ub, O1=O1: O1 - (u - ub) / r_t)
            else:                                        # 뒤 구간이 두꺼움 → 앞(얇은) 구간 안으로
                kt, Ot, lo, hi = j + 1, O1, max(ub + r_t * d, L_[0]), ub
                O = (lambda u, ub=ub, O2=O2: O2 - (ub - u) / r_t)
            for sgn in (1, -1):
                on_e = spec.escalator and (not spec.stair or (sgn > 0) == (e_side > 0))
                ftop = e_top if on_e else s_top
                for code, bot, top, l0, l1 in ((("FLOOR_E" if on_e else "FLOOR_S"), bottom, ftop, 0.0, end),
                                               ("WALL_L" if sgn > 0 else "WALL_R", ftop, wall_top, 0.0, u_top),
                                               ("ROOF", roof_bot, roof_top, 0.0, u_re)):
                    p = by_code.get(f"{code}_Z{kt}" if zoned else code)
                    if p is not None:
                        p.pieces += taper_pieces(frame, O, Ot, sgn, bot, top, max(lo, l0), min(hi, l1))

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

    # ---------- 내부 마감 (마감 켤 때): 하부 평탄부 바닥·측벽·경사 천장(천장 슬래브 하면 − 올림)·천장틀·막이
    finish = []
    if eft is not None:
        ceil_pl = PL([(u0, u1, z0 - rz, z1 - rz) for u0, u1, z0, z1 in roof_bot.segs]) if eft.ceiling else None
        joint_top = roof_bot.at(0.0)
        if pft is not None and pft.ceiling:
            from passages.passage_finish import ceiling_fit
            if ceiling_fit(pl.spec, pft)[0]:
                joint_top = min(joint_top, zp + pft.ffl + pft.ceiling_h)         # 통로 천장판 하면까지 막음
        finish = layout_entrance_finish(spec, eft, a=a, a_p=a_p, T=T, zones=zones, e_side=e_side if spec.escalator else 1,
                                        zl=zl, G=Gt, u_s0=u_s0, surfaces=surfaces, u_top=u_top, u_re=u_re, truss_lo=truss_lo,
                                        nose_at=nose, nose_breaks=nose_bps, ceil_pl=ceil_pl, roof_pl=roof_bot,
                                        joint_top=joint_top, a_open=a_o if spec.open_narrow > 0 else None)

    # ---------- 계단·에스컬레이터 부재 (출입구 좌표의 띠). 개구부 내공 축소: 계단의 개구부 쪽 조각은 벽 쪽 변을 축소된 내공면까지
    if spec.stair and spec.open_narrow > 0:
        z0, z1 = zones["stair"]
        n0, n1 = max(z0, -a_o), min(z1, a_o)
        if n0 > z0 + 1e-12 or n1 < z1 - 1e-12:         # 벽 쪽 변이 축소된 내공면 밖 → 그 폭으로 계단을 다시 만들어 뒤쪽을 씀
            ssp_n = dataclasses.replace(ssp, t_center=(n0 + n1) / 2.0, width=n1 - n0)
            n_parts, n_finish = make_stair(u_s0, s_top, u_top - arrive, ssp_n)
            stair_parts = splice_parts(stair_parts, n_parts, u_re, (z0, z1), (n0, n1))
            stair_finish = splice_parts(stair_finish, n_finish, u_re, (z0, z1), (n0, n1))
    stair = SimpleNamespace(parts=stair_parts, n_risers=n, riser=r, flight_risers=counts, run=run_s, start=u_s0,
                            finish=stair_finish, finish_base=z_st if fin is not None else None) if spec.stair else None
    escalators = []
    for esp in esps:                                  # 정거장 에스컬레이터와 같은 상세 형상 + 개별 스텝 (출입구 좌표 s = u_wp + u)
        s_lo, s_hi, _ = step_range(esp, nl)
        reach = esp.newel_ext + esp.newel_radius
        if s_lo - reach < -esp.lower_ext - 1e-6 or s_hi + reach > run_e + esp.upper_ext + 1e-6:
            raise ValueError(f"출입구 {name}: 에스컬레이터 스텝(평탄 스텝 + 곡선 전이부)과 끝 뉴얼이 트러스보다 깁니다 "
                             "(하부/상부 연장을 늘리거나 평탄 스텝 수·반경을 줄이세요)")
        eparts, _, _ = escalator_part_strips(esp, nl, zl, run_e, lambda x: u_wp + x, lambda *_: 1.0,
                                             extra_us=nl.breakpoints(), steps_range=(s_lo, s_hi))
        escalators.append(SimpleNamespace(parts=eparts, run=run_e, rise=Gt - zl, spec=esp, steps=layout_steps(esp, nl),
                                          nose=nl, u_wp=u_wp, finish_levels=(zl, Gt)))
    escalator = escalators[0] if escalators else None

    return EntranceLayout(
        name=name, spec=spec, passage=spec.passage, frame=frame, z_floor=zp, ground=G, top_level=Gt,
        u=dict(wp_lo=u_wp, wp_hi=u_up, truss_lo=truss_lo, truss_hi=truss_hi, cross=u_cross, stair0=u_s0,
               arrive=arrive, top=u_top, end=end, roof_end=u_re, roof_knee=u_k),
        roof_clear=c, box_parts=parts, haunches=haunches, stair=stair, escalator=escalator, spec_stair_finish=fin,
        finish=finish, finish_type=eft, ceiling_raise=rz, escalators=escalators)
