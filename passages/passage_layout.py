"""출구통로 배치 계산 (경로 꼭짓점 해석, 구간별 부재 조각, 본체 측벽 오프닝).

경로 = 통로 중심선 폴리선. 꼭짓점은 선형 상대 (s, t) 또는 절대 (X, Y) 로 주고, 둘 다 세계 평면 좌표로 바꿔 쓴다.
구간(꼭짓점 사이)마다 곧은 축을 가진 BoxPiece 들로 단면(바닥·천장·좌우 벽·헌치)을 만든다.
- 바닥 상면 높이는 꼭짓점 사이 직선 보간 (구간 구배 = 높이차 / 평면 길이)
- 꺾이는 꼭짓점에서는 두 구간을 이등분선으로 맞대어 자른다 (연귀): 단면 v 위치에서 앞 구간 끝 = L − v·tan(δ/2),
  뒤 구간 시작 = v·tan(δ/2) (δ = 왼쪽 + 회전각). 앞뒤 구간이 수평이라 꺾임부 높이가 어긋나지 않는다
- 평면에서 일직선인 꼭짓점(경사 변화점)은 직각으로 잘라 잇는다
- 부재는 '평면 직선 구간(run)' 단위로 묶는다: 꺾이는 꼭짓점마다 run 번호가 바뀐다
"""
import math
from dataclasses import dataclass

from helper.box_piece import BoxPiece
from passages.passage_spec import STATION, WORLD
from passages.passage_type import PassagePartKind

_COLLINEAR = 1e-6          # rad: 이보다 작게 꺾이면 일직선 (경사 변화점)
MAX_TURN_DEG = 135.0
_Z_TOL = 0.005             # 첫 꼭짓점 높이 허용 오차 (m)


@dataclass
class ResolvedVertex:
    x: float                 # 세계 평면 좌표
    y: float
    z: float                 # 바닥 상면 절대 표고
    s: float                 # 정거장 로컬
    t: float


@dataclass
class PassageElementLayout:
    code: str                    # 예: S1_FLOOR, S2_WALL_L (S = 평면 직선 구간 번호)
    run: int
    kind: PassagePartKind
    pieces: list                 # BoxPiece


@dataclass
class PassageLayout:
    name: str
    spec: object                 # PassageSpec
    floor: int
    side: int                    # 첫 꼭짓점이 붙은 측벽: +1 = t 큰 쪽
    vertices: list               # ResolvedVertex
    z_floor: float               # 접합부(첫 꼭짓점) 바닥 상면 = 그 층 FL 표고
    elements: list               # PassageElementLayout
    wall_opening: tuple          # (이름, 층, side, s0, s1, z_rel0, z_rel1)  z_rel = 바닥 슬래브 상면 기준. 분기 통로는 None
    corners: list                # 꺾이는 꼭짓점 번호 (0 부터)
    parent: str = ""             # 분기한 부모 통로 이름 ('' = 본체)
    branch_seg: int = -1         # 분기면 부모 구간 번호 (0 부터)
    branch_a: float = 0.0        # 분기면 부모 구간 축 위 접합 위치 (구간 시작 꼭짓점에서의 거리)

    def pieces(self) -> list:
        return [p for e in self.elements for p in e.pieces]

    @property
    def plan_length(self) -> float:
        vs = self.vertices
        return sum(math.hypot(b.x - a.x, b.y - a.y) for a, b in zip(vs, vs[1:]))


def _rect(v0, v1, d0, d1):
    return [(v0, d0), (v1, d0), (v1, d1), (v0, d1)]


def _haunch_top(v_face, into, hw, hh, H):
    """천장 하면(H) 과 벽 안쪽 면(v_face) 의 모서리 삼각형. into = 내공 쪽 방향(±1)"""
    return [(v_face, H - hh), (v_face, H), (v_face + into * hw, H)]


def _haunch_bottom(v_face, into, hw, hh):
    return [(v_face, 0.0), (v_face + into * hw, 0.0), (v_face, hh)]


