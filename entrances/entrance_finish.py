"""출입구 내부 마감 (리팩토링 4단계): 하부 평탄부 바닥 · 측벽 · 경사 천장판 · 천장틀 · 천장 끝 막이 · 상단 끝벽.

마감 종류 = 출입구 spec.finish, 비우면 붙은 출구통로의 마감 종류(통로의 finish, 비우면 '통로'). 모든 부재는 출입구 좌표의 띠
(Strip: s = u, 절대 표고) — 형상·체적·IFC 는 박스 부재와 같은 길을 씀.

- 바닥: 하부 평탄부만 (사용자 지정) — 이음면(u=0) ~ 계단 첫 챌판(계단·칸막이 구역) / 트러스 하단 끝(에스컬레이터 구역), 채움 + 마감재,
  마감면 = 통로 끝 바닥 마감면 (계단·ESC 승강구와 같은 높이)
- 측벽: 구조 벽 안쪽 면에서 face 띄운 패널 (wall_t). 아래 끝 = 하부 평탄부는 바닥 마감면, 계단 쪽은 디딤판·계단참 윗면(칸마다),
  에스컬레이터 쪽은 스텝 코 선(그 아래 트러스 옆은 피트 — 마감 없음). 위 끝 = 천장 구간은 천장판 하면, 지붕 없는 개구부는 지표 + 파라펫
- 천장: 천장 슬래브 하면과 나란한 경사 천장 — 천장판 하면 = 천장 슬래브 하면 − raise (layout 이 그만큼 천장 슬래브를 올려 머리 높이 유지),
  천장판 위 천장틀 (바 = 축에 직각, u 방향 bar_spacing / 캐링 = 축 방향, t 방향 carrier_spacing). 천장은 벽 마감 표면 사이
- 막이: 이음면(u=0)에서 천장판 위 ~ (통로 천장판 하면 또는 천장 슬래브 하면), 개구부 쪽 천장 끝에서 천장판 위 ~ 천장 슬래브 하면 (천장 속 가림)
- 상단 끝벽 안쪽 면: 지표 ~ 지표 + 파라펫
"""
import math

from helper.strip_member import Strip

TOL = 1e-9


def ceiling_raise(spec, ft) -> float:
    """천장판·천장틀(+ 벽 마감 표면 자리의 헌치)만큼 천장 슬래브를 올리는 높이 (천장 없으면 0)"""
    if ft is None or not ft.ceiling:
        return 0.0
    face = ft.face if ft.wall_t > 0 else 0.0
    hc = 0.0
    if spec.haunch_w > 0 and spec.haunch_h > 0 and face < spec.haunch_w:
        hc = spec.haunch_h * (1.0 - face / spec.haunch_w)
    return ft.board_t + ft.frame_depth + hc


def _strips(bot, top, lo, hi, breaks=()) -> list:
    """bot(u)·top(u) 사이 띠 (lo ~ hi, breaks 에서 나눔 — 두 함수는 그 사이 선형이어야 함)"""
    cuts = sorted({lo, hi, *(x for x in breaks if lo + TOL < x < hi - TOL)})
    out = []
    for a, b in zip(cuts, cuts[1:]):
        if b - a <= 1e-9:
            continue
        e = min(1e-6, (b - a) / 4.0)                      # 구간 안쪽 두 점에서 재고 양 끝으로 선형 연장 (경계의 값 뜀을 피함, 선형이라 정확)
        zb0, zb1 = _ends(bot, a, b, e)
        zt0, zt1 = _ends(top, a, b, e)
        if zt0 - zb0 > 1e-9 or zt1 - zb1 > 1e-9:
            out.append(Strip(a, b, zb0, zb1, zt0, zt1=None if abs(zt1 - zt0) < 1e-12 else zt1))
    return out


def _ends(f, a, b, e):
    fa, fb = f(a + e), f(b - e)
    k = (fb - fa) / (b - a - 2 * e)
    return fa - k * e, fb + k * e


