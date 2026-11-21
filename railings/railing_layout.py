"""계단·에스컬레이터 오프닝 유리난간 배치 (정거장 로컬 사각 조각 → 엔진이 선형 각기둥으로).

- 대상: 계단(항상)·에스컬레이터(RailingSettings.escalators) 자동 오프닝. 난간은 위층(오프닝 슬래브 k → k+1층) 바닥 위,
  오프닝 가장자리 바깥. 계단·ESC 가 도착하는 쪽 가장자리(부재가 슬래브에 맞닿음)는 없음
- 가장자리를 빼는 경우: 경계석이 내공면(벽)·내공 시점/종점 밖으로 나감(벽에 붙은 쪽), 같은 슬래브 다른 오프닝과 겹침
- 가장자리 하나 = 바깥 거리 띠 [e0, e1] 로 정의되는 사각형. 모서리(이웃 가장자리도 있음)는 s 방향 가장자리(T0/T1)가 차지하고
  t 방향 가장자리(S0/S1)는 그 안쪽까지 → 모서리 겹침·빈틈 없음. 이웃 가장자리가 없으면 오프닝 모서리선에서 끝남
- 높이(본체 FL 기준): 위층 FL = 구조 바닥, 마감면 = FL + 그 자리 실의 마감 높이(마감을 끄면 0)
조각 = (s0, s1, t0, t1, z0, z1)
"""
from config.layout_cache import cached_layout
import math
from dataclasses import dataclass, field

_EPS = 1e-6
CURB, SKIRT, CORE, POST, RAIL, GLASS = "CURB", "SKIRT", "CORE", "POST", "RAIL", "GLASS"   # CURB = 경계석 윗면 화강석 석판
EDGES = ("T0", "T1", "S0", "S1")     # T0/T1 = t 일정(s 방향) 가장자리 −t/+t, S0/S1 = s 일정(t 방향) 가장자리 시점/종점 쪽


@dataclass
class RailingLayout:
    name: str                        # RL_{오프닝 이름}
    opening: str
    floor: int                       # 난간이 서는 층
    edges: tuple                     # 난간이 있는 가장자리
    ffl: float                       # 바닥 마감면 (본체 FL 기준)
    parts: dict = field(default_factory=dict)        # 부재 코드 → [조각]

    @property
    def curb_rects(self) -> list:
        """경계석 평면 (윗면 석판 = 경계석 폭 전체)"""
        return [p[:4] for p in self.parts.get(CURB, [])]


def _inter(a, b) -> bool:
    return min(a[1], b[1]) - max(a[0], b[0]) > _EPS and min(a[3], b[3]) - max(a[2], b[2]) > _EPS


def band(rect, edge, present, e0, e1):
    """가장자리 edge 의 바깥 거리 [e0, e1] 띠 사각형 (s0, s1, t0, t1). present = 난간이 있는 가장자리 집합"""
    S0, S1, T0, T1 = rect
    if edge in ("T0", "T1"):
        s0 = S0 - e1 if "S0" in present else S0
        s1 = S1 + e1 if "S1" in present else S1
        return (s0, s1, T0 - e1, T0 - e0) if edge == "T0" else (s0, s1, T1 + e0, T1 + e1)
    t0 = T0 - e0 if "T0" in present else T0
    t1 = T1 + e0 if "T1" in present else T1
    return (S0 - e1, S0 - e0, t0, t1) if edge == "S0" else (S1 + e0, S1 + e1, t0, t1)


def _sources(cfg, rs):
    """[(오프닝 OpeningSpec, 도착 s)] — 계단(항상)·에스컬레이터(설정)"""
    out = [(lay.opening, lay.s_at(lay.length)) for lay in cfg.stair_layouts()]
    if rs.escalators:
        out += [(lay.opening, lay.s_at(lay.u_range[1])) for lay in cfg.escalator_layouts()]
    return out


@cached_layout("railings")
def layout_railings(cfg) -> list:
    rs = getattr(cfg, "railing_settings", None)
    if rs is None or not rs.enabled:
        return []
    from finishes.finish_clear import wall_surface
    from finishes.finish_layout import floor_ffl_at
    st = cfg.station
    L = st.length
    all_ops = cfg.all_openings()
    out = []
    for op, arrive in _sources(cfg, rs):
        k = op.slabs[0]
        n = k + 1
        if n > st.floors:
            continue
        rect = (op.s_start, op.s_end, op.t_lo, op.t_hi)
        S0, S1, T0, T1 = rect
        cw = rs.curb_w
        skip = {"S0" if abs(arrive - S0) < abs(arrive - S1) else "S1"}
        if T0 - cw < -wall_surface(cfg, n, -1, S0, S1) + _EPS:      # 위층 벽 마감 표면 기준
            skip.add("T0")
        if T1 + cw > wall_surface(cfg, n, +1, S0, S1) - _EPS:
            skip.add("T1")
        if S0 - cw < _EPS:
            skip.add("S0")
        if S1 + cw > L - _EPS:
            skip.add("S1")
        present = {e for e in EDGES if e not in skip}
        others = [(o.s_start, o.s_end, o.t_lo, o.t_hi) for o in all_ops if k in o.slabs and o.name != op.name]
        reach = cw + rs.post_d + rs.rail_d                   # 난간이 차지하는 바깥 거리 (레일 포함)
        for e in list(present):
            if any(_inter(band(rect, e, present, 0.0, max(reach, cw)), o) for o in others):
                present.discard(e)
        if not present:
            continue
        # 바닥 마감면: 첫 가장자리 바깥 점이 든 실
        e0 = sorted(present)[0]
        probe = {"T0": ((S0 + S1) / 2, T0 - cw - 0.05), "T1": ((S0 + S1) / 2, T1 + cw + 0.05),
                 "S0": (S0 - cw - 0.05, (T0 + T1) / 2), "S1": (S1 + cw + 0.05, (T0 + T1) / 2)}[e0]
        fl = st.floor_level(n)
        ffl = fl + floor_ffl_at(cfg, n, *probe)
        out.append(RailingLayout(f"RL_{op.name}", op.name, n, tuple(e for e in EDGES if e in present), ffl,
                                 _parts(rs, rect, present, fl, ffl)))
    return out


