"""환기구 배치 계산 (경로 해석은 출구통로와 같음 + 연속박스 단면, 수직구, 끝 그릴, 본체 측벽 칸별 오프닝).

경로 구간은 두 종류:
- 덕트 구간(평면 길이 > 0): 출구통로처럼 곧은 축의 BoxPiece 들. 단면 = 바닥·천장 슬래브 + 좌·우 바깥 벽 + 칸 사이 중벽
  (+ 칸마다 상부 헌치). 꺾이는 꼭짓점은 연귀, 일직선 꼭짓점은 경사 변화점.
- 수직 구간(평면 위치 같음, 위로): 수직구. 아래 덕트 방향(u)을 그대로 쓰는 좌표에서 수직 꼭짓점이 수직구 내공 중심.
  * 아래 덕트: 내공이 꼭짓점 + D/2 까지 이어지고 끝 벽으로 막힘. 천장 슬래브는 [L − D/2, L + D/2] 에서 칸 자리만 비움
    (바깥 벽·중벽 위 띠는 남음), 헌치도 그 구간에서는 없음.
  * 수직구: 아래 덕트 천장 상면 ~ (위 덕트 바닥 하면 | 마지막이면 꼭짓점 높이). 앞·뒤 벽(두께 = 바깥 벽) + 좌·우 벽 + 중벽.
  * 위 덕트(있으면, 아래 덕트와 평면에서 같은 선): 내공이 꼭짓점 − D/2 부터 시작하고 시작 벽으로 막힘.
    바닥 슬래브는 [−D/2, D/2] 에서 칸 자리만 비움.
- 그릴: 경로 마지막 끝면의 칸마다. 수직구 끝이면 상단 수평(윗면 = 마지막 꼭짓점 높이), 덕트 끝이면 끝 단면(덕트는 개방).
  테두리 4개 + 일정 간격 살(덕트 끝 그릴은 연직 살, 수직구 그릴은 u 방향 살) — 모두 BoxPiece.
"""
import math
from dataclasses import dataclass, field

from helper.box_piece import BoxPiece
from passages.passage_layout import resolve_vertices
from ventilations.vent_type import VentPartKind

_COLLINEAR = 1e-6
MAX_TURN_DEG = 135.0
_EPS = 1e-6


@dataclass
class VentElementLayout:
    code: str                    # 예: D1_FLOOR, D1_MID2, D1_END, V1_WALL_F, GRILL3 (D = 덕트 run, V = 수직구 번호)
    kind: VentPartKind
    pieces: list = field(default_factory=list)      # BoxPiece (local: seg = 경로 구간 번호)


@dataclass
class VentLayout:
    name: str
    spec: object                 # VentSpec
    floor: int
    side: int                    # 첫 꼭짓점이 붙은 측벽: +1 = t 큰 쪽
    vertices: list               # passages.passage_layout.ResolvedVertex
    z_floor: float               # 접합부 FL 표고
    elements: list               # VentElementLayout (콘크리트 부재)
    grills: list                 # VentElementLayout (kind GRILL, 칸마다)
    wall_openings: list          # [(이름, 층, side, s0, s1, z_rel0, z_rel1, 종류)] 칸마다
    corners: list                # 평면에서 꺾이는 꼭짓점 번호 (0 부터)
    shafts: list                 # 수직 구간 시작 꼭짓점 번호 (0 부터)
    grill_at_shaft: bool         # 그릴이 수직구 상단(True) / 덕트 끝 단면(False)

    def pieces(self) -> list:
        return [p for e in self.elements + self.grills for p in e.pieces]

    def concrete_pieces(self) -> list:
        return [p for e in self.elements for p in e.pieces]


def _rect(v0, v1, d0, d1):
    return [(v0, d0), (v1, d0), (v1, d1), (v0, d1)]