def lower_ledge(station, floor_n: int) -> float:
    """아래층 외벽이 그 층보다 두꺼워 바깥으로 나온 턱의 폭 (m, 없으면 0).
    아래층 벽 상단 = 그 층 FL 이라, 접합부에서 나가는 통로·덕트의 바닥 슬래브(FL − 바닥 두께 ~ FL)와 이 폭만큼 겹친다"""
    if floor_n <= 1:
        return 0.0
    return max(0.0, station.wall_t_at(floor_n - 1) - station.wall_t_at(floor_n))


def _auto_side(cfg, spec, name: str, what: str) -> int:
    """첫 꼭짓점 t 를 비웠을 때 붙을 측벽: 두 번째 꼭짓점이 선형 중심의 어느 쪽인가"""
    if len(spec.path) < 2:
        raise ValueError(f"{what} {name}: 첫 꼭짓점 t 를 비우려면 두 번째 꼭짓점이 있어야 합니다")
    v = spec.path[1]
    t = v.y if v.mode == STATION else cfg.to_station(v.x, v.y)[1]
    if t is None or abs(t) < 1e-9:
        raise ValueError(f"{what} {name}: 첫 꼭짓점 t 를 비우면 두 번째 꼭짓점의 t 부호로 측벽을 정합니다 "
                         "(두 번째 꼭짓점 t 가 0 이 아니어야 함)")
    return 1 if t > 0 else -1


def resolve_vertices(cfg, spec, name: str, what: str = "출구통로", last_z=None) -> tuple[list, int, float]:
    """꼭짓점을 세계 좌표·절대 표고로 해석하고 접합부 조건 검사. (꼭짓점, side, 접합부 FL 표고). what = 오류 문구의 구조물 이름.
    첫 꼭짓점(선형 상대)의 t 가 None 이면 그 층 외벽 바깥면(측벽은 두 번째 꼭짓점 t 의 부호)에 붙인다.
    last_z: 주면 마지막 꼭짓점 높이가 None 일 때 쓸 절대 표고 (환기구: 지표 EL + 지상 돌출 높이)"""
    st = cfg.station
    k = spec.floor
    t_face = st.width / 2.0 + st.wall_t_at(k)
    raw = []
    for i, v in enumerate(spec.path, start=1):
        if v.mode == STATION:
            s, t = v.x, v.y
            if t is None:
                if i > 1:
                    raise ValueError(f"{what} {name}: 꼭짓점 {i} 의 t 를 입력하세요 (비울 수 있는 것은 첫 꼭짓점뿐)")
                t = _auto_side(cfg, spec, name, what) * t_face
            x, y = cfg.to_world(s, t)
        elif v.mode == WORLD:
            x, y = v.x, v.y
            s, t = cfg.to_station(x, y)
        else:
            raise ValueError(f"{what} {name}: 꼭짓점 {i} 의 좌표 방식이 올바르지 않습니다 ({v.mode!r})")
        raw.append((x, y, s, t))
    x0, y0, s0, t0 = raw[0]
    if abs(abs(t0) - t_face) > 1e-3:
        raise ValueError(f"{what} {name}: 첫 꼭짓점(t = {t0:.3f})이 {st.level_name(k)} 외벽 바깥면(t = ±{t_face:g})에 있지 않습니다")
    side = 1 if t0 > 0 else -1
    e0 = cfg.lv(s0) - st.offset + st.floor_level(k)
    out = []
    for i, ((x, y, s, t), v) in enumerate(zip(raw, spec.path), start=1):
        if v.z is None:
            if i == len(spec.path) and i > 1 and last_z is not None:
                z = last_z
            elif i > 1:
                raise ValueError(f"{what} {name}: 꼭짓점 {i} 의 바닥 높이를 입력하세요")
            else:
                z = e0
        else:
            z = e0 + v.z if v.mode == STATION else v.z
            if i == 1 and abs(z - e0) > _Z_TOL:
                raise ValueError(f"{what} {name}: 첫 꼭짓점 바닥 높이({z:.3f})가 접합부 FL({e0:.3f})과 다릅니다 "
                                 "(비워 두면 FL)")
        out.append(ResolvedVertex(x, y, e0 if i == 1 else z, s, t))
    return out, side, e0


