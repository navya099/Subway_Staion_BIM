"""구조물 내공 확폭 층의 실 마감 (사다리꼴 영역).

finish_layout.layout_room_finishes 가 실 영역이 사다리꼴 조각(RoomLayout.traps)인 실에 쓴다. 규칙은 직사각형 실과 같고,
본체 측벽 내공면(사선 전이부·직각 계단 포함)의 벽 마감은 내공면 폴리선을 이격·마감 표면 거리만큼 수직으로 띄운 띠
(widening.offset_polyline → band, 사선 벽도 같은 이격·두께, 꺾임점 연귀). 조각은 (s0, s1, t0, t1, z0, z1[, trap]) —
trap 이 있으면 사다리꼴 (helper.trap_region 형식의 (t0, t1 @ s0, t0, t1 @ s1)).
"""
from config.widening import band, inner_polyline, offset_polyline, on_inner_face
from helper import trap_region as T
from openings import decompose

_EPS = 1e-6



def _out(p, z0, z1, extra=()):
    s0, s1, ta, tb = T.bbox(p)
    tr = T.trap_of(p)
    return (s0, s1, ta, tb, z0, z1, *extra) if tr is None else (s0, s1, ta, tb, z0, z1, *extra, tr)


def piece_region(x) -> tuple:
    """조각 (s0, s1, t0, t1, ...[, trap]) 의 평면 사다리꼴 (trap 은 끝 원소가 4개짜리 tuple 일 때)"""
    tr = x[-1] if isinstance(x[-1], tuple) and len(x[-1]) == 4 else None
    return T.rect(*x[:4]) if tr is None else (x[0], x[1], *tr)


def _zone_traps(zones, hw):
    """기준 바닥 t 구간 → 사다리꼴 조각 (내공면 쪽 끝은 넓어진 내공까지)"""
    out = []
    for p0, p1, zb in zones:
        a = -T.BIG if abs(p0 + hw) < _EPS else p0
        b = T.BIG if abs(p1 - hw) < _EPS else p1
        out.append((T.rect(-T.BIG, T.BIG, a, b), zb))
    return out


def side_bands(cfg, floor_n: int, d0: float, d1: float) -> list:
    """양쪽 측벽 내공면에서 안쪽으로 d0 ~ d1 띠 (사다리꼴 조각, s 0 ~ L)"""
    st = cfg.station
    L = st.length
    pad = st.max_wall_t + 1.0
    out = []
    for side in (1, -1):
        P = inner_polyline(cfg, floor_n, side, -pad, L + pad)
        lo, hi = (offset_polyline(P, -d1), offset_polyline(P, -d0) if d0 > 1e-12 else P)
        for s0, s1, l0, h0, l1, h1 in band(lo, hi, 0.0, L):
            out.append((s0, s1, l0, h0, l1, h1) if side > 0 else (s0, s1, -h0, -l0, -h1, -l1))
    return T.merge(out)


def _cut_s_holes(p, z0, z1, holes):
    """s 방향 띠 조각 p (사다리꼴) 에서 벽 평면 (s, z) 구멍 [(s0, s1, z0, z1)] 을 뺀 조각들"""
    hs = [(max(a, p[0]), min(b, p[1]), max(c, z0), min(d, z1)) for a, b, c, d in holes]
    hs = [h for h in hs if h[1] - h[0] > _EPS and h[3] - h[2] > _EPS]
    if not hs:
        return [_out(p, z0, z1)]
    out = []
    for u0, u1, w0, w1 in decompose.subtract_rects((p[0], p[1], z0, z1), hs):
        lo0, hi0 = T.at(p, u0)
        lo1, hi1 = T.at(p, u1)
        out.append(_out((u0, u1, lo0, hi0, lo1, hi1), w0, w1))
    return out


