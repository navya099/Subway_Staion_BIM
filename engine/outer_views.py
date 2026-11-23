"""본체 밖 구조물(출입구 · 외부 엘리베이터 · 환기구 지상부 · 출구통로)의 평면도 · 본체 종단면도 표시.

부재의 3D 면(볼록 조각)을 그대로 써서 2D 윤곽을 만든다 (BIM 객체 = 단일 원천, 도면 코드가 기하를 다시 계산하지 않음).

평면도 (층마다, `plan_outer_items`): 구조물마다 그 층의 수평 절단면 z 를 정하고
- 절단면을 지나는 조각 = 수평 단면 다각형, 절단면 아래(아래층 절단면까지) 부분 = 위에서 본 윤곽. 아래층 절단면보다 낮은 부분은 그 아래층 평면에 나옴
  → 경사 출입구·승강로가 층마다 그 층 높이만큼 나뉘어 보임 (층 겹쳐 보기 없음)
- 붙은 층(통로·EV 문 층)의 절단면 = 그 구조물 바닥 + 절단 높이 (아래로 끝까지), 다른 층 = 그 측점 본체 FL + 층 높이 + 절단 높이
- 지상(층 번호 = 층수 + 1): 절단면 = 지표 + 절단 높이. 출입구 개구부·캐노피·앞마당, EV 유리 박스·기단·경사로, 환기구 지상 돌출 + 본체 외곽선
종단면도 (`profile_outer_items`): 모든 조각을 (s, 절대 표고)에 투영한 윤곽 (절단되지 않으므로 해치 없음), 왼쪽(+t)·오른쪽(−t)·양쪽·없음 선택.
"""
import math

import numpy as np

from config.widening import outer_polyline
from helper.box_piece import _convex_hull, polygon_area
from helper.strip_member import strip_faces
from helper.view_item import ViewItem

OUTER_BOTH, OUTER_LEFT, OUTER_RIGHT, OUTER_NONE = "both", "left", "right", "none"
OUTERS = (OUTER_BOTH, OUTER_LEFT, OUTER_RIGHT, OUTER_NONE)
_EPS = 1e-6


# ====================================================================== 조각 → 평면 윤곽
def _area(poly) -> float:
    """다각형 넓이 (세계 좌표가 커서 첫 점 기준 — 그대로 계산하면 1e-5 m² 쯤 틀림)"""
    x0, y0 = poly[0]
    return abs(polygon_area([(x - x0, y - y0) for x, y in poly])) if len(poly) >= 3 else 0.0


def level_polygon(faces, z: float):
    """볼록 조각을 표고 z 로 자른 평면 다각형 (없으면 None)"""
    return _slab_polygon(faces, z, z)


def _slab_polygon(faces, z0: float, z1: float):
    """볼록 조각의 z0 ~ z1 부분을 위에서 본 볼록 다각형 (없으면 None)"""
    pts = []
    for f in faces:
        for i in range(len(f)):
            p, q = f[i], f[(i + 1) % len(f)]
            if z0 - 1e-9 <= p[2] <= z1 + 1e-9:
                pts.append((p[0], p[1]))
            for z in (z0, z1):
                if (p[2] - z) * (q[2] - z) < 0:
                    k = (z - p[2]) / (q[2] - p[2])
                    pts.append((p[0] + (q[0] - p[0]) * k, p[1] + (q[1] - p[1]) * k))
    hull = _convex_hull(pts)
    return hull if len(hull) >= 3 and _area(hull) > 1e-7 else None


class Solid:
    """작도할 볼록 조각 1개. section = 절단면 작도, beyond = 절단면 아래 윤곽 작도, over = 절단면 위에 있어도 윤곽 (지붕 등)"""

    def __init__(self, name, layer, faces, section=True, beyond=True, over=False, merge=True):
        self.merge = merge                                        # 같은 부재의 맞닿은 조각을 합침
        self.name, self.layer, self.faces = name, layer, faces
        self.section, self.beyond, self.over = section, beyond, over
        zs = [p[2] for f in faces for p in f]
        self.z0, self.z1 = min(zs), max(zs)