def _plain_xy(cfg, v):
    """꼭짓점 → 세계 평면 좌표 (선형 상대 t 가 비면 None)"""
    if v.mode == STATION:
        return None if v.y is None else cfg.to_world(v.x, v.y)
    return (v.x, v.y)


def resolve_branch(cfg, spec, name: str, parent) -> tuple:
    """분기 통로의 꼭짓점 해석. 부모 구간 = 첫 꼭짓점(t 를 비우면 두 번째 꼭짓점)에 가장 가까운 부모 구간,
    접합점 = 두 번째 꼭짓점에서 그 구간에 내린 수선의 발을 부모 측벽 바깥면으로 옮긴 점 (첫 구간이 부모에 직각).
    반환: (꼭짓점, side(+1 = 부모 진행방향 왼쪽), 접합부 바닥 표고, 부모 구간 번호, 구간 축 위 위치)"""
    what = f"출구통로 {name}"
    if len(spec.path) < 2:
        raise ValueError(f"{what}: 분기 통로는 꼭짓점이 2개 이상이어야 합니다")
    p2 = _plain_xy(cfg, spec.path[1])
    if p2 is None:
        raise ValueError(f"{what}: 꼭짓점 2 의 t 를 입력하세요")
    probe = _plain_xy(cfg, spec.path[0]) or p2
    pv = parent.vertices
    best = None
    for i, (p, q) in enumerate(zip(pv, pv[1:])):
        L = math.hypot(q.x - p.x, q.y - p.y)
        ux, uy = (q.x - p.x) / L, (q.y - p.y) / L
        a = max(0.0, min(L, (probe[0] - p.x) * ux + (probe[1] - p.y) * uy))
        d = math.hypot(probe[0] - (p.x + ux * a), probe[1] - (p.y + uy * a))
        if best is None or d < best[0] - 1e-9:
            best = (d, i, ux, uy)
    _, i, ux, uy = best
    p, q = pv[i], pv[i + 1]
    if abs(q.z - p.z) > 1e-6:
        raise ValueError(f"{what}: 분기하는 부모 통로 {parent.name} 의 구간 {i + 1}–{i + 2} 이(가) 수평이 아닙니다 "
                         "(분기는 수평 구간에서만)")
    a = (p2[0] - p.x) * ux + (p2[1] - p.y) * uy
    seg_len = math.hypot(q.x - p.x, q.y - p.y)
    if not -1e-6 <= a <= seg_len + 1e-6:
        raise ValueError(f"{what}: 두 번째 꼭짓점에서 부모 통로 {parent.name} 구간 {i + 1}–{i + 2} 에 내린 수선의 발이 "
                         f"구간 밖({a:.2f}m, 구간 길이 {seg_len:.2f}m)입니다 — T자 분기는 부모 측벽 중간에서 직각으로만 "
                         "나갑니다 (부모 끝에서 이어 나가는 분기는 아직 지원하지 않음)")
    side_d = -(p2[0] - p.x) * uy + (p2[1] - p.y) * ux          # 부모 진행방향 왼쪽(+v) 거리
    side = 1 if side_d > 0 else -1
    reach = parent.spec.half_out
    if abs(side_d) <= reach + 1e-6:
        raise ValueError(f"{what}: 두 번째 꼭짓점이 부모 통로 {parent.name} 바깥에 있어야 합니다 (측벽에서 직각으로 나감)")
    jx, jy = p.x + ux * a - side * uy * reach, p.y + uy * a + side * ux * reach
    js, jt = cfg.to_station(jx, jy)
    e0 = p.z
    out = [ResolvedVertex(jx, jy, e0, js, jt)]
    for j, v in enumerate(spec.path[1:], start=2):
        xy = _plain_xy(cfg, v)
        if xy is None:
            raise ValueError(f"{what}: 꼭짓점 {j} 의 t 를 입력하세요")
        if v.z is None:
            raise ValueError(f"{what}: 꼭짓점 {j} 의 바닥 높이를 입력하세요")
        s, t = (v.x, v.y) if v.mode == STATION else cfg.to_station(*xy)
        out.append(ResolvedVertex(xy[0], xy[1], e0 + v.z if v.mode == STATION else v.z, s, t))
    if spec.path[0].z is not None:
        z = e0 + spec.path[0].z if spec.path[0].mode == STATION else spec.path[0].z
        if abs(z - e0) > _Z_TOL:
            raise ValueError(f"{what}: 첫 꼭짓점 바닥 높이({z:.3f})가 분기점 부모 바닥({e0:.3f})과 다릅니다 (비워 두면 부모 바닥)")
    return out, side, e0, i, a


