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
    wall_opening: tuple          # (이름, 층, side, s0, s1, z_rel0, z_rel1)  z_rel = 바닥 슬래브 상면 기준
    corners: list                # 꺾이는 꼭짓점 번호 (0 부터)

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


def resolve_vertices(cfg, spec, name: str, what: str = "출구통로") -> tuple[list, int, float]:
    """꼭짓점을 세계 좌표·절대 표고로 해석하고 접합부 조건 검사. (꼭짓점, side, 접합부 FL 표고). what = 오류 문구의 구조물 이름"""
    st = cfg.station
    k = spec.floor
    raw = []
    for i, v in enumerate(spec.path, start=1):
        if v.mode == STATION:
            s, t = v.x, v.y
            x, y = cfg.to_world(s, t)
        elif v.mode == WORLD:
            x, y = v.x, v.y
            s, t = cfg.to_station(x, y)
        else:
            raise ValueError(f"{what} {name}: 꼭짓점 {i} 의 좌표 방식이 올바르지 않습니다 ({v.mode!r})")
        raw.append((x, y, s, t))
    x0, y0, s0, t0 = raw[0]
    t_face = st.width / 2.0 + st.wall_t_at(k)
    if abs(abs(t0) - t_face) > 1e-3:
        raise ValueError(f"{what} {name}: 첫 꼭짓점(t = {t0:.3f})이 {st.level_name(k)} 외벽 바깥면(t = ±{t_face:g})에 있지 않습니다")
    side = 1 if t0 > 0 else -1
    e0 = cfg.lv(s0) - st.offset + st.floor_level(k)
    out = []
    for i, ((x, y, s, t), v) in enumerate(zip(raw, spec.path), start=1):
        if v.z is None:
            if i > 1:
                raise ValueError(f"{what} {name}: 꼭짓점 {i} 의 바닥 높이를 입력하세요")
            z = e0
        else:
            z = e0 + v.z if v.mode == STATION else v.z
            if i == 1 and abs(z - e0) > _Z_TOL:
                raise ValueError(f"{what} {name}: 첫 꼭짓점 바닥 높이({z:.3f})가 접합부 FL({e0:.3f})과 다릅니다 "
                                 "(비워 두면 FL)")
        out.append(ResolvedVertex(x, y, e0 if i == 1 else z, s, t))
    return out, side, e0


def layout_passage(cfg, spec, name: str) -> PassageLayout:
    """통로 1개의 배치 (spec 의 기본 범위 검사는 passage_check.check_passage_spec 이 먼저 한다)"""
    st = cfg.station
    k = spec.floor
    vs, side, e0 = resolve_vertices(cfg, spec, name)

    # 구간 방향·길이
    segs = []
    for i, (p, q) in enumerate(zip(vs, vs[1:]), start=1):
        L = math.hypot(q.x - p.x, q.y - p.y)
        if L < 1e-3:
            raise ValueError(f"출구통로 {name}: 꼭짓점 {i} 와 {i + 1} 의 평면 위치가 같습니다")
        segs.append(((q.x - p.x) / L, (q.y - p.y) / L, L))

    # 첫 구간: 본체에서 직각으로 나감
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
            piece = BoxPiece(ox=p.x, oy=p.y, ux=ux, uy=uy, a0=0.0, a1=L, sect=sect, z0=p.z, slope=slope,
                             ks=tp, ke=-tn, local={"seg": i, "run": run})
            key = f"S{run}_{code}"
            elements.setdefault(key, PassageElementLayout(key, run, kind, [])).pieces.append(piece)

    s0 = vs[0].s
    fl = st.floor_level(k)
    opening = (name, k, side, s0 - a, s0 + a, fl, fl + H)
    return PassageLayout(name=name, spec=spec, floor=k, side=side, vertices=vs, z_floor=e0,
                         elements=list(elements.values()), wall_opening=opening, corners=corners)