def _strips(frame, part):
    return [strip_faces(frame, st, *part.t_range) for st in part.shape.strips]


# ====================================================================== 구조물 → 조각
def entrance_solids(ent) -> list:
    """출입구 평면 조각: 박스(버림·헌치 제외), 계단 디딤판(마감이면 계단석, 아니면 구조), 에스컬레이터 스텝·핸드레일, 캐노피"""
    from escalators.escalator_type import EscalatorPartKind as K
    fr, out = ent.frame, []
    for e in ent.elements:
        if e.kind == "LEAN" or e.code.startswith("LEAN"):
            continue
        layer = "PLAN_FINISH" if e.kind in ("PAVE", "LANDFIN", "ARCH") else "PLAN_PASSAGE"
        roof = e.code.startswith(("ROOF", "FLOOR"))                # 천장(아래가 안 보임)·계단/ESC 밑 바닥은 절단 단면만
        out += [Solid(e.name, layer, f, beyond=not roof) for f in _strips(fr, e)]
        if not roof:
            out += [Solid(e.name, layer, p.faces()) for p in e.pieces]
    st = ent.stair
    if st is not None:
        treads = [f for f in st.finishes if f.code in ("TREAD", "STONE")] or [f for f in st.finishes if f.code == "FILL"]
        for m in treads or list(st.parts):
            out += [Solid(m.name, "PLAN_STAIR", f, section=False, merge=False) for f in _strips(fr, m)]
    for esc in ent.escalators:
        for p in esc.parts:
            if p.kind in (K.HANDRAIL, K.FLOOR_PLATE):
                out += [Solid(p.name, "PLAN_ESCALATOR", f, section=False) for f in _strips(fr, p)]
        for s in esc.steps:
            out += [Solid(s.name, "PLAN_ESCALATOR", f, section=False, merge=False) for f in _strips(fr, s)]
    for c in ent.canopy:
        over = c.kind in ("CP_GLASS", "CP_BEAM")
        if c.kind != "CP_SIGN":
            out += [Solid(c.name, "PLAN_BEYOND" if over else "PLAN_PASSAGE", f, over=over) for f in _strips(fr, c)]
    return out


_EV_LAYER = {"PODIUM": "PLAN_FINISH", "RAMP": "PLAN_FINISH", "CURB": "PLAN_FINISH", "LOW_FLOOR": "PLAN_FINISH", "RAIL": "PLAN_RAILING"}


def ext_ev_solids(x) -> list:
    """외부 엘리베이터 평면 조각: 승강로·유리·기둥·문·카·기단·경사로 (사인·루버·지붕·보 제외, 캐노피는 윤곽)"""
    out = []
    for e in x.elements:
        if e.kind in ("SIGN", "SIGN_FACE", "LOUVER", "ROOF", "BEAM", "GIRT", "SPIDER"):
            continue
        over = e.kind == "CANOPY"
        layer = "PLAN_BEYOND" if over else _EV_LAYER.get(e.kind, "PLAN_ELEVATOR")
        low = e.kind in ("PODIUM", "RAMP", "CURB", "LOW_FLOOR", "RAIL", "CAR_FLOOR")
        for f in _strips(e.frame, e) + [p.faces() for p in e.pieces]:
            out.append(Solid(e.name, layer, f, beyond=low, over=over))
    return out


def vent_solids(vt) -> list:
    return [Solid(e.name, "PLAN_VENT", p.faces()) for e in vt.elements + vt.grills for p in e.pieces]


# ====================================================================== 지상
def ground_floor(cfg) -> int:
    """지상 평면의 층 번호 (= 층수 + 1)"""
    return cfg.station.floors + 1


def has_ground(cfg) -> bool:
    """지상에 나오는 구조물(출입구·외부 EV·수직구로 끝나는 환기구)이 있는가"""
    return bool(getattr(cfg, "entrances", None) or getattr(cfg, "ext_evs", None)
                or any(v.grill_at_shaft for v in cfg.vent_layouts()))


def floor_label(cfg, n: int) -> str:
    return "지상" if n == ground_floor(cfg) else cfg.station.level_name(n)


