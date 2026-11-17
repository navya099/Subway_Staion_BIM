"""점자블록 배치: 층마다 서로 겹치지 않는 평면 사각형 (s0, s1, t0, t1) + 종류(점형/선형) + 놓이는 바닥 높이.

- 자동 점형: 승강장 연단(최하층), 계단·에스컬레이터 아래층 시작 앞·위층 도착 뒤, 엘리베이터 정지층 문 앞
- 유도 경로: 꼭짓점마다 점형 정사각형(폭 × 폭), 꼭짓점 사이는 선형 띠 (점형 정사각형 사이)
- 겹침: 점형이 선형보다 우선, 같은 종류는 먼저 놓인 것 우선 (서로 빼서 겹치지 않게)
- 기준 바닥: 그 층 FL, 최하층은 승강장 슬래브 위(t 범위)만 + 승강장 상면 (선로부에는 놓지 않음)
- 빼는 것: 칸막이벽·구획분리 벽, 사각 기둥, 그 층을 지나는 승강로, 그 층에서 오르는 계단·에스컬레이터 평면, 아래 슬래브 오프닝
높이(z)는 여기서 정하지 않는다: 바닥 마감이 있으면 그 마감재를 대체(finish_layout), 없으면 기준 바닥 위 block_t (엔진).
"""
import math
from dataclasses import dataclass

from openings import decompose
from tactiles.tactile_spec import GUIDE, WARNING

_EPS = 1e-6


@dataclass
class TactileBlock:
    floor: int
    kind: str                    # WARNING | GUIDE
    rect: tuple                  # (s0, s1, t0, t1) 정거장 로컬
    base: float                  # 놓이는 바닥 높이 (본체 FL 기준: 층 FL 또는 승강장 상면)
    source: str                  # 출처 (EDGE, 계단·에스컬레이터·엘리베이터·경로 이름)


def _inter(a, b):
    r = (max(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), min(a[3], b[3]))
    return r if r[1] - r[0] > _EPS and r[3] - r[2] > _EPS else None


def minus(rects, holes):
    """사각형들에서 구멍들을 뺀 조각"""
    out = []
    for r in rects:
        hs = [h for h in (_inter(r, h) for h in holes) if h]
        out += decompose.subtract_rects(r, hs) if hs else [tuple(r)]
    return [r for r in out if r[1] - r[0] > _EPS and r[3] - r[2] > _EPS]


def _srect(s_a, s_b, t0, t1):
    return (min(s_a, s_b), max(s_a, s_b), t0, t1)


def zones(cfg, n: int) -> list:
    """층 n 의 기준 바닥 [(t0, t1, 바닥 높이)] (최하층 승강장이 있으면 승강장 슬래브 위만)"""
    st, pl = cfg.station, cfg.platform
    hw = st.width / 2.0
    if n == 1 and pl.exists:
        return [(p0, p1, pl.top_level) for p0, p1 in pl.slab_t_ranges(st.width)]
    return [(-hw, hw, st.floor_level(n))]


def path_name(k: int, spec) -> str:
    return spec.name.strip() if spec.name.strip() else f"TP{k}"


def path_blocks(spec, size: float) -> list:
    """유도 경로 → [(종류, 사각형)]: 꼭짓점 점형 정사각형 + 사이 선형 띠"""
    w = spec.width if spec.width is not None else size
    h = w / 2.0
    pts = [(float(s), float(t)) for s, t in spec.points]
    out = [(WARNING, (s - h, s + h, t - h, t + h)) for s, t in pts]
    for (sa, ta), (sb, tb) in zip(pts, pts[1:]):
        if abs(ta - tb) < _EPS:                      # s 방향 선분
            lo, hi = min(sa, sb) + h, max(sa, sb) - h
            if hi - lo > _EPS:
                out.append((GUIDE, (lo, hi, ta - h, ta + h)))
        else:                                        # t 방향 선분
            lo, hi = min(ta, tb) + h, max(ta, tb) - h
            if hi - lo > _EPS:
                out.append((GUIDE, (sa - h, sa + h, lo, hi)))
    return out