def _parts(rs, rect, present, fl, ffl) -> dict:
    S0, S1, T0, T1 = rect
    c = rs.center
    curb_top = ffl + rs.curb_h
    parts = {CURB: [], SKIRT: [], CORE: [], POST: [], RAIL: [], GLASS: []}
    # 경계석 (ㅠ): 윗면 화강석 석판(폭 전체) + 양 옆 흑색 걸레받이 + 속채움. 바깥 거리 띠로 나눠 모서리에서도 겹침·빈틈 없음
    cw, ts = rs.curb_w, rs.skirt_t
    z_plate = curb_top - rs.plate_t
    for e in EDGES:
        if e in present:
            parts[CURB].append((*band(rect, e, present, 0.0, cw), z_plate, curb_top))
            parts[SKIRT].append((*band(rect, e, present, 0.0, ts), fl, z_plate))
            parts[SKIRT].append((*band(rect, e, present, cw - ts, cw), fl, z_plate))
            parts[CORE].append((*band(rect, e, present, ts, cw - ts), fl, z_plate))
    # 레일 (POST 바닥 쪽 면에 붙음): 위 레일 윗면 rail_h1, 아래 레일 중심 rail_h2
    r0 = c + rs.post_d / 2.0
    for z0, z1 in ((ffl + rs.rail_h1 - rs.rail_d, ffl + rs.rail_h1),
                   (ffl + rs.rail_h2 - rs.rail_d / 2.0, ffl + rs.rail_h2 + rs.rail_d / 2.0)):
        for e in EDGES:
            if e in present:
                parts[RAIL].append((*band(rect, e, present, r0, r0 + rs.rail_d), z0, z1))
    # POST·유리: 가장자리마다 중심선을 따라
    post_top = ffl + rs.rail_h1
    g0, g1 = curb_top + rs.glass_gap, ffl + rs.rail_h1 - rs.glass_top_gap
    hw, hd = rs.post_w / 2.0, rs.post_d / 2.0
    corners = set()
    for e in EDGES:
        if e not in present:
            continue
        along_s = e in ("T0", "T1")
        if along_s:
            line = T0 - c if e == "T0" else T1 + c
            a_corner, b_corner = "S0" in present, "S1" in present
            a = S0 - c if a_corner else S0
            b = S1 + c if b_corner else S1
        else:
            line = S0 - c if e == "S0" else S1 + c
            a_corner, b_corner = "T0" in present, "T1" in present
            a = T0 - c if a_corner else T0
            b = T1 + c if b_corner else T1
        # 끝 POST: 모서리면 모서리 점(정사각, 반폭 hd), 아니면 끝선 안쪽으로 반두께
        pa = a if a_corner else a + hw
        pb = b if b_corner else b - hw
        n = max(1, math.ceil((pb - pa) / rs.post_spacing - 1e-9))
        pos = [pa + (pb - pa) * i / n for i in range(n + 1)]
        half = [hd if (i == 0 and a_corner) or (i == n and b_corner) else hw for i in range(n + 1)]
        for i, p in enumerate(pos):
            corner = (i == 0 and a_corner) or (i == n and b_corner)
            if corner:
                key = (round(p, 9), round(line, 9)) if along_s else (round(line, 9), round(p, 9))
                if key in corners:
                    continue
                corners.add(key)
                cs, ct = key
                parts[POST].append((cs - hd, cs + hd, ct - hd, ct + hd, curb_top, post_top))
            elif along_s:
                parts[POST].append((p - hw, p + hw, line - hd, line + hd, curb_top, post_top))
            else:
                parts[POST].append((line - hd, line + hd, p - hw, p + hw, curb_top, post_top))
        gt = rs.glass_t / 2.0
        for i in range(n):
            lo = pos[i] + half[i] + rs.post_gap
            hi = pos[i + 1] - half[i + 1] - rs.post_gap
            if hi - lo < _EPS:
                continue
            if along_s:
                parts[GLASS].append((lo, hi, line - gt, line + gt, g0, g1))
            else:
                parts[GLASS].append((line - gt, line + gt, lo, hi, g0, g1))
    return parts


@cached_layout("railing_footprints")
def railing_footprints(cfg, floor: int) -> list:
    """그 층 유리난간 경계석 평면 [(s0, s1, t0, t1)] — 바닥 마감·점자블록이 피함"""
    return [r for lay in layout_railings(cfg) if lay.floor == floor for r in lay.curb_rects]


def check_railings(cfg) -> None:
    rs = getattr(cfg, "railing_settings", None)
    if rs is None or not rs.enabled:
        return
    rs.check()
    layout_railings(cfg)
