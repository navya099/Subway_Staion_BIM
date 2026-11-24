"""비품 겹침 검사 · 벽 붙임 (정거장 로컬 (s, t, FL 기준 높이) 의 볼록 각기둥끼리 — 평면 분리축 + 높이 구간).

막는 것(오류): 칸막이벽·문(닫힌 상태)·벽 마감·기둥·계단·에스컬레이터·승강로·유리난간·스크린도어·제연경계벽·사인·천장판·천장 기구와 겹침,
내공 밖, 바닥에 놓는 비품이 바닥 오프닝 위·승강장 끝에 걸침·실 밖, 비품끼리 겹침. 벽 부착은 가까운 벽 마감 표면을 못 찾으면 오류.
"""
import math

from helper import prism_member as PM

TOL = 1e-3
SNAP = 0.5                       # 벽 부착: 고른 점에서 이 거리 안의 벽 면에 붙음

FIXTURE = "천장 기구 "             # 장애물 이름 앞머리 (매달림 사인 행거가 피함)


def length_text(d: float) -> str:
    """겹친 길이 (1cm 미만은 mm)"""
    return f"{d * 1000:.0f}mm" if d < 0.01 else f"{d:.2f}m"


def rect(s0, s1, t0, t1) -> list:
    return [(s0, t0), (s1, t0), (s1, t1), (s0, t1)]


def circle(s, t, r, n=16) -> list:
    R = r / math.cos(math.pi / n)
    return [(s + R * math.cos(2 * math.pi * k / n), t + R * math.sin(2 * math.pi * k / n)) for k in range(n)]


def depth(a, b) -> float:
    """두 볼록 다각형의 겹침 깊이 (떨어져 있으면 ≤ 0)"""
    best = math.inf
    for poly in (a, b):
        for p, q in zip(poly, poly[1:] + poly[:1]):
            nx, ny = q[1] - p[1], p[0] - q[0]
            n = math.hypot(nx, ny)
            if n < 1e-12:
                continue
            nx, ny = nx / n, ny / n
            pa = [x * nx + y * ny for x, y in a]
            pb = [x * nx + y * ny for x, y in b]
            best = min(best, max(pa) - min(pb), max(pb) - min(pa))
            if best <= 0:
                return best
    return best


class Obstacles:
    """모델 부재의 (이름, 다각형, z0, z1) 목록 — 높이는 FL 기준"""

    def __init__(self, engine):
        self.cfg = cfg = engine.cfg
        self.items = []
        off = cfg.station.offset

        def piece(name, p):
            s0, s1 = PM.s_range(p)
            tr = getattr(p, "trap", None)
            poly = rect(s0, s1, *PM.t_range(p)) if not tr else [(s0, tr[0]), (s1, tr[2]), (s1, tr[3]), (s0, tr[1])]
            zs = [z - (cfg.lv(s) - off) for s in (s0, s1) for z in PM.z_range_at(cfg, p, s)]
            self.add(name, poly, min(zs), max(zs))

        def strip(name, st, t):
            zs = [z - (cfg.lv(s) - off) for s, z in ((st.s0, st.zb0), (st.s1, st.zb1), (st.s0, st.zt), (st.s1, st.zt_end))]
            self.add(name, rect(st.s0, st.s1, *t), min(zs), max(zs))
        for pw in engine.rooms.partitions:
            for p in pw.pieces:
                piece(f"칸막이벽 {pw.name}", p)
        for d in engine.rooms.doors:
            for p in d.parts:
                if p.code != "SILL":
                    piece(f"문 {d.name}", p.piece)
        for e in engine.finishes.all_elements():
            if e.code in ("WALL", "COLUMN", "SKIRT", "CEILING"):
                for p in e.pieces:
                    piece(f"마감 {e.name}", p)
        for fn, s, t, hs, ht, r in engine.finishes._columns(engine.columns):
            z0 = cfg.station.floor_level(fn)
            z1 = z0 + cfg.station.floor_heights[fn - 1]
            from finishes.finish_clear import room_finish_at
            ft = room_finish_at(cfg, fn, s, t)
            f = ft.face if ft is not None and ft.wall_t > 1e-9 else 0.0
            self.add(f"기둥 ({cfg.station.level_name(fn)})", circle(s, t, r + f) if r is not None else rect(s - hs - f, s + hs + f, t - ht - f, t + ht + f), z0, z1)
        for lay in cfg.stair_layouts():
            for part in lay.parts:
                for st in part.strips:
                    strip(f"계단 {lay.name}", st, getattr(part, "t_range", None) or lay.t_range)
            for f in lay.finish or []:
                for st in f.strips:
                    strip(f"계단 {lay.name}", st, f.t_range)
        for lay in cfg.escalator_layouts():
            for part in lay.parts:
                for st in part.strips:
                    strip(f"에스컬레이터 {lay.name}", st, getattr(part, "t_range", None) or lay.t_range)
            for x in lay.bollards:
                self.add(f"에스컬레이터 {lay.name} 볼라드", circle(x.s, x.t, lay.spec.bollard_d / 2), x.z0, x.z0 + lay.spec.bollard_h)
        for ev in cfg.elevator_layouts():
            self.add(f"엘리베이터 {ev.name}", rect(*ev.outer_rect()), cfg.station.floor_level(ev.lower_floor) - 1.0,
                     cfg.station.floor_level(ev.upper_floor) + cfg.station.floor_heights[ev.upper_floor - 1])
        for nm, els in (("유리난간", getattr(engine.railings, "railings", [])), ("스크린도어", engine.psds.elements), ("사인", engine.signs.elements)):
            for e in els:
                for part in getattr(e, "parts", None) or [e]:
                    for p in part.pieces:
                        piece(f"{nm} {e.name}", p)
        for e in engine.smokes.elements:
            for p in e.pieces:
                piece(f"제연경계벽 {e.name}", p)
        for e in engine.fixtures.elements:
            piece(f"{FIXTURE}{e.name}", e.face)

    def add(self, name, poly, z0, z1):
        ss, ts = [p[0] for p in poly], [p[1] for p in poly]
        self.items.append((name, poly, z0, z1, (min(ss), max(ss), min(ts), max(ts))))

    def hit(self, poly, z0, z1, skip=()):
        """겹치는 첫 부재 (이름, 깊이) 또는 None"""
        ss, ts = [p[0] for p in poly], [p[1] for p in poly]
        b = (min(ss), max(ss), min(ts), max(ts))
        for name, q, a0, a1, bb in self.items:
            if bb[0] > b[1] - TOL or bb[1] < b[0] + TOL or bb[2] > b[3] - TOL or bb[3] < b[2] + TOL:
                continue
            h = min(z1, a1) - max(z0, a0)
            if h <= TOL or name in skip:
                continue
            d = depth(poly, q)
            if d > TOL:
                return name, min(d, h)
        return None