def _auto_blocks(cfg, ts, n: int, stairs, escs, evs) -> list:
    """층 n 의 자동 점형 [(출처, 사각형)]"""
    st, pl = cfg.station, cfg.platform
    out = []
    if ts.edge and n == 1 and pl.exists:
        edge = pl.track_spacing / 2.0 + pl.plat_offset           # 선로 쪽 끝단 |t|
        a, b = edge + ts.edge_offset, edge + ts.edge_offset + ts.edge_width
        out += [("EDGE", (0.0, st.length, -b, -a)), ("EDGE", (0.0, st.length, a, b))]
    if ts.stair:
        for lay in stairs:
            c, d = ts.stair_clear, ts.stair_depth
            if lay.lower_floor == n:                              # 첫 챌판 앞
                out.append((lay.name, _srect(lay.s_at(-c), lay.s_at(-c - d), *lay.t_range)))
            if lay.lower_floor + 1 == n:                          # 위층 도착 지점 뒤
                out.append((lay.name, _srect(lay.s_at(lay.length + c), lay.s_at(lay.length + c + d), *lay.t_range)))
    if ts.escalator:
        for lay in escs:
            c, d = ts.esc_clear, ts.esc_depth
            u0, u1 = lay.u_range
            if lay.lower_floor == n:
                out.append((lay.name, _srect(lay.s_at(u0 - c), lay.s_at(u0 - c - d), *lay.t_range)))
            if lay.lower_floor + 1 == n:
                out.append((lay.name, _srect(lay.s_at(u1 + c), lay.s_at(u1 + c + d), *lay.t_range)))
    if ts.elevator:
        for lay in evs:
            sp = lay.spec
            if not sp.lower_floor <= n <= sp.upper_floor:
                continue
            s0, s1, t0, t1 = lay.outer_rect()
            c, d, half = ts.ev_clear, ts.ev_depth, sp.door_w / 2.0 + ts.size
            sides = [sp.door_side] + ([{"+": "-", "-": "+"}[sp.door_side[0]] + sp.door_side[1]] if sp.through else [])
            for side in sides:
                if side == "+s":
                    r = (s1 + c, s1 + c + d, sp.t_center - half, sp.t_center + half)
                elif side == "-s":
                    r = (s0 - c - d, s0 - c, sp.t_center - half, sp.t_center + half)
                elif side == "+t":
                    r = (sp.s_center - half, sp.s_center + half, t1 + c, t1 + c + d)
                else:
                    r = (sp.s_center - half, sp.s_center + half, t0 - c - d, t0 - c)
                out.append((lay.name, r))
    return out


def layout_tactile(cfg, columns=()) -> list:
    """TactileBlock 목록 (층마다 서로 겹치지 않음). columns: [(층, s, t, 반폭 s, 반폭 t, 반지름|None)] — 사각 기둥만 뺌"""
    ts = getattr(cfg, "tactile_settings", None)
    if ts is None or not ts.enabled:
        return []
    st = cfg.station
    L = st.length
    rooms = {fl.floor: fl for fl in cfg.room_layouts()}
    openings = cfg.all_openings()
    stairs, escs, evs = list(cfg.stair_layouts()), list(cfg.escalator_layouts()), list(cfg.elevator_layouts())
    out = []
    for n in range(1, st.floors + 1):
        warn = _auto_blocks(cfg, ts, n, stairs, escs, evs)
        guide = []
        for k, sp in enumerate(ts.paths, start=1):
            if sp.floor != n:
                continue
            for kind, r in path_blocks(sp, ts.size):
                (warn if kind == WARNING else guide).append((path_name(k, sp), r))
        if not warn and not guide:
            continue
        fl = rooms.get(n)
        holes = [p[:4] for pw in (fl.partitions if fl else []) for p in pw.pieces]
        holes += [(s - hs, s + hs, t - ht, t + ht) for fn, s, t, hs, ht, r in columns if fn == n and r is None]
        holes += [ev.outer_rect() for ev in evs if ev.lower_floor <= n <= ev.upper_floor]
        holes += [(*x.s_range, *x.t_range) for x in stairs + escs if x.lower_floor == n]
        holes += [(o.s_start, o.s_end, o.t_lo, o.t_hi) for o in openings if n - 1 in o.slabs]
        placed = []                                       # 이미 놓은 사각형 (뒤에 오는 블록에서 뺌)
        for kind, items in ((WARNING, warn), (GUIDE, guide)):
            for src, r in items:
                for t0, t1, base in zones(cfg, n):
                    zr = _inter(r, (0.0, L, t0, t1))
                    if zr is None:
                        continue
                    for piece in minus([zr], holes + placed):
                        out.append(TactileBlock(n, kind, piece, base, src))
                        placed.append(piece)
    return out