def layout_passage(cfg, spec, name: str, parent=None) -> PassageLayout:
    """통로 1개의 배치 (spec 의 기본 범위 검사는 passage_check.check_passage_spec 이 먼저 한다).
    parent: 분기면 부모 PassageLayout (먼저 배치되어 있어야 함)"""
    st = cfg.station
    k = parent.floor if parent is not None else spec.floor
    if parent is not None:
        vs, side, e0, bseg, ba = resolve_branch(cfg, spec, name, parent)
    else:
        vs, side, e0 = resolve_vertices(cfg, spec, name)

    # 구간 방향·길이
    segs = []
    for i, (p, q) in enumerate(zip(vs, vs[1:]), start=1):
        L = math.hypot(q.x - p.x, q.y - p.y)
        if L < 1e-3:
            raise ValueError(f"출구통로 {name}: 꼭짓점 {i} 와 {i + 1} 의 평면 위치가 같습니다")
        segs.append(((q.x - p.x) / L, (q.y - p.y) / L, L))

    # 첫 구간: 본체에서 직각으로 나감 (분기는 접합점을 수선의 발로 잡아 늘 직각)
    if parent is None:
        th = cfg.theta_at(vs[0].s)
        nx, ny = -side * math.sin(th), side * math.cos(th)
        ux, uy, _ = segs[0]
        if ux * nx + uy * ny <= 0 or abs(ux * ny - uy * nx) > 1e-3:
            raise ValueError(f"출구통로 {name}: 첫 구간은 본체 측벽에서 직각으로 나가야 합니다 (꼭짓점 1→2 방향 확인)")

    # 꺾임각 (꼭짓점 i: 구간 i-1 → i), 꺾임부 수평 검사
    turns = [0.0] * len(vs)
    corners = []
    for i in range(1, len(vs) - 1):
        (ax, ay, _), (bx, by, _) = segs[i - 1], segs[i]
        d = math.atan2(ax * by - ay * bx, ax * bx + ay * by)
        if abs(d) < _COLLINEAR:
            continue
        if abs(math.degrees(d)) > MAX_TURN_DEG + 1e-9:
            raise ValueError(f"출구통로 {name}: 꼭짓점 {i + 1} 의 꺾임각({abs(math.degrees(d)):.1f}°)이 "
                             f"{MAX_TURN_DEG:g}° 를 넘습니다")
        if abs(vs[i].z - vs[i - 1].z) > 1e-6 or abs(vs[i + 1].z - vs[i].z) > 1e-6:
            raise ValueError(f"출구통로 {name}: 꺾이는 꼭짓점 {i + 1} 앞뒤 구간은 수평이어야 합니다 "
                             "(경사 시작점은 일직선 위 꼭짓점으로 따로 넣으세요)")
        turns[i] = d
        corners.append(i)

    a, b, H = spec.half_in, spec.half_out, spec.inner_height
    ft, rt = spec.floor_t, spec.roof_t
    th_w, th_h, bh_w, bh_h = spec.top_haunch_w, spec.top_haunch_h, spec.bottom_haunch_w, spec.bottom_haunch_h
    sections = [(PassagePartKind.FLOOR, "FLOOR", _rect(-b, b, -ft, 0.0)),
                (PassagePartKind.ROOF, "ROOF", _rect(-b, b, H, H + rt)),
                (PassagePartKind.WALL, "WALL_L", _rect(a, b, 0.0, H)),        # L = 진행방향 왼쪽(+v)
                (PassagePartKind.WALL, "WALL_R", _rect(-b, -a, 0.0, H))]
    if th_w > 0 and th_h > 0:
        sections += [(PassagePartKind.ROOF, "ROOF", _haunch_top(-a, 1, th_w, th_h, H)),
                     (PassagePartKind.ROOF, "ROOF", _haunch_top(a, -1, th_w, th_h, H))]
    if bh_w > 0 and bh_h > 0:
        sections += [(PassagePartKind.FLOOR, "FLOOR", _haunch_bottom(-a, 1, bh_w, bh_h)),
                     (PassagePartKind.FLOOR, "FLOOR", _haunch_bottom(a, -1, bh_w, bh_h))]

    ledge = lower_ledge(st, k) if parent is None else 0.0     # 아래층 벽 턱 위는 바닥 슬래브를 빼고 벽 상단이 바닥
    if ledge > 0 and segs[0][2] <= ledge + b * abs(math.tan(turns[1] / 2.0)) + 1e-6:
        raise ValueError(f"출구통로 {name}: 첫 구간({segs[0][2]:.3f}m)이 아래층 외벽 턱({ledge:g}m)에 비해 너무 짧습니다")
    elements: dict = {}
    run = 1
    for i, (ux, uy, L) in enumerate(segs):
        if i in corners:
            run += 1
        tp = math.tan(turns[i] / 2.0)                    # 시작 꼭짓점(i)의 연귀
        tn = math.tan(turns[i + 1] / 2.0)                # 끝 꼭짓점(i+1)의 연귀
        if L <= b * abs(tp + tn) + 1e-6:
            raise ValueError(f"출구통로 {name}: 꼭짓점 {i + 1}→{i + 2} 구간({L:.3f}m)이 꺾임부 연귀 접합에 비해 너무 짧습니다")
        p, q = vs[i], vs[i + 1]
        slope = (q.z - p.z) / L
        for kind, code, sect in sections:
            lo = ledge if (i == 0 and kind == PassagePartKind.FLOOR and sect[0][1] < 0.0) else 0.0   # 바닥 슬래브만 (헌치는 FL 위)
            piece = BoxPiece(ox=p.x, oy=p.y, ux=ux, uy=uy, a0=lo, a1=L, sect=sect, z0=p.z + slope * lo, slope=slope,
                             ks=tp if lo == 0.0 else 0.0, ke=-tn, local={"seg": i, "run": run})
            key = f"S{run}_{code}"
            elements.setdefault(key, PassageElementLayout(key, run, kind, [])).pieces.append(piece)

    if spec.close_end:                                   # 끝 벽: 마지막 구간 끝 [L − 벽 두께, L], 헌치 삼각 조각은 끝 벽 앞까지
        last, wt = len(segs) - 1, spec.wall_t
        ux, uy, L = segs[last]
        p, q = vs[last], vs[last + 1]
        slope = (q.z - p.z) / L
        tp = math.tan(turns[last] / 2.0)
        if L - wt <= b * abs(tp) + 1e-6:
            raise ValueError(f"출구통로 {name}: 마지막 구간({L:.3f}m)이 끝 벽({wt:g}m)에 비해 너무 짧습니다")
        run = max(e.run for e in elements.values())
        for e in elements.values():
            for pc in e.pieces:
                if pc.local.get("seg") == last and len(pc.sect) == 3:
                    pc.a1 = L - wt
        end = BoxPiece(ox=p.x, oy=p.y, ux=ux, uy=uy, a0=L - wt, a1=L, sect=_rect(-a, a, 0.0, H), z0=p.z + slope * (L - wt),
                       slope=slope, local={"seg": last, "run": run, "end": True})
        elements[f"S{run}_END"] = PassageElementLayout(f"S{run}_END", run, PassagePartKind.WALL, [end])

    if parent is not None:
        return PassageLayout(name=name, spec=spec, floor=k, side=side, vertices=vs, z_floor=e0,
                             elements=list(elements.values()), wall_opening=None, corners=corners,
                             parent=parent.name, branch_seg=bseg, branch_a=ba)
    s0 = vs[0].s
    fl = st.floor_level(k)
    opening = (name, k, side, s0 - a, s0 + a, fl, fl + H)
    return PassageLayout(name=name, spec=spec, floor=k, side=side, vertices=vs, z_floor=e0,
                         elements=list(elements.values()), wall_opening=opening, corners=corners)


