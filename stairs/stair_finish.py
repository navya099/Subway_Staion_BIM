"""계단 마감 (계단석 분리 구조): 구조 = 매끈한 경사 슬래브, 그 위에 스텝(판석 + 채움 / 통석 + 깔 몰탈 / 콘크리트 채움),
논슬립, 노출된 옆면 마감.

진행 좌표 u (첫 챌판 = 0, 오르는 방향 +), 표고는 절대 표고. 디딤판·계단참 상면(마감면)은 아래층 바닥 마감면 ~ 위층 바닥 마감면을
같은 단높이로 나눈 높이 (stair_layout 이 e_base·단높이를 마감면 기준으로 계산해 넘김).

- 마감 안쪽 모서리 선 corner_i(u): 런 i 의 디딤판 안쪽 모서리(챌판 아래)를 잇는 직선 (기울기 = 단높이 / 단너비)
- 구조 상면 T(u) = min(corner_i(u), 다음 면 높이) − depth  (런은 경사, 계단참·위층 도착은 다음 면 높이 − depth 수평, 그 사이 꺾임 =
  마지막 챌판 + 단너비 — 예전 일체형 계단과 같은 꺾임 위치), 구조 하면 = T − band (band = 허리 두께 / cos).
  첫 런은 시작면(바닥 슬래브 상면 / 승강장 상면) 아래를 잘라냄 (상·하면 모두 max(바닥, …))
- 스텝(칸 = 디딤판 하나 / 계단참 / 위층 도착 디딤판): 구조 상면 ~ 마감면.
  판석: 디딤판 판석 [Z − tread_t, Z] (칸 전체), 칸 앞 챌판 판석 [ua, ua + riser_t] × [Z − 단높이, Z − tread_t], 나머지 채움.
  통석: 칸 전체가 돌 [T + bed, Z] + 깔 몰탈 [T, T + bed] (계단참은 판석 방식).  콘크리트: 칸 전체 채움(콘크리트).
- 논슬립: 칸 앞 코에서 nosing_w × (폭 − 2·nosing_end) × 상면에서 nosing_t 깊이 — 그 자리 상부 재료에서 뺌
- 옆면: 노출된 쪽(내공면·벽에 붙지 않은 쪽) 계단 폭 안쪽 side_t, 스텝(계단석·채움)만 — 구조 상면 ~ 마감면, 스텝은 그만큼 좁아짐.
  구조 슬래브 옆면은 콘크리트 노출(실무 — 실제로는 옆 칸막이벽이 가림), 구조는 계단 폭 전체
"""
import math
from dataclasses import dataclass, field

from finishes.finish_spec import STEP_CONCRETE, STEP_PLATE, STEP_SOLID
from stairs.stair_shape import StairStrip
from stairs.stair_type import StairPartKind

TOL = 1e-9

# 마감 부재 코드 → (이름 꼬리, IFC PredefinedType)
CODES = {"TREAD": ("디딤판·계단참", "FLOORING"), "RISER": ("챌판", "CLADDING"), "STONE": ("계단석", "FLOORING"),
         "FILL": ("스텝 채움", "FLOORING"), "NOSING": ("논슬립", "USERDEFINED"), "SIDE": ("계단 옆면", "CLADDING")}


@dataclass
class FinishPart:
    """계단 마감 부재 1종 (띠 묶음, t 범위가 같은 조각끼리). code: CODES 키"""
    code: str
    material: str
    t_range: tuple
    strips: list = field(default_factory=list)
    columns: list = field(default_factory=list)   # 칸 [(s0, s1, 앞 코 s, 스텝 t0, t1, 계단참 여부)] — 텍스처를 디딤판마다 맞출 때


def _lin(xa, za, xb, zb):
    return lambda x: za if abs(xb - xa) < TOL else za + (zb - za) * (x - xa) / (xb - xa)


def _crossing(a, b, fa, fb):
    """[a, b] 에서 선형 f 가 0 을 지나는 점 (없으면 None)"""
    if (fa > TOL and fb < -TOL) or (fa < -TOL and fb > TOL):
        return a + (b - a) * fa / (fa - fb)
    return None