def check_tactile(cfg):
    """점자블록 입력 검사 (ValueError). 경로: 층·꼭짓점·s/t 방향 선분·내공(최하층은 승강장 위) 범위"""
    ts = getattr(cfg, "tactile_settings", None)
    if ts is None or not ts.enabled:
        return
    for label, v, pos in (("블록 크기", ts.size, True), ("블록 두께", ts.block_t, True),
                          ("연단 이격", ts.edge_offset, False), ("연단 띠 폭", ts.edge_width, True),
                          ("계단 앞 이격", ts.stair_clear, False), ("계단 앞 띠 깊이", ts.stair_depth, True),
                          ("에스컬레이터 앞 이격", ts.esc_clear, False), ("에스컬레이터 앞 띠 깊이", ts.esc_depth, True),
                          ("엘리베이터 앞 이격", ts.ev_clear, False), ("엘리베이터 앞 띠 깊이", ts.ev_depth, True)):
        if not isinstance(v, (int, float)) or not math.isfinite(v) or (v <= 0 if pos else v < 0):
            raise ValueError(f"점자블록: {label}은(는) {'0보다 커야' if pos else '0 이상이어야'} 합니다 ({v})")
    st = cfg.station
    L, hw = st.length, st.width / 2.0
    names = set()
    for k, sp in enumerate(ts.paths, start=1):
        name = path_name(k, sp)
        where = f"유도블록 경로 {k}({name})"
        if name in names:
            raise ValueError(f"{where}: 이름이 중복됩니다")
        names.add(name)
        if not (isinstance(sp.floor, int) and 1 <= sp.floor <= st.floors):
            raise ValueError(f"{where}: 층 번호가 범위(1~{st.floors}) 밖입니다 ({sp.floor})")
        w = sp.width if sp.width is not None else ts.size
        if not isinstance(w, (int, float)) or not math.isfinite(w) or w <= 0:
            raise ValueError(f"{where}: 폭은 0보다 커야 합니다 ({w})")
        if len(sp.points) < 2:
            raise ValueError(f"{where}: 꼭짓점이 2개 이상이어야 합니다")
        for j, p in enumerate(sp.points, start=1):
            if len(p) != 2 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in p):
                raise ValueError(f"{where} 꼭짓점 {j}: 좌표가 숫자가 아닙니다 ({p})")
        h = w / 2.0
        zs = [(t0, t1) for t0, t1, _ in zones(cfg, sp.floor)]
        on_platform = sp.floor == 1 and cfg.platform.exists
        for j, ((sa, ta), (sb, tb)) in enumerate(zip(sp.points, sp.points[1:]), start=1):
            if abs(sa - sb) < _EPS and abs(ta - tb) < _EPS:
                raise ValueError(f"{where}: 꼭짓점 {j} 과 {j + 1} 이 같은 위치입니다")
            if abs(sa - sb) > _EPS and abs(ta - tb) > _EPS:
                raise ValueError(f"{where}: 선분 {j}–{j + 1} 이 선형 방향(s)이나 직각 방향(t)이 아닙니다 "
                                 "(유도블록 경로는 꺾어서 입력, 미리보기 선택은 직교 모드)")
            lo, hi = min(ta, tb) - h, max(ta, tb) + h
            if not any(t0 - 1e-3 <= lo and hi <= t1 + 1e-3 for t0, t1 in zs):
                raise ValueError(f"{where}: 선분 {j}–{j + 1} 이 " + ("승강장 위를 벗어납니다" if on_platform
                                                                    else "내공 폭을 벗어납니다"))
        for j, (s, t) in enumerate(sp.points, start=1):
            if not (-1e-3 <= s - h and s + h <= L + 1e-3):
                raise ValueError(f"{where} 꼭짓점 {j}: 내공 길이(0 ~ {L:g})를 벗어납니다 (s = {s:g})")
            if not -hw - 1e-3 <= t - h <= t + h <= hw + 1e-3:
                raise ValueError(f"{where} 꼭짓점 {j}: 내공 폭을 벗어납니다 (t = {t:g})")