# ====================================================================== 평면도
def _objects(engine) -> list:
    """[(이름표, 조각 목록, 붙은 층, 바닥 표고, 지표 표고, 본체에 붙는 측점 s)]"""
    cfg, out = engine.cfg, []
    by_name = {p.name: p for p in cfg.passage_layouts()}
    for ent in engine.entrances.entrances:
        s0 = by_name[ent.passage].vertices[0].s if ent.passage in by_name else 0.0
        out.append((f"{ent.name} ENTRANCE", entrance_solids(ent), ent.floor, ent.layout.z_floor, ent.layout.ground, s0))
    for x in engine.ext_evs.ext_evs:
        c = x.layout
        s0 = cfg.to_station(*x.frame.to_world((c.outer[0] + c.outer[1]) / 2.0, (c.outer[2] + c.outer[3]) / 2.0))[0]
        out.append((f"{x.name} EV", ext_ev_solids(x), c.floor, x.stops[1], c.ground, s0))
    return out


def _cut_level(cfg, n: int, floor: int, z_floor: float, ground: float, s0: float, cut_h: float) -> float:
    """구조물의 층 n 절단면 표고"""
    st = cfg.station
    if n == ground_floor(cfg):
        return ground + cut_h
    if n == floor:
        return z_floor + cut_h
    return cfg.lv(min(max(s0, 0.0), st.length)) - st.offset + st.floor_level(n) + cut_h


def _cut_solids(solids, prev, z):
    """조각 목록 → [(Solid, 다각형, 절단 여부)] (절단면 z, 아래 한계 prev — None 이면 끝까지)"""
    lo = -1e9 if prev is None else prev
    out = []
    for so in solids:
        if so.over and so.z1 > z:
            poly = _slab_polygon(so.faces, so.z0, so.z1)
            if poly:
                out.append((so, poly, False))
            continue
        if so.z0 >= z - _EPS or so.z1 <= lo + _EPS:
            continue
        sec = level_polygon(so.faces, z) if so.section and so.z1 > z + _EPS else None
        if sec:
            out.append((so, sec, True))
        if so.beyond:
            poly = _slab_polygon(so.faces, max(lo, so.z0), min(z, so.z1))
            if poly and not (sec and abs(_area(poly) - _area(sec)) < 1e-6):
                out.append((so, poly, False))      # 절단 단면과 같은 윤곽(연직 벽)은 한 번만
    return _merge(out)


def _merge(cuts) -> list:
    """같은 부재에서 변을 맞대는 조각(띠 경계)은 한 다각형으로 — 합친 볼록 껍질의 면적이 두 넓이의 합(맞닿음) 또는 큰 쪽(포함)과 같을 때.
    디딤판·스텝(merge = False)은 나누어진 선이 도면 내용이라 그대로"""
    groups, out = {}, []
    for so, poly, cut in cuts:
        if so.merge:
            groups.setdefault((so.name, so.layer, cut), []).append((so, poly))
        else:
            out.append((so, poly, cut))
    for (_, _, cut), lst in groups.items():
        polys = [(so, poly, _area(poly)) for so, poly in lst]
        polys.sort(key=lambda x: (min(p[0] for p in x[1]), min(p[1] for p in x[1])))
        i = 0
        while i < len(polys):
            j = i + 1
            while j < len(polys):
                hull = _convex_hull(list(polys[i][1]) + list(polys[j][1]))
                a, ai, aj = _area(hull), polys[i][2], polys[j][2]
                if a <= max(ai, aj) + 1e-6 or abs(a - ai - aj) < 1e-6:
                    polys[i] = (polys[i][0], hull, a)
                    polys.pop(j)
                    j = i + 1                                      # 커졌으니 다시
                else:
                    j += 1
            i += 1
        out += [(so, poly, cut) for so, poly, _ in polys]
    return out