def finished_stair(spec, fin, counts: list, r: float, e_base: float, floor_fn, s_at, curve_factor, sides: tuple,
                   top_extra: float = 0.0):
    """(구조 부재 [PartLayout], 마감 부재 [FinishPart]).
    counts: 런별 챌판 수, r: 단높이 (마감면 기준), e_base: 아래층 바닥 마감면 표고 (첫 챌판 아래),
    floor_fn(u): 시작면(구조) 표고, s_at(u): 진행 좌표 → s, curve_factor(sa, sb, t_center), sides = (t0 쪽 옆면 두께, t1 쪽),
    top_extra: 위층 도착 디딤판 뒤로 같은 높이로 더 늘이는 길이 (출입구 상부 평탄부, 정거장은 0)"""
    from stairs.stair_layout import PartLayout
    g, w, d = spec.tread, spec.waist_t, fin.depth
    slope = r / g
    band = w * math.sqrt(1.0 + slope * slope)
    t0, t1 = spec.t_lo, spec.t_hi
    a0, a1 = t0 + sides[0], t1 - sides[1]                 # 스텝 t 범위 (구조는 계단 폭 전체 t0 ~ t1)
    tc = (t0 + t1) / 2.0
    n0, n1 = a0 + fin.nosing_end, a1 - fin.nosing_end      # 논슬립 t 범위
    use_nosing = fin.nosing and fin.nosing_w > TOL and fin.nosing_t > TOL and n1 - n0 > TOL
    fill_mat = "콘크리트" if fin.method == STEP_CONCRETE else fin.fill_material

    # ---- 칸 목록: (ua, ub, Z, corner 함수, 다음 면 높이, 앞 챌판 여부, 첫 런 여부, 계단참 여부, 부재 번호)
    cols, u, j0 = [], 0.0, 0
    part_defs = []                                       # (kind, n_risers, surfaces)
    for i, c in enumerate(counts):
        u_start, e_start = u, e_base + j0 * r
        corner = (lambda x, u0=u_start, e0=e_start: e0 + (x - u0) * slope)
        u_end = u_start + (c - 1) * g
        top = e_base + (j0 + c) * r
        pidx = len(part_defs)
        surfaces = []
        for m in range(1, c):
            ua, ub, zt = u_start + (m - 1) * g, u_start + m * g, e_start + m * r
            surfaces.append((ua, ub, zt))
            cols.append((ua, ub, zt, corner, top, i == 0, False, pidx))
        part_defs.append([StairPartKind.FLIGHT, c, surfaces])
        if i < len(counts) - 1:
            lidx = len(part_defs)
            part_defs.append([StairPartKind.LANDING, 0, [(u_end, u_end + spec.landing_len, top)]])
            cols.append((u_end, u_end + spec.landing_len, top, corner, top, False, True, lidx))
            u = u_end + spec.landing_len
        else:
            cols.append((u_end, u_end + g + top_extra, top, corner, top, False, False, pidx))
        j0 += c

    struct = [[] for _ in part_defs]
    pieces = {}                                          # (code, t0, t1) → 띠

    def add(code, ta, tb, ua, ub, zba, zbb, zta, ztb):
        if ub - ua < TOL or (zta - zba < TOL and ztb - zbb < TOL):
            return
        sa, sb = s_at(ua), s_at(ub)
        if sa > sb:
            sa, sb, zba, zbb, zta, ztb = sb, sa, zbb, zba, ztb, zta
        flat = abs(ztb - zta) < 1e-12
        stp = StairStrip(sa, sb, zba, zbb, zta, curve_factor=curve_factor(sa, sb, (ta + tb) / 2.0),
                         zt1=None if flat else ztb)
        pieces.setdefault((code, ta, tb), []).append(stp)

    for ua, ub, Z, corner, top, first, landing, pidx in cols:
        T = lambda x, cn=corner, tp=top: min(cn(x), tp) - d
        knee = None
        if corner(ua) < top - TOL and corner(ub) > top + TOL:
            knee = ua + (top - corner(ua)) / slope
        cuts = {ua, ub}
        if knee is not None:
            cuts.add(knee)
        front = ua                                       # 칸 앞(아래쪽) 챌판 위치
        riser_z0 = Z - r                                 # 앞 챌판 아래 끝 = 아래 디딤판(또는 아래층 마감면) 높이
        solid = fin.method == STEP_SOLID and not landing
        plate = fin.method == STEP_PLATE or (fin.method == STEP_SOLID and landing)   # 통석도 계단참은 판석
        if plate:
            cuts.add(min(ub, front + fin.riser_t))
        if use_nosing:
            cuts.add(min(ub, front + fin.nosing_w))
        if first:                                        # 구조 상·하면이 시작면을 지나는 점
            sc = sorted(cuts)
            for a, b in zip(sc, sc[1:]):
                for f in (lambda x: T(x) - floor_fn(x), lambda x: T(x) - band - floor_fn(x)):
                    x = _crossing(a, b, f(a), f(b))
                    if x is not None:
                        cuts.add(x)
        sc = sorted(cuts)
        for a, b in zip(sc, sc[1:]):
            if b - a < TOL:
                continue
            if first:
                top_a, top_b = max(floor_fn(a), T(a)), max(floor_fn(b), T(b))
                bot_a, bot_b = max(floor_fn(a), T(a) - band), max(floor_fn(b), T(b) - band)
            else:
                top_a, top_b = T(a), T(b)
                bot_a, bot_b = top_a - band, top_b - band
            # 구조
            if top_a - bot_a > TOL or top_b - bot_b > TOL:
                sa, sb = s_at(a), s_at(b)
                za, zb_, ya, yb = bot_a, bot_b, top_a, top_b
                if sa > sb:
                    sa, sb, za, zb_, ya, yb = sb, sa, zb_, za, yb, ya
                struct[pidx].append(StairStrip(sa, sb, za, zb_, ya, curve_factor=curve_factor(sa, sb, tc),
                                               zt1=None if abs(yb - ya) < 1e-12 else yb))
            # 옆면 (노출된 쪽, 스텝 부분만 — 구조 상면 ~ 마감면)
            if sides[0] > TOL:
                add("SIDE", t0, a0, a, b, top_a, top_b, Z, Z)
            if sides[1] > TOL:
                add("SIDE", a1, t1, a, b, top_a, top_b, Z, Z)
            # 스텝
            in_riser = plate and b <= front + fin.riser_t + TOL
            in_nose = use_nosing and b <= front + fin.nosing_w + TOL
            # 아래에서 위로 쌓는 재료 [(코드, 재질, 하면 a, 하면 b, 상면 a, 상면 b)] — 맨 위 재료에서 논슬립을 뺌
            if fin.method == STEP_CONCRETE:
                layers = [("FILL", fill_mat, top_a, top_b, Z, Z)]
            elif solid:
                layers = [("FILL", fill_mat, top_a, top_b, top_a + fin.bed, top_b + fin.bed),
                          ("STONE", fin.material, top_a + fin.bed, top_b + fin.bed, Z, Z)]
            elif in_riser:
                zr = max(riser_z0, top_a, top_b)          # 첫 챌판: 아래층 마감면 아래는 채움이 맡음
                layers = [("FILL", fill_mat, top_a, top_b, zr, zr),
                          ("RISER", fin.material, zr, zr, Z - fin.tread_t, Z - fin.tread_t),
                          ("TREAD", fin.material, Z - fin.tread_t, Z - fin.tread_t, Z, Z)]
            else:
                zp = Z - fin.tread_t
                layers = [("FILL", fill_mat, top_a, top_b, zp, zp), ("TREAD", fin.material, zp, zp, Z, Z)]
            for k, (code, _, za, zb_, zta, ztb) in enumerate(layers):
                if in_nose and k == len(layers) - 1:
                    zcut = Z - fin.nosing_t
                    add(code, a0, a1, a, b, za, zb_, zcut, zcut)
                    add(code, a0, n0, a, b, zcut, zcut, Z, Z)
                    add(code, n1, a1, a, b, zcut, zcut, Z, Z)
                    add("NOSING", n0, n1, a, b, zcut, zcut, Z, Z)
                else:
                    add(code, a0, a1, a, b, za, zb_, zta, ztb)

    parts = []
    for (kind, n_r, surfaces), strips in zip(part_defs, struct):
        parts.append(PartLayout(kind, sorted(strips, key=lambda s: s.s0), n_risers=n_r, surfaces=surfaces,
                                t_range=(t0, t1)))
    mats = {"TREAD": fin.material, "RISER": fin.material, "STONE": fin.material, "FILL": fill_mat,
            "NOSING": fin.nosing_material, "SIDE": fin.side_material}
    columns = sorted((*sorted((s_at(ua), s_at(ub))), s_at(ua), a0, a1, landing) for ua, ub, _, _, _, _, landing, _ in cols)
    out = [FinishPart(code, mats[code], (ta, tb), sorted(strips, key=lambda s: s.s0), columns)
           for (code, ta, tb), strips in sorted(pieces.items(), key=lambda kv: (list(CODES).index(kv[0][0]), kv[0][1]))]
    return parts, out