def _subtract(lo, hi, holes):
    """[lo, hi] 에서 구멍 구간들을 뺀 구간 목록"""
    out, cur = [], lo
    for a, b in sorted(holes):
        a, b = max(a, lo), min(b, hi)
        if b <= a:
            continue
        if a > cur + _EPS:
            out.append((cur, a))
        cur = max(cur, b)
    if hi > cur + _EPS:
        out.append((cur, hi))
    return out


def _bars(lo, hi, bar, gap):
    """[lo, hi] 안에 폭 bar 의 살을 간격 약 gap 으로 고르게 (양 끝 틈 포함 등간격) → [(a, b)]"""
    span = hi - lo
    n = int((span - gap) / (bar + gap) + 1e-9)
    if n <= 0:
        return []
    clear = (span - n * bar) / (n + 1)
    return [(lo + clear * (k + 1) + bar * k, lo + clear * (k + 1) + bar * (k + 1)) for k in range(n)]


def layout_vent(cfg, spec, name: str) -> VentLayout:
    """환기구 1개의 배치 (spec 의 기본 범위 검사는 vent_check.check_vent_spec 이 먼저 한다)"""
    st = cfg.station
    k = spec.floor
    vs, side, e0 = resolve_vertices(cfg, spec, name, "환기구")
    nseg = len(vs) - 1

    # ---- 구간 분류: ('H', ux, uy, L) 덕트 / ('V', dz) 수직
    segs = []
    for i, (p, q) in enumerate(zip(vs, vs[1:]), start=1):
        L = math.hypot(q.x - p.x, q.y - p.y)
        dz = q.z - p.z
        if L >= 1e-3:
            segs.append(("H", (q.x - p.x) / L, (q.y - p.y) / L, L))
        elif abs(dz) < 1e-3:
            raise ValueError(f"환기구 {name}: 꼭짓점 {i} 와 {i + 1} 의 위치가 같습니다")
        elif dz < 0:
            raise ValueError(f"환기구 {name}: 꼭짓점 {i}→{i + 1} 은 아래로 내려가는 수직 구간입니다 (수직 구간은 위로만)")
        else:
            segs.append(("V", dz))
    if segs[0][0] != "H":
        raise ValueError(f"환기구 {name}: 첫 구간은 본체 측벽에서 수평으로 나가야 합니다 (수직 구간 불가)")
    th = cfg.theta_at(vs[0].s)
    nx, ny = -side * math.sin(th), side * math.cos(th)
    _, ux, uy, _ = segs[0]
    if ux * nx + uy * ny <= 0 or abs(ux * ny - uy * nx) > 1e-3:
        raise ValueError(f"환기구 {name}: 첫 구간은 본체 측벽에서 직각으로 나가야 합니다 (꼭짓점 1→2 방향 확인)")

    def level(i):              # 덕트 구간 i 가 수평인가
        return abs(vs[i + 1].z - vs[i].z) < 1e-6

    shafts = []
    for i, sg in enumerate(segs):
        if sg[0] != "V":
            continue
        if i + 1 < nseg and segs[i + 1][0] == "V":
            raise ValueError(f"환기구 {name}: 수직 구간이 연속됩니다 (꼭짓점 {i + 1}~{i + 3}) — 하나로 합치세요")
        if not level(i - 1):
            raise ValueError(f"환기구 {name}: 수직 구간(꼭짓점 {i + 1}) 앞 덕트 구간은 수평이어야 합니다")
        if i + 1 < nseg:
            if not level(i + 1):
                raise ValueError(f"환기구 {name}: 수직 구간(꼭짓점 {i + 2}) 뒤 덕트 구간은 수평이어야 합니다")
            a, b = segs[i - 1], segs[i + 1]
            if abs(a[1] * b[2] - a[2] * b[1]) > 1e-3:
                raise ValueError(f"환기구 {name}: 수직구 위 덕트(꼭짓점 {i + 2}→{i + 3})는 아래 덕트와 평면에서 같은 선"
                                 "(같은 방향 또는 반대 방향)이어야 합니다")
        shafts.append(i)

    # ---- 평면 꺾임 (연속한 덕트 구간 사이)
    turns = [0.0] * len(vs)
    corners = []
    for i in range(1, nseg):
        if segs[i - 1][0] != "H" or segs[i][0] != "H":
            continue
        (_, ax, ay, _), (_, bx, by, _) = segs[i - 1], segs[i]
        d = math.atan2(ax * by - ay * bx, ax * bx + ay * by)
        if abs(d) < _COLLINEAR:
            continue
        if abs(math.degrees(d)) > MAX_TURN_DEG + 1e-9:
            raise ValueError(f"환기구 {name}: 꼭짓점 {i + 1} 의 꺾임각({abs(math.degrees(d)):.1f}°)이 {MAX_TURN_DEG:g}° 를 넘습니다")
        if not (level(i - 1) and level(i)):
            raise ValueError(f"환기구 {name}: 꺾이는 꼭짓점 {i + 1} 앞뒤 구간은 수평이어야 합니다 "
                             "(경사 시작점은 일직선 위 꼭짓점으로 따로 넣으세요)")
        turns[i] = d
        corners.append(i)

    # ---- 단면
    a, b, H = spec.half_in, spec.half_out, spec.cell_height
    ft, rt, wt, D = spec.floor_t, spec.roof_t, spec.wall_t, spec.depth
    cells, mids, solid = spec.cell_ranges(), spec.mid_ranges(), spec.solid_ranges()
    hw, hh = spec.haunch_w, spec.haunch_h
    haunches = []
    if hw > 0 and hh > 0:
        for c0, c1 in cells:
            haunches += [[(c0, H - hh), (c0, H), (c0 + hw, H)], [(c1, H - hh), (c1 - hw, H), (c1, H)]]
    last_is_shaft = segs[-1][0] == "V"

    elements: dict = {}

    def add(code, kind, piece):
        elements.setdefault(code, VentElementLayout(code, kind)).pieces.append(piece)

    run = 0
    for i, sg in enumerate(segs):
        if sg[0] != "H":
            continue
        if i == 0 or i in corners or segs[i - 1][0] == "V":
            run += 1
        _, ux, uy, L = sg
        p, q = vs[i], vs[i + 1]
        slope = (q.z - p.z) / L
        after_shaft = i > 0 and segs[i - 1][0] == "V"
        before_shaft = i + 1 < nseg and segs[i + 1][0] == "V"
        last = i == nseg - 1
        a0 = -D / 2.0 if after_shaft else 0.0
        a1 = L + D / 2.0 if before_shaft else L
        tp = 0.0 if after_shaft else math.tan(turns[i] / 2.0)
        tn = 0.0 if (before_shaft or last) else math.tan(turns[i + 1] / 2.0)
        roof_hole = [(L - D / 2.0, L + D / 2.0)] if before_shaft else []
        floor_hole = [(-D / 2.0, D / 2.0)] if after_shaft else []
        free_lo = D / 2.0 + wt if after_shaft else a0                 # 수직구 벽이 차지하지 않는 덕트 구간
        free_hi = L - D / 2.0 - wt if before_shaft else a1
        if (after_shaft or before_shaft) and free_hi < free_lo - _EPS:
            raise ValueError(f"환기구 {name}: 꼭짓점 {i + 1}→{i + 2} 덕트 구간({L:.3f}m)이 수직구에 비해 너무 짧습니다")
        if L <= b * abs(tp + tn) + 1e-6:
            raise ValueError(f"환기구 {name}: 꼭짓점 {i + 1}→{i + 2} 구간({L:.3f}m)이 꺾임부 연귀 접합에 비해 너무 짧습니다")
        dcode = f"D{run}"

        def piece(lo, hi, sect, first_ks=True, last_ke=True):
            return BoxPiece(ox=p.x, oy=p.y, ux=ux, uy=uy, a0=lo, a1=hi, sect=sect, z0=p.z + slope * lo, slope=slope,
                            ks=tp if (first_ks and abs(lo - a0) < _EPS) else 0.0,
                            ke=-tn if (last_ke and abs(hi - a1) < _EPS) else 0.0, local={"seg": i, "run": run})

        def strips(kind, code, d0, d1, hole):
            """슬래브: 구멍 구간 밖은 전체 폭, 구멍 구간에서는 벽 위 띠만"""
            for lo, hi in _subtract(a0, a1, hole):
                add(code, kind, piece(lo, hi, _rect(-b, b, d0, d1)))
            for lo, hi in hole:
                for v0, v1 in solid:
                    add(code, kind, piece(lo, hi, _rect(v0, v1, d0, d1)))

        strips(VentPartKind.FLOOR, f"{dcode}_FLOOR", -ft, 0.0, floor_hole)
        strips(VentPartKind.ROOF, f"{dcode}_ROOF", H, H + rt, roof_hole)
        add(f"{dcode}_WALL_L", VentPartKind.WALL, piece(a0, a1, _rect(a, b, 0.0, H)))      # L = 진행방향 왼쪽(+v)
        add(f"{dcode}_WALL_R", VentPartKind.WALL, piece(a0, a1, _rect(-b, -a, 0.0, H)))
        for m, (v0, v1) in enumerate(mids, start=1):
            add(f"{dcode}_MID{m}", VentPartKind.MID_WALL, piece(a0, a1, _rect(v0, v1, 0.0, H)))
        h_hi = a1 - (spec.grill_t if last and not last_is_shaft else 0.0)            # 덕트 끝 그릴 자리는 헌치 없음
        for lo, hi in _subtract(a0, h_hi, roof_hole):
            for sect in haunches:
                add(f"{dcode}_ROOF", VentPartKind.ROOF, piece(lo, hi, sect, last_ke=hi >= a1 - _EPS))
        if after_shaft:
            add(f"{dcode}_END_S", VentPartKind.END_WALL, piece(a0 - wt, a0, _rect(-b, b, -ft, H + rt)))
        if before_shaft:
            add(f"{dcode}_END_E", VentPartKind.END_WALL, piece(a1, a1 + wt, _rect(-b, b, -ft, H + rt)))

    # ---- 수직구
    for j, i in enumerate(shafts, start=1):
        _, ux, uy, L = segs[i - 1]
        v = vs[i]
        z_bot = v.z + H + rt                                    # 아래 덕트 천장 상면
        z_top = vs[i + 1].z - (0.0 if i + 1 == nseg else ft)    # 마지막이면 그릴 윗면, 아니면 위 덕트 바닥 하면
        if z_top <= z_bot + _EPS:
            raise ValueError(f"환기구 {name}: 수직 구간(꼭짓점 {i + 1}→{i + 2})이 너무 낮습니다 "
                             f"(수직구 바닥 {z_bot:.3f} ≥ 위 끝 {z_top:.3f}; 덕트 높이 + 천장" + ("" if i + 1 == nseg else " + 바닥") + " 두께 이상 올라가야 함)")
        h = z_top - z_bot

        def box(lo, hi, v0, v1, z0=z_bot, height=h, seg=i):
            return BoxPiece(ox=v.x, oy=v.y, ux=ux, uy=uy, a0=lo, a1=hi, sect=_rect(v0, v1, 0.0, height), z0=z0,
                            local={"seg": seg, "shaft": j})
        code = f"V{j}"
        add(f"{code}_WALL_B", VentPartKind.SHAFT_WALL, box(-D / 2.0 - wt, -D / 2.0, -b, b))     # 뒤 (아래 덕트 쪽)
        add(f"{code}_WALL_F", VentPartKind.SHAFT_WALL, box(D / 2.0, D / 2.0 + wt, -b, b))       # 앞 (아래 덕트 진행 쪽)
        add(f"{code}_WALL_L", VentPartKind.SHAFT_WALL, box(-D / 2.0, D / 2.0, a, b))
        add(f"{code}_WALL_R", VentPartKind.SHAFT_WALL, box(-D / 2.0, D / 2.0, -b, -a))
        for m, (v0, v1) in enumerate(mids, start=1):
            add(f"{code}_MID{m}", VentPartKind.SHAFT_WALL, box(-D / 2.0, D / 2.0, v0, v1))

    # ---- 그릴 (경로 마지막 끝면, 칸마다)
    g, fw, bw, gap = spec.grill_t, spec.grill_frame, spec.grill_bar, spec.grill_gap
    grills = []
    if last_is_shaft:
        i = nseg - 1
        _, ux, uy, _ = segs[i - 1]
        v = vs[i]
        z0 = vs[-1].z - g
        u0, u1 = -D / 2.0, D / 2.0
        for c, (c0, c1) in enumerate(cells, start=1):
            el = VentElementLayout(f"GRILL{c}", VentPartKind.GRILL)

            def gbox(lo, hi, v0, v1):
                return BoxPiece(ox=v.x, oy=v.y, ux=ux, uy=uy, a0=lo, a1=hi, sect=_rect(v0, v1, 0.0, g), z0=z0,
                                local={"seg": i, "grill": c})
            el.pieces += [gbox(u0, u1, c0, c0 + fw), gbox(u0, u1, c1 - fw, c1),                 # 테두리 (u 방향 2개)
                          gbox(u0, u0 + fw, c0 + fw, c1 - fw), gbox(u1 - fw, u1, c0 + fw, c1 - fw)]
            el.pieces += [gbox(u0 + fw, u1 - fw, s0, s1) for s0, s1 in _bars(c0 + fw, c1 - fw, bw, gap)]   # 살 (u 방향)
            grills.append(el)
    else:
        i = nseg - 1
        _, ux, uy, L = segs[i]
        p, q = vs[i], vs[i + 1]
        slope = (q.z - p.z) / L
        lo, hi = L - g, L
        for c, (c0, c1) in enumerate(cells, start=1):
            el = VentElementLayout(f"GRILL{c}", VentPartKind.GRILL)

            def gpiece(v0, v1, d0, d1):
                return BoxPiece(ox=p.x, oy=p.y, ux=ux, uy=uy, a0=lo, a1=hi, sect=_rect(v0, v1, d0, d1),
                                z0=p.z + slope * lo, slope=slope, local={"seg": i, "grill": c})
            el.pieces += [gpiece(c0, c0 + fw, 0.0, H), gpiece(c1 - fw, c1, 0.0, H),            # 테두리 (연직 2개)
                          gpiece(c0 + fw, c1 - fw, 0.0, fw), gpiece(c0 + fw, c1 - fw, H - fw, H)]
            el.pieces += [gpiece(s0, s1, fw, H - fw) for s0, s1 in _bars(c0 + fw, c1 - fw, bw, gap)]   # 살 (연직)
            grills.append(el)

    # ---- 본체 측벽 칸별 오프닝 (첫 구간이 측벽에 직각: v = −side·(s − s0))
    s0, fl = vs[0].s, st.floor_level(k)
    openings = []
    for c, (c0, c1) in enumerate(cells, start=1):
        sa, sb = sorted((s0 - side * c0, s0 - side * c1))
        openings.append((f"{name}_C{c}", k, side, sa, sb, fl, fl + H, "VENT_DUCT"))
    return VentLayout(name=name, spec=spec, floor=k, side=side, vertices=vs, z_floor=e0, elements=list(elements.values()),
                      grills=grills, wall_openings=openings, corners=corners, shafts=shafts, grill_at_shaft=last_is_shaft)