def layout_entrance_finish(spec, ft, *, a, a_p, T, zones, e_side, zl, G, u_s0, surfaces, u_top, u_re, truss_lo,
                           nose_at, nose_breaks, ceil_pl, roof_pl, joint_top) -> list:
    """[(코드, 종류, 재질, t 범위, 띠 목록)]. 종류 = FLOOR / FILL / WALL / CEILING / FRAME.
    ceil_pl = 천장판 하면 PL (천장 없으면 None), roof_pl = 천장 슬래브 하면 PL, joint_top = 이음면 막이 윗면 표고,
    surfaces = 계단 디딤판·계단참 [(u0, u1, 윗면)] (출입구 좌표), nose_at(u) = 스텝 코 선.
    a_p = 통로 내공 반폭, T = 이음벽 두께: 출입구가 통로보다 넓으면 이음벽(u 0 ~ T, |t| a_p ~ a)이 있어 — 바닥은 그 밖 u ≥ T,
    측벽 마감은 이음벽 면 마감 뒤부터, 이음벽 면(u = T)에 마감 패널, 천장은 이음벽 면 마감 표면(u = T + face)부터 전폭,
    그 앞(통로와 이어지는 곳)은 통로 폭(벽 마감 표면 사이)만"""
    out = []
    face = ft.face if ft.wall_t > 0 else 0.0
    c = a - face                                         # 벽 마감 표면 (천장 반폭)
    ceil = ceil_pl is not None
    joint = a - a_p > 1e-6
    u_j = T + face if joint else 0.0                     # 이음벽 면 마감 표면 (그 뒤 전폭)
    cp = a_p - face                                      # 통로 폭 안 벽 마감 표면 (이음 구간 천장 반폭)

    def add(code, kind, mat, t_range, strips):
        if strips:
            out.append((code, kind, mat, t_range, strips))

    # ---- 바닥 (하부 평탄부): 채움 + 마감재
    if ft.ffl > TOL:
        mat0 = zl - ft.floor_t
        z_struct = zl - ft.ffl
        esc = zones.get("escalator")
        regions = []
        if esc is None:
            regions.append(((-a, a), u_s0))
        else:
            other = (-a, esc[0]) if e_side > 0 else (esc[1], a)
            regions += [(other, u_s0), (esc, truss_lo)]
        if joint:                                        # 이음 구간 (u 0 ~ T): 통로 폭만, 그 뒤 전폭
            regions = [((-a_p, a_p), T, 0.0)] + [(t_rng, u_end, T) for t_rng, u_end in regions]
        else:
            regions = [(t_rng, u_end, 0.0) for t_rng, u_end in regions]
        for k, (t_rng, u_end, u_beg) in enumerate(regions, start=1):
            if u_end - u_beg <= TOL:
                continue
            if ft.floor_fill == "mortar" and mat0 - z_struct > TOL:
                add(f"FIN_FILL{k}", "FILL", "몰탈", t_rng, [Strip(u_beg, u_end, z_struct, z_struct, mat0)])
            add(f"FIN_FLOOR{k}", "FLOOR", ft.floor_material, t_rng, [Strip(u_beg, u_end, mat0, mat0, zl)])

    # ---- 천장 위 끝 (천장 구간 = 천장판 하면, 개구부 = 지표 + 파라펫)
    top_open = G + spec.parapet

    def wall_top(u):
        if u >= u_re:
            return top_open
        return ceil_pl.at(u) if ceil else roof_pl.at(u)
    top_breaks = sorted(set((ceil_pl if ceil else roof_pl).breaks) | {u_re})

    # ---- 측벽 (구조 벽 안쪽 면에서 face 띄운 패널)
    if ft.wall_t > 0:
        stair_bot = _stair_bottom(zl, G, u_s0, surfaces, u_top)
        for code, sgn in (("FIN_WALL_L", 1), ("FIN_WALL_R", -1)):
            t_rng = tuple(sorted((sgn * c, sgn * (c + ft.wall_t))))
            on_esc = "escalator" in zones and (sgn > 0) == (e_side > 0)
            if on_esc:
                bot = lambda u: zl if u < truss_lo else nose_at(u)
                br = [truss_lo] + list(nose_breaks)
            else:
                bot, br = stair_bot
            add(code, "WALL", ft.wall_material, t_rng, _strips(bot, wall_top, u_j - ft.wall_t if joint else 0.0, u_top,
                                                               list(br) + top_breaks))
            if joint:                                    # 이음벽 면 (u = T) 마감: 통로 벽 마감 표면 ~ 출입구 벽 마감 표면
                jt = tuple(sorted((sgn * cp, sgn * c)))
                add(f"FIN_JOINT_{code[-1]}", "WALL", ft.wall_material, jt,
                    _strips(lambda u: zl, wall_top, u_j - ft.wall_t, u_j, top_breaks))
        # 상단 끝벽 안쪽 면 (지표 ~ 파라펫, 개구부)
        e0 = u_top - face
        add("FIN_END_WALL", "WALL", ft.wall_material, (-c, c), [Strip(e0, e0 + ft.wall_t, G, G, top_open)])

    # ---- 천장판·천장틀·막이
    if ceil:
        bt = ft.board_t
        brk = ceil_pl.breaks
        add("FIN_CEILING", "CEILING", ft.ceiling_material, (-c, c),
            _strips(ceil_pl.at, lambda u: ceil_pl.at(u) + bt, u_j, u_re, brk))
        if joint:
            add("FIN_CEILING_J", "CEILING", ft.ceiling_material, (-cp, cp),
                _strips(ceil_pl.at, lambda u: ceil_pl.at(u) + bt, 0.0, u_j, brk))
        wt = max(ft.wall_t, 0.01)                         # 막이 두께 (벽 마감재, 면처리면 1cm)
        f_lo, f_hi = max(wt, u_j), u_re - wt             # 천장틀은 막이 사이 (전폭 천장 위)
        bars, k = [], math.ceil((f_lo + ft.bar_w / 2.0) / ft.bar_spacing - 1e-9)
        while k * ft.bar_spacing + ft.bar_w / 2.0 <= f_hi + TOL:
            u = k * ft.bar_spacing
            ua, ub = u - ft.bar_w / 2.0, u + ft.bar_w / 2.0
            bars += _strips(lambda x: ceil_pl.at(x) + bt, lambda x: ceil_pl.at(x) + bt + ft.bar_h, ua, ub, brk)
            k += 1
        add("FIN_FRAME_BAR", "FRAME", f"{ft.frame}바 천장틀", (-c, c), bars)
        n = int(math.floor((c - ft.carrier_w / 2.0) / ft.carrier_spacing + 1e-9))
        for j in range(-n, n + 1):
            v = j * ft.carrier_spacing
            add(f"FIN_FRAME_C{j + n + 1}", "FRAME", f"{ft.frame}바 천장틀", (v - ft.carrier_w / 2.0, v + ft.carrier_w / 2.0),
                _strips(lambda x: ceil_pl.at(x) + bt + ft.bar_h, lambda x: ceil_pl.at(x) + bt + ft.bar_h + ft.carrier_h,
                        f_lo, f_hi, brk))
        heads = []
        if joint_top - (ceil_pl.at(0.0) + bt) > 1e-6:      # 이음면 막이: 천장판 위 ~ 통로 천장판 하면(또는 천장 슬래브 하면)
            z0 = ceil_pl.at(0.0) + bt
            add("FIN_HEAD_J", "WALL", ft.wall_material, (-cp, cp) if joint else (-c, c),
                [Strip(0.0, wt, z0, ceil_pl.at(wt) + bt, joint_top)])
        z1 = ceil_pl.at(u_re - wt) + bt                  # 개구부 쪽 천장 끝 막이: 천장판 위 ~ 천장 슬래브 하면
        zr = min(roof_pl.at(u_re - wt), roof_pl.at(u_re))
        if zr - z1 > 1e-6:
            heads.append(Strip(u_re - wt, u_re, z1, ceil_pl.at(u_re) + bt, zr))
        add("FIN_HEAD", "WALL", ft.wall_material, (-c, c), heads)
    return out


def _stair_bottom(zl, G, u_s0, surfaces, u_top):
    """계단 쪽 벽 마감 아래 끝: 하부 평탄부 = 바닥 마감면, 계단 = 그 칸 디딤판·계단참 윗면, 마지막 뒤 = 지표 (계단단 꺾임마다 나눔)"""
    srf = sorted(surfaces)
    last = max(b for _, b, _ in srf) if srf else u_s0

    def bot(u):
        if u < u_s0:
            return zl
        for ua, ub, z in srf:
            if ua - TOL <= u < ub - TOL:
                return z
        return G if u >= last - TOL else zl
    breaks = [u_s0] + [x for ua, ub, _ in srf for x in (ua, ub)] + [last]
    return bot, sorted(set(breaks))
