"""천장 기구 배치 (매입 평판 조명 0.3×1.2 · 사각 디퓨저 0.6×0.6): 실 천장판 영역에 천장판 격자(0.6, 정거장 s·t 원점)에 맞춰 자동 배치.

- 천장판 영역의 맞닿은 덩어리마다: 간격(FinishType.light_s × light_t, diff_gap)에 가깝게 고르게 나눈 자리를 격자에 맞춤
- 조명 긴 방향 = 덩어리의 긴 방향. 진행방향(s)으로 놓이면 s 로 두 칸, t 로는 칸 가운데 / t 로 놓이면 그 반대
- 디퓨저는 한 칸 전체. 조명·벽·막힌 자리와 겹치면 가까운 빈 칸으로 옮기고, 없으면 뺌
- 기구 둘레 EDGE 만큼 천장판 영역 안이어야 함 (벽 마감 표면·오프닝에서 띄움). 막힌 자리 = 원기둥 둘레 마감, 입구 제연경계벽
"""
from helper import trap_region as T

CELL = 0.6                       # 천장판 격자
LIGHT_W, LIGHT_L = 0.3, 1.2      # 조명 폭 × 길이
DIFF = 0.6                       # 디퓨저 한 변
EDGE = 0.1                       # 천장판 영역 끝에서 띄움
DEPTH = {"LIGHT": 0.08, "DIFFUSER": 0.1}        # 천장판 하면 위 몸체 높이 (위 슬래브 하면까지로 제한)
FACE = {"LIGHT": 0.004, "DIFFUSER": 0.01}       # 천장판 하면 아래로 나온 면 두께
_EPS = 1e-6


def spread(lo: float, hi: float, gap: float) -> list:
    """[lo, hi] 를 gap 에 가장 가까운 칸 수로 고르게 나눈 칸 가운데"""
    n = max(1, int((hi - lo) / gap + 0.5))
    return [lo + (hi - lo) * (i + 0.5) / n for i in range(n)]


def _edge(x: float) -> float:
    return round(x / CELL) * CELL


def _mid(x: float) -> float:
    import math
    return (math.floor(x / CELL) + 0.5) * CELL


def _uniq(xs):
    out = []
    for x in xs:
        if not out or abs(out[-1] - x) > _EPS:
            out.append(x)
    return out


def _hit(a, b, tol=_EPS) -> bool:
    return min(a[1], b[1]) - max(a[0], b[0]) > tol and min(a[3], b[3]) - max(a[2], b[2]) > tol


class _Region:
    """천장판 덩어리 (서로 겹치지 않는 사다리꼴 조각들)"""

    def __init__(self, pieces):
        self.pieces = pieces
        self.boxes = [T.bbox(p) for p in pieces]
        self.s0, self.s1 = min(b[0] for b in self.boxes), max(b[1] for b in self.boxes)
        self.t0, self.t1 = min(b[2] for b in self.boxes), max(b[3] for b in self.boxes)

    def covers(self, r, grow=EDGE) -> bool:
        q = (r[0] - grow, r[1] + grow, r[2] - grow, r[3] + grow)
        want = (q[1] - q[0]) * (q[3] - q[2])
        got = 0.0
        for p, b in zip(self.pieces, self.boxes):
            if not _hit(q, b):
                continue
            if T.is_rect(p):
                got += (min(q[1], b[1]) - max(q[0], b[0])) * (min(q[3], b[3]) - max(q[2], b[2]))
            else:
                got += T.area(T.intersect([T.rect(*q)], [p]))
        return got >= want - 1e-6


def _sym_mid(x: float) -> float:
    """중심선(0)이 칸 가운데인 격자의 칸 가운데 (좌우 대칭)"""
    import math
    return math.copysign(math.floor(abs(x) / CELL + 0.5) * CELL, x) + 0.0


def layout_fixtures(ft, pieces: list, blocked: list, centered: bool = False) -> tuple:
    """(조명 [(s0, s1, t0, t1, 긴 방향 's'|'t')], 디퓨저 [(s0, s1, t0, t1)]).
    ft = FinishType (light_s·light_t·diff_gap, 0 = 없음), pieces = 천장판 사다리꼴 조각, blocked = 막힌 평면 사각형.
    centered (통로·출입구): 조명 긴 방향은 늘 s, t 격자는 중심선이 칸 가운데 (좌우 대칭)"""
    lights, diffs = [], []
    if not pieces or not (ft.has_light or ft.has_diffuser):
        return lights, diffs
    for g in T.groups(list(pieces)):
        reg = _Region(g)
        free = lambda r: reg.covers(r) and not any(_hit(r, b) for b in blocked)
        if ft.has_light:
            along = "s" if centered or reg.s1 - reg.s0 >= reg.t1 - reg.t0 else "t"
            h_s, h_t = (LIGHT_L / 2, LIGHT_W / 2) if along == "s" else (LIGHT_W / 2, LIGHT_L / 2)
            snap_s, snap_t = (_edge, _sym_mid if centered else _mid) if along == "s" else (_mid, _edge)
            for s in _uniq([snap_s(x) for x in spread(reg.s0, reg.s1, ft.light_s)]):
                for t in _uniq([snap_t(x) for x in spread(reg.t0, reg.t1, ft.light_t)]):
                    r = (s - h_s, s + h_s, t - h_t, t + h_t)
                    if free(r) and not any(_hit(r, x) for x in lights if x[1] > r[0] and x[0] < r[1]):
                        lights.append((*r, along))
        if ft.has_diffuser:
            reach = int(ft.diff_gap / 2 / CELL)
            steps = sorted(((i, j) for i in range(-reach, reach + 1) for j in range(-reach, reach + 1)), key=lambda q: (q[0] ** 2 + q[1] ** 2, q))
            for s in _uniq([_mid(x) for x in spread(reg.s0, reg.s1, ft.diff_gap)]):
                near = [x for x in lights if x[1] > s - ft.diff_gap and x[0] < s + ft.diff_gap]
                for t in _uniq([(_sym_mid if centered else _mid)(x) for x in spread(reg.t0, reg.t1, ft.diff_gap)]):
                    for i, j in steps:
                        c, d = s + i * CELL, t + j * CELL
                        r = (c - DIFF / 2, c + DIFF / 2, d - DIFF / 2, d + DIFF / 2)
                        if any(_hit(r, x) for x in near) or any(_hit(r, x) for x in diffs if abs(x[0] - r[0]) < 2 * ft.diff_gap):
                            continue
                        if free(r):
                            diffs.append(r)
                            break
    return lights, diffs