def wall_faces(engine, z: float) -> list:
    """높이 z(FL 기준)를 지나는 연직 벽 면 [(사각형, 법선 (ns, nt))]: 벽·기둥 마감, 칸막이벽 (사각 조각만)"""
    cfg = engine.cfg
    out = []

    def add(p):
        if getattr(p, "trap", None):
            return
        s0, s1 = PM.s_range(p)
        t0, t1 = PM.t_range(p)
        m = (s0 + s1) / 2.0
        zs = [v - (cfg.lv(m) - cfg.station.offset) for v in PM.z_range_at(cfg, p, m)]
        if zs[0] <= z <= zs[1]:
            out.extend([((s0, s1, t0, t1), n) for n in ((0, -1), (0, 1), (-1, 0), (1, 0))])
    for e in engine.finishes.all_elements():
        if e.code in ("WALL", "COLUMN"):
            for p in e.pieces:
                add(p)
    for pw in engine.rooms.partitions:
        for p in pw.pieces:
            add(p)
    return out


def snap_to_wall(engine, floor: int, s: float, t: float, z: float):
    """고른 점에서 SNAP 안의 가장 가까운 벽 면 → (s, t, 앞면 방향 각도) 또는 None. 마감이 없으면 본체 벽 내공면(확폭은 그 자리 값)"""
    from config.widening import inner_at
    cfg = engine.cfg
    L = cfg.station.length
    best = None
    body = [((0.0, L, inner_at(cfg, floor, 1, s), 1e3), (0, -1)), ((0.0, L, -1e3, -inner_at(cfg, floor, -1, s)), (0, 1)),
            ((-1e3, 0.0, -1e3, 1e3), (1, 0)), ((L, 1e3, -1e3, 1e3), (-1, 0))]
    for (s0, s1, t0, t1), (ns, nt) in wall_faces(engine, z) + body:
        if nt:
            if not s0 - 1e-6 <= s <= s1 + 1e-6:
                continue
            c = t0 if nt < 0 else t1
            d = (t - c) * nt
            pos = (s, c)
        else:
            if not t0 - 1e-6 <= t <= t1 + 1e-6:
                continue
            c = s0 if ns < 0 else s1
            d = (s - c) * ns
            pos = (c, t)
        if -0.02 <= d <= SNAP and (best is None or d < best[0] - 1e-9):
            best = (d, pos, math.degrees(math.atan2(nt, ns)) % 360.0)
    return None if best is None else (*best[1], best[2])