def finish_trap_room(cfg, room, rf, ft, ctx):
    """사다리꼴 영역 실 하나의 마감 → rf (RoomFinishLayout) 에 채움. ctx: layout_room_finishes 의 층 공통 값"""
    from finishes.finish_layout import FILL_MORTAR, _circle_ring, _cut_holes, _grid, _grow, _ring_rects, room_wall_holes
    st = cfg.station
    n, L, hw = rf.floor, st.length, st.width / 2.0
    clear = ctx["clear"]
    region = room.region()
    zones = _zone_traps(ctx["zones"], hw)
    obstacles = list(ctx["obstacles_t"])
    f = ft.wall_t
    wall_top = rf.ceiling_rel if ft.ceiling else ctx["top_slab"]

    # ---- 바닥
    if ft.ffl > _EPS:
        holes = obstacles + T.from_rects(ctx["stair_fp"] + ctx["below"])
        blocks = [b for b in ctx["tactile"] if b.floor == n]
        for zt, zb in zones:
            area = T.intersect(region, [zt])
            area = T.subtract(area, holes) if holes else area
            z_top = zb + ft.ffl
            if blocks and ft.floor_t > _EPS:
                for b in blocks:
                    for c in T.intersect(area, [T.rect(*b.rect)]):
                        rf.tactile.append(_out(c, z_top - ft.floor_t, z_top, (b.kind,)))
                area_top = T.subtract(area, T.from_rects([b.rect for b in blocks]))
            else:
                area_top = area
            if ft.floor_t > _EPS:
                rf.floor_top += [_out(p, z_top - ft.floor_t, z_top) for p in area_top]
            if ft.floor_fill == FILL_MORTAR and z_top - ft.floor_t - zb > _EPS:
                rf.floor_fill += [_out(p, zb, z_top - ft.floor_t) for p in area]

    def wall_pass(w):
        """벽 마감 한 벌 (패널 또는 걸레받이, finish_spec.WallPass) → (벽 조각, 둘레 조각, 원기둥 고리, 마감 표면까지 영역)"""
        gap, face = w.gap, w.face
        columns_out, rings_out = [], []
        face_regs = []                                       # 구조체 면 ~ 마감 표면 (천장에서 뺌)
        segs = T.boundary(region)
        sides = set()
        for a, b, _ in segs:
            if on_inner_face(cfg, n, a, b) and not (abs(a[0] - b[0]) < _EPS and (abs(a[0]) < _EPS or abs(a[0] - L) < _EPS)):
                sides.add(1 if (a[1] + b[1]) > 0 else -1)
        # 본체 측벽 내공면: 띠 ∩ 실 영역 (사선 전이부·직각 계단을 따라감)
        primary, secondary, gaps = [], [], []
        band_face, band_gap = side_bands(cfg, n, gap, face), (side_bands(cfg, n, 0.0, gap) if gap > _EPS else [])
        band_full = side_bands(cfg, n, 0.0, face)
        for side in sides:
            pick = lambda ps: [p for p in ps if (p[2] + p[3] + p[4] + p[5]) * side > 0]
            primary += [(p, "side", side) for p in T.intersect(pick(band_face), region)]
            gaps += T.intersect(pick(band_gap), region) if band_gap else []
            face_regs += T.intersect(pick(band_full), region)
        lines = ctx["lines"]
        for a, b, nrm in segs:
            vertical = abs(a[0] - b[0]) < _EPS
            horizontal = abs(a[1] - b[1]) < _EPS
            end = vertical and (abs(a[0]) < _EPS or abs(a[0] - L) < _EPS)
            if not (vertical or horizontal):
                continue                                         # 사선 = 본체 측벽 (띠로 처리)
            if not end and on_inner_face(cfg, n, a, b):
                continue                                         # 측벽 내공면 (띠로 처리)
            axis = "t" if vertical else "s"
            c = a[0] if vertical else a[1]
            sign = (1 if nrm[0] > 0 else -1) if vertical else (1 if nrm[1] > 0 else -1)
            lo, hi = sorted((a[1], b[1]) if vertical else (a[0], b[0]))
            if end:
                backs = [(lo, hi, 0.0, "station")]
            else:
                backs = []
                for x_lo, x_hi, half in lines.get((axis, round(c, 6)), []):
                    x0, x1 = max(x_lo, lo), min(x_hi, hi)
                    if x1 - x0 > _EPS:
                        backs.append((x0, x1, half, "wall"))
            for x0, x1, off, kind in backs:
                kg, kf = (w.pgap, w.pface) if kind == "wall" else (gap, face)   # 칸막이벽은 칸막이벽 전용 거리
                if vertical:                                     # 측벽 내공면에 닿는 끝은 넓혀서 띠에서 끝나게
                    if on_inner_face(cfg, n, (c, x0), (c, x0)):
                        x0 = -T.BIG
                    if on_inner_face(cfg, n, (c, x1), (c, x1)):
                        x1 = T.BIG
                d0, d1 = sorted((c + sign * (off + kg), c + sign * (off + kf)))
                r = T.rect(x0, x1, d0, d1) if axis == "s" else T.rect(d0, d1, x0, x1)
                strip = T.intersect(clear, [r])
                (primary if axis == "s" else secondary).extend((p, kind, axis, c) for p in strip)
                for depth, bucket in ((kg, gaps), (kf, face_regs)):
                    if depth > _EPS:
                        e0, e1 = sorted((c + sign * off, c + sign * (off + depth)))
                        rr = T.rect(x0, x1, e0, e1) if axis == "s" else T.rect(e0, e1, x0, x1)
                        bucket += T.intersect(clear, [rr])
        prim_regs = [x[0] for x in primary]
        pieces = []
        wall_ops = ctx["wall_ops"]
        for group, cut_by in ((primary, []), (secondary, prim_regs)):
            for item in group:
                p = item[0]
                for q in T.subtract(T.subtract(T.subtract([p], obstacles), gaps), cut_by) if (obstacles or gaps or cut_by) else [p]:
                    for zt, zb in zones:
                        for zz in T.intersect([q], [zt]):
                            z0 = zb + ft.ffl + w.z0
                            z1 = wall_top if w.z1 is None else min(wall_top, zb + ft.ffl + w.z1)
                            if wall_top <= z0 + _EPS:
                                raise ValueError(f"실 {room.name}: 벽 마감 높이가 0 이하입니다 (바닥 마감 높이·걸레받이 높이·천장 높이 확인)")
                            if item[1] == "side":                    # 측벽: 본체 측벽 오프닝 (출구통로·환기구)
                                side = item[2]
                                holes = [x for o in wall_ops if o[1] == n and o[2] == side for x in room_wall_holes(cfg, o, w.skirt)]
                                pieces += _cut_s_holes(zz, z0, z1, holes)
                                continue
                            _, kind, axis, c = item
                            holes = []
                            for d in ctx["doors"]:
                                o = d.opening
                                across = (o[2], o[3]) if axis == "s" else (o[0], o[1])
                                if across[0] - _EPS <= c <= across[1] + _EPS:
                                    holes.append(((o[0], o[1]) if axis == "s" else (o[2], o[3])) + (o[4], o[5]))
                            if T.is_rect(zz):
                                pieces += _cut_holes((*T.bbox(zz), z0, z1), axis, holes)
                            elif axis == "s":
                                pieces += _cut_s_holes(zz, z0, z1, holes)
                            else:
                                pieces.append(_out(zz, z0, z1))

        # ---- 기둥 둘레 · 승강로 바깥면
        wall_regs = list(ctx["walls_t"]) + [piece_region(x) for x in pieces]
        rings = []
        for fn, s, t, hs, ht, rad in ctx["columns"]:
            if fn != n or not room.contains(s, t):
                continue
            zb = next((z for p0, p1, z in ctx["zones"] if p0 - _EPS <= t <= p1 + _EPS), None)
            if zb is None:
                continue
            if rad is None:
                rings.append(((s - hs, s + hs, t - ht, t + ht), zb, []))
            else:
                z1 = wall_top if w.z1 is None else min(wall_top, zb + ft.ffl + w.z1)
                rings_out += _circle_ring(cfg, s, t, rad + gap, face - gap, zb + ft.ffl + w.z0, z1)
        for ev in ctx["evs"]:
            S0, S1, T0, T1 = ev.outer_rect()
            if not room.contains((S0 + S1) / 2.0, (T0 + T1) / 2.0):
                continue
            zb = next((z for p0, p1, z in ctx["zones"] if p0 - _EPS <= (T0 + T1) / 2.0 <= p1 + _EPS), None)
            if zb is None:
                continue
            base_abs = cfg.lv(ev.spec.s_center) - st.offset
            if ev.spec.shaft == "glass":
                continue                                          # 투시형: 유리·금속 패널이 마감
            holes = [(rect, z0 - base_abs, z1 - base_abs) for _, _, fnum, rect, z0, z1 in ev.door_openings if fnum == n]
            rings.append(((S0, S1, T0, T1), zb, holes))
        col_rects = ctx["col_rects"]
        for rect, zb, door_holes in rings:
            z0 = zb + ft.ffl + w.z0
            z1 = wall_top if w.z1 is None else min(wall_top, zb + ft.ffl + w.z1)
            face_regs.append(T.rect(*_grow(rect, face)))
            for r, axis, sign, c in _ring_rects(_grow(rect, gap), face - gap):
                others = wall_regs + T.from_rects([x for x in col_rects if x != rect])
                for rr in T.intersect(clear, T.subtract([T.rect(*r)], others) if others else [T.rect(*r)]):
                    holes = []
                    for (a0, a1, b0, b1), h0, h1 in door_holes:
                        across = (b0, b1) if axis == "s" else (a0, a1)
                        if across[0] - gap - _EPS <= c <= across[1] + gap + _EPS:   # 마감은 벽면에서 이격(gap)만큼 떨어져 있음
                            holes.append(((a0, a1) if axis == "s" else (b0, b1)) + (h0, h1))
                    if T.is_rect(rr):
                        columns_out += _cut_holes((*T.bbox(rr), z0, z1), axis, holes)
                    else:
                        columns_out.append(_out(rr, z0, z1))
        return pieces, columns_out, rings_out, face_regs

    face_regs = []
    if f > _EPS:
        rf.walls, rf.columns, rf.rings, face_regs = wall_pass(ft.panel_pass())
        if ft.has_skirt:
            sw, sc, rf.skirt_rings, _ = wall_pass(ft.skirt_pass())
            rf.skirts = sw + sc

    # ---- 천장 · 천장틀
    if ft.ceiling:
        c = rf.ceiling_rel
        area = [p for zt, _ in zones for p in T.intersect(region, [zt])]
        holes = obstacles + T.from_rects(ctx["above"] + ctx.get("lining_fp", [])) + face_regs
        area = T.subtract(area, holes) if holes else T.merge(area)
        rf.ceiling = [_out(p, c, c + ft.board_t) for p in area]
        zb0, zb1 = c + ft.board_t, c + ft.board_t + ft.bar_h
        zc1 = zb1 + ft.carrier_h
        for p in area:
            s0, s1, t0, t1 = T.bbox(p)
            for s in _grid(s0, s1, ft.bar_spacing):
                for q in T.intersect([p], [T.rect(s - ft.bar_w / 2.0, s + ft.bar_w / 2.0, t0, t1)]):
                    rf.bars.append(_out(q, zb0, zb1))
            for t in _grid(t0, t1, ft.carrier_spacing):
                for q in T.intersect([p], [T.rect(s0, s1, t - ft.carrier_w / 2.0, t + ft.carrier_w / 2.0)]):
                    rf.carriers.append(_out(q, zb1, zc1))