def plan_outer_items(engine, n: int, cut_h: float) -> list:
    """층 n(지상 = 층수 + 1) 평면도의 본체 밖 구조물 ViewItem (pts 는 세계 평면 좌표)"""
    cfg, items = engine.cfg, []
    ground = n == ground_floor(cfg)
    for label, solids, floor, z_floor, G, s0 in _objects(engine):
        if n < floor:
            continue
        z = _cut_level(cfg, n, floor, z_floor, G, s0, cut_h)
        prev = None if n == floor else _cut_level(cfg, n - 1, floor, z_floor, G, s0, cut_h)
        if not ground:                                             # 지표 위(지상부)는 지상 평면에만
            z = min(z, G - 0.05)
        elif prev is not None:
            prev = min(prev, G - 0.05)
        solids = solids if ground else [so for so in solids if not so.over]
        items += _items(_cut_solids(solids, prev, z), label)
    if ground:
        for vt in engine.vents.vents:
            if vt.grill_at_shaft:
                sol = vent_solids(vt)
                top = max(so.z1 for so in sol)
                spec = next(v for v in cfg.vent_layouts() if v.name == vt.name).spec
                G = cfg.station.ground_el if cfg.station.ground_el is not None else top - spec.protrusion
                items += _items(_cut_solids(sol, G - 0.3, G + cut_h), f"{vt.name} VENT")
    return items


def _items(cuts, label) -> list:
    items, lab = [], None
    if cuts:
        xs = [p for _, poly, _ in cuts for p in poly]
        lab = (label, (min(p[0] for p in xs) + max(p[0] for p in xs)) / 2.0, (min(p[1] for p in xs) + max(p[1] for p in xs)) / 2.0,
               0.5, "PLAN_TEXT")
    for so, poly, cut in cuts:
        items.append(ViewItem(so.name, so.layer, u0=min(p[0] for p in poly), u1=max(p[0] for p in poly), pts=poly, label=lab))
        lab = None
    return items


def body_outline_items(cfg) -> list:
    """지상 평면의 본체 외곽선 (최상층 측벽 바깥면 + 단부 벽, 정거장 (s, t))"""
    st = cfg.station
    n = st.floors
    w = st.wall_t_at(n)
    up = outer_polyline(cfg, n, 1, -w, st.length + w)
    dn = outer_polyline(cfg, n, -1, -w, st.length + w)
    ring = [(s, t) for s, t in up] + [(s, -t) for s, t in reversed(dn)]
    dense = []
    for (s0, t0), (s1, t1) in zip(ring, ring[1:] + ring[:1]):      # 곡선 선형이면 변을 표본 측점마다
        ss = cfg.sample_s(min(s0, s1), max(s0, s1)) if abs(s1 - s0) > _EPS else [s0, s1]
        if s1 < s0:
            ss = list(reversed(ss))
        for s in ss[:-1] if abs(s1 - s0) > _EPS else [s0]:
            k = 0.0 if abs(s1 - s0) < _EPS else (s - s0) / (s1 - s0)
            dense.append((s, t0 + (t1 - t0) * k))
    return [ViewItem("BODY_OUTLINE", "PLAN_BEYOND", u0=-w, u1=st.length + w, pts=dense)]


def to_plan_coords(cfg, items, world_mode: bool) -> list:
    """세계 좌표 ViewItem → 평면도 좌표 (전개 평면이면 (s, t))"""
    if world_mode:
        return items
    memo = {}

    def st(p):
        k = (round(p[0], 6), round(p[1], 6))
        if k not in memo:
            memo[k] = cfg.to_station(*p)
        return memo[k]
    out = []
    for it in items:
        pts = [st(p) for p in it.pts]
        lab = None if it.label is None else (it.label[0], *st(it.label[1:3]), *it.label[3:])
        out.append(ViewItem(it.name, it.layer, u0=min(p[0] for p in pts), u1=max(p[0] for p in pts), pts=pts, label=lab))
    return out


