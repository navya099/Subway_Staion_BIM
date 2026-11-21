"""마감이 빠지던 곳 채우기: 계단·에스컬레이터 아래 바닥, 슬래브 오프닝 둘레.

1) 바닥 마감은 계단·에스컬레이터 평면 전체가 아니라 부재가 실제로 바닥 마감면 아래까지 내려오는 곳(접지 구간)만 뺀다
   (`contact_rects`). 계단 경사부 아래·트러스가 떠 있는 구간 바닥은 마감한다. 띠(strip)마다 하면 표고가 그 자리 바닥 마감면
   (선형 표고 + 시작면 + 마감 높이)보다 낮은 s 구간 × 부재 t 범위.
2) 슬래브 오프닝 둘레 (`opening_linings`, 천장이 있는 실만): 천장판이 오프닝 가장자리에서 끝나 천장 속(천장판 ~ 슬래브 하면)이
   보이므로 가장자리 바깥쪽에 마감 두께의 막이(천장판 하면 ~ 위 슬래브 하면)를, 오프닝 안쪽 슬래브 옆면에 마감
   (슬래브 하면 ~ 상면)을 댄다. 계단·에스컬레이터가 위층에 도착하는 쪽 가장자리는 부재가 슬래브에 맞닿으므로 두지 않고,
   옆면 마감은 부재 상면이 슬래브 하면보다 높은 s 구간에서 뺀다 (부재와 겹치지 않음). 승강로·피트 오프닝은 제외.
조각은 정거장 로컬 사각형 (s0, s1, t0, t1, z0, z1) — 높이는 본체 FL(z=0) 기준.
"""
from openings import decompose

_EPS = 1e-6


def _merge(iv):
    out = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1] + _EPS:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _sub(lo, hi, holes):
    out, cur = [], lo
    for a, b in _merge([(max(a, lo), min(b, hi)) for a, b in holes if min(b, hi) - max(a, lo) > _EPS]):
        if a > cur + _EPS:
            out.append((cur, a))
        cur = max(cur, b)
    if hi > cur + _EPS:
        out.append((cur, hi))
    return out


def _below(strip, f, cfg, off, ref, above=False):
    """띠 하면(above=False) 또는 상면(above=True) 이 기준면 ref(s) (= 선형 표고 − offset + off) 보다 낮은(높은) s 구간"""
    s0, s1 = strip.s0, strip.s1
    if s1 - s0 < _EPS:
        return []
    z = strip.zt_at if above else strip.zb_at
    d0 = z(s0) - (cfg.lv(s0) - off + ref)
    d1 = z(s1) - (cfg.lv(s1) - off + ref)
    if above:
        d0, d1 = -d0, -d1
    if d0 < f and d1 < f:
        return [(s0, s1)]
    if d0 >= f and d1 >= f:
        return []
    x = s0 + (s1 - s0) * (f - d0) / (d1 - d0)
    return [(s0, x)] if d0 < f else [(x, s1)]


def _parts(lay):
    """계단·에스컬레이터 배치 → [(띠 목록, t 범위)] (계단 마감 부재 포함)"""
    out = [(p.strips, getattr(p, "t_range", None) or lay.t_range) for p in lay.parts]
    return out + [(f.strips, f.t_range) for f in getattr(lay, "finish", None) or []]


def contact_rects(cfg, items, floor_n: int, ffl: float) -> list:
    """층 floor_n 에서 오르는 계단·에스컬레이터가 바닥 마감면(시작면 + ffl) 아래로 내려오는 평면 [(s0, s1, t0, t1)]"""
    off = cfg.station.offset
    out = []
    for lay in items:
        if lay.lower_floor != floor_n:
            continue
        ref = lay.base_level + ffl
        t0, t1 = lay.t_range                             # 부재(구조·계단 마감)마다 구간을 모아 계단 폭 전체로 합침
        iv = _merge([x for strips, _ in _parts(lay) for st in strips for x in _below(st, -1e-9, cfg, off, ref)])
        out += [(a, b, t0, t1) for a, b in iv if b - a > _EPS]
    return out