def cut_branch_opening(parent: PassageLayout, child: PassageLayout):
    """부모 통로 측벽에 분기 통로 내공 크기의 개구부: 그 구간의 WALL_L/R 조각을 개구부 앞·뒤 + 위 인방으로 나눔"""
    sp, cs = parent.spec, child.spec
    seg, side = child.branch_seg, child.side
    o0, o1 = child.branch_a - cs.half_in, child.branch_a + cs.half_in
    code = "WALL_L" if side > 0 else "WALL_R"
    if sp.close_end and seg == len(parent.vertices) - 2:
        L = parent.vertices[-1]
        L = math.hypot(L.x - parent.vertices[-2].x, L.y - parent.vertices[-2].y)
        if o1 > L - sp.wall_t + 1e-6:
            raise ValueError(f"출구통로 {child.name}: 분기 개구부가 부모 통로 {parent.name} 의 끝 벽과 겹칩니다 — 부모 경로 끝을 "
                             f"{o1 + sp.wall_t - L:.3f}m 이상 늘리거나(분기 바깥 벽 면까지면 "
                             f"{child.branch_a + cs.half_out - L:.3f}m) 끝 폐합을 끄세요")
    hit = False
    for e in parent.elements:
        if not e.code.endswith(code):
            continue
        new = []
        for pc in e.pieces:
            if pc.local.get("seg") != seg or not (pc.a0 - 1e-9 <= child.branch_a <= pc.a1 + 1e-9):
                new.append(pc)
                continue
            lo = max(pc.a_start(sp.half_out * side), pc.a_start(sp.half_in * side))
            hi = min(pc.a_end(sp.half_out * side), pc.a_end(sp.half_in * side))
            if o0 < lo + 1e-6 or o1 > hi - 1e-6:
                raise ValueError(f"출구통로 {child.name}: 분기 개구부가 부모 통로 {parent.name} 구간 {seg + 1}–{seg + 2} 의 "
                                 "측벽 범위(꺾임부 연귀 포함)를 벗어납니다 (분기 위치를 구간 가운데 쪽으로 옮기세요)")
            hit = True

            def z_at(a, pc=pc):
                return pc.z0 + pc.slope * (a - pc.a0)
            new.append(BoxPiece(pc.ox, pc.oy, pc.ux, pc.uy, pc.a0, o0, pc.sect, pc.z0, pc.slope, pc.ks, 0.0, dict(pc.local)))
            new.append(BoxPiece(pc.ox, pc.oy, pc.ux, pc.uy, o1, pc.a1, pc.sect, z_at(o1), pc.slope, 0.0, pc.ke, dict(pc.local)))
            top = max(dz for _, dz in pc.sect)
            if cs.inner_height < top - 1e-6:                           # 개구부 위 인방
                vv = sorted({v for v, _ in pc.sect})
                lintel = [(vv[0], cs.inner_height), (vv[-1], cs.inner_height), (vv[-1], top), (vv[0], top)]
                new.append(BoxPiece(pc.ox, pc.oy, pc.ux, pc.uy, o0, o1, lintel, z_at(o0), pc.slope, 0.0, 0.0,
                                    dict(pc.local, lintel=child.name)))
        e.pieces = new
    if not hit:
        raise ValueError(f"출구통로 {child.name}: 부모 통로 {parent.name} 의 분기 위치에서 측벽 조각을 찾지 못했습니다")