# ====================================================================== 종단면도
def _station_s(cfg, pts) -> np.ndarray:
    """세계 평면 점 → 정거장 s (표본 투영 근사 + 곡선이면 뉴턴 2회 — 선형에서 먼 점은 근사만으로 수 cm 틀림)"""
    from preview.preview_render import station_of
    a, base = cfg.align, cfg.station.start_station
    lo = max(a.start_station, base - 300.0) - base
    hi = min(a.end_station, base + cfg.station.length + 300.0) - base
    out = station_of(cfg, pts, lo, hi)
    if a.is_straight:
        return out
    memo = {}
    for i, (x, y) in enumerate(pts):
        key = (round(float(x), 5), round(float(y), 5))
        if key not in memo:
            s = float(out[i])
            for _ in range(2):
                s = min(max(s, lo), hi)
                cx, cy = cfg.to_world(s, 0.0)
                th = cfg.theta_at(s)
                du = (x - cx) * math.cos(th) + (y - cy) * math.sin(th)
                t = -(x - cx) * math.sin(th) + (y - cy) * math.cos(th)
                s += du / max(0.2, 1.0 - cfg.curvature_at(s) * t)
            memo[key] = s
        out[i] = memo[key]
    return out


def profile_outer_items(engine, sides: str = OUTER_BOTH) -> list:
    """본체 종단면도의 본체 밖 구조물 투영 윤곽 (u = s, v = 절대 표고). sides = both | left(+t) | right(−t) | none"""
    if sides not in OUTERS:
        raise ValueError(f"종단면도: 외부 구조물 투영은 {', '.join(OUTERS)} 중 하나여야 합니다 ({sides!r})")
    if sides == OUTER_NONE:
        return []
    from escalators.escalator_type import EscalatorPartKind as K
    cfg = engine.cfg
    by_name = {p.name: p for p in cfg.passage_layouts()}
    side_of = lambda t: 1 if t >= 0 else -1
    groups = []                                                    # (이름표, 쪽, [(부재 이름, 조각 면 목록)])
    psd = {ps.name: ps for ps in engine.passages.all_passages()}
    for name, lay in by_name.items():
        groups.append((f"{name} EXIT", side_of(lay.vertices[0].t), [(e.name, p.faces()) for e in psd[name].elements for p in e.pieces]))
    for ent in engine.entrances.entrances:
        mem = [(e.name, f) for e in ent.elements if not e.code.startswith("LEAN") for f in _strips(ent.frame, e) + [p.faces() for p in e.pieces]]
        mem += [(c.name, f) for c in ent.canopy if c.kind != "CP_SIGN" for f in _strips(ent.frame, c)]
        mem += [(p.name, f) for esc in ent.escalators for p in esc.parts if p.kind == K.TRUSS for f in _strips(ent.frame, p)]
        mem += [(p.name, f) for p in (ent.stair.parts if ent.stair is not None else []) for f in _strips(ent.frame, p)]
        groups.append((f"{ent.name} ENTRANCE", side_of(by_name[ent.passage].vertices[0].t), mem))
    for x in engine.ext_evs.ext_evs:
        c = x.layout.outer
        t = cfg.to_station(*x.frame.to_world((c[0] + c[1]) / 2.0, (c[2] + c[3]) / 2.0))[1]
        mem = [(e.name, f) for e in x.elements if e.kind not in ("SIGN", "SIGN_FACE", "SPIDER", "GIRT")
               for f in _strips(e.frame, e) + [p.faces() for p in e.pieces]]
        groups.append((f"{x.name} EV", side_of(t), mem))
    want = {OUTER_BOTH: (1, -1), OUTER_LEFT: (1,), OUTER_RIGHT: (-1,)}[sides]
    items = []
    for label, side, mem in groups:
        if side not in want or not mem:
            continue
        pts = np.array([p[:2] for _, f in mem for q in f for p in q], dtype=float)
        ss = _station_s(cfg, pts)
        i, top, left, first = 0, -1e9, 1e9, len(items)
        for name, f in mem:
            sz = []
            for q in f:
                for p in q:
                    sz.append((float(ss[i]), p[2]))
                    i += 1
            hull = _convex_hull(sz)
            if len(hull) >= 3 and _area(hull) > 1e-7:
                items.append(ViewItem(name, "PROF_OUTER", u0=min(p[0] for p in hull), u1=max(p[0] for p in hull), pts=hull))
                top, left = max(top, max(p[1] for p in hull)), min(left, min(p[0] for p in hull))
        if len(items) > first:
            items[first].label = (label + (" (L)" if side > 0 else " (R)"), left, top + 0.5, 0.6, "PROF_TEXT")
    return items