def opening_linings(cfg, floor_n: int, room, ft, ceiling_rel: float, openings: list, stairs: list, escalators: list,
                    skip: set, obstacles: list) -> tuple:
    """천장이 있는 실(room)의 위 슬래브(번호 floor_n) 오프닝 둘레 마감 → (조각 목록, 천장판에서 뺄 평면 사각형 목록).
    skip: 제외할 오프닝 이름 (승강로·피트), obstacles: 막이에서 뺄 평면 (벽·기둥·승강로)"""
    st = cfg.station
    f = ft.wall_t
    if not ft.ceiling or f <= _EPS:
        return [], []
    if floor_n >= st.floors:
        slab_top = st.height
    else:
        slab_top = st.floor_level(floor_n + 1)
    from rooms.room_layout import ceiling_rel as slab_bottom_of
    slab_bot = slab_bottom_of(st, floor_n)
    off = st.offset
    own = {}                                             # 오프닝 이름 → (도착 s, 부재 띠·t 범위)
    for lay in stairs:
        if lay.lower_floor == floor_n:
            own[lay.opening.name] = (lay.s_at(lay.length), _parts(lay))
    for lay in escalators:
        if lay.lower_floor == floor_n:
            own[lay.opening.name] = (lay.s_at(lay.u_range[1]), _parts(lay))
    pieces, footprint = [], []
    for o in openings:
        if floor_n not in o.slabs or o.name in skip:
            continue
        S0, S1, T0, T1 = o.s_start, o.s_end, o.t_lo, o.t_hi
        if not room.contains((S0 + S1) / 2.0, (T0 + T1) / 2.0):
            continue
        arrive, parts = own.get(o.name, (None, []))
        skip_s0 = arrive is not None and abs(arrive - S0) < abs(arrive - S1)
        skip_s1 = arrive is not None and not skip_s0
        # 가장자리 (축, 바깥 막이 사각형, 안쪽 옆면 사각형)
        # 본체 벽 마감 패널까지 넓힌 가장자리(계단 구간 벽 마감이 위층까지 이어짐)는 막이·옆면 없음 — 이슈 #32
        from finishes.finish_layout import shaft_walls
        walled = {x[2] for x in shaft_walls(cfg, floor_n, [o], stairs, escalators)}
        edges = []
        if -1 not in walled:
            edges.append(("s", (S0 - f, S1 + f, T0 - f, T0), (S0, S1, T0, T0 + f)))
        if 1 not in walled:
            edges.append(("s", (S0 - f, S1 + f, T1, T1 + f), (S0, S1, T1 - f, T1)))
        ta, tb = T0, T1                                      # 입구·끝 막이는 패널(오프닝 s 구간 안)과 s 로 맞닿아 겹치지 않음
        if not skip_s0:
            edges.append(("t", (S0 - f, S0, ta, tb), (S0, S0 + f, T0 + f, T1 - f)))
        if not skip_s1:
            edges.append(("t", (S1, S1 + f, ta, tb), (S1 - f, S1, T0 + f, T1 - f)))
        if skip_s0:                                      # 도착 쪽에는 막이도 옆면도 없음: s 방향 가장자리를 그 끝까지만
            edges = [(a, (max(r[0], S0), r[1], r[2], r[3]), (max(q[0], S0), q[1], q[2], q[3])) if a == "s" else (a, r, q)
                     for a, r, q in edges]
        if skip_s1:
            edges = [(a, (r[0], min(r[1], S1), r[2], r[3]), (q[0], min(q[1], S1), q[2], q[3])) if a == "s" else (a, r, q)
                     for a, r, q in edges]
        for axis, out_r, in_r in edges:
            # 바깥 막이: 천장판 하면 ~ 위 슬래브 하면 (실 안, 벽·기둥 등은 뺌)
            if slab_bot - ceiling_rel > _EPS:
                for r in _clip_room(room, decompose_minus([out_r], obstacles)):
                    pieces.append((*r, ceiling_rel, slab_bot))
                    footprint.append(r)
            # 안쪽 옆면: 슬래브 하면 ~ 상면, 부재 상면이 슬래브 하면보다 높은 s 구간은 뺌 (s 방향 가장자리만 해당)
            s0, s1, t0, t1 = in_r
            holes = []
            if axis == "s":
                for strips, (pt0, pt1) in parts:
                    if min(pt1, t1) - max(pt0, t0) <= _EPS:
                        continue
                    holes += [x for stp in strips for x in _below(stp, 0.0, cfg, off, slab_bot, above=True)]
            for a, b in (_sub(s0, s1, holes) if axis == "s" else [(s0, s1)]):
                if b - a > _EPS and t1 - t0 > _EPS:
                    pieces.append((a, b, t0, t1, slab_bot, slab_top))
    return pieces, footprint


def decompose_minus(rects, holes):
    out = []
    for r in rects:
        hs = [h for h in holes if min(r[1], h[1]) - max(r[0], h[0]) > _EPS and min(r[3], h[3]) - max(r[2], h[2]) > _EPS]
        out += decompose.subtract_rects(r, hs) if hs else [tuple(r)]
    return [r for r in out if r[1] - r[0] > _EPS and r[3] - r[2] > _EPS]


def _clip_room(room, rects):
    """실 영역(직사각형 조각) 안으로 자름 — 사다리꼴 실(확폭)은 외접 사각형 조각 기준"""
    out = []
    for r in rects:
        for q in room.rects:
            c = (max(r[0], q[0]), min(r[1], q[1]), max(r[2], q[2]), min(r[3], q[3]))
            if c[1] - c[0] > _EPS and c[3] - c[2] > _EPS:
                out.append(c)
    return out
