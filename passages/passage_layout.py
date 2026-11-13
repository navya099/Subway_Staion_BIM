"""출구통로 배치 계산 (통로 좌표계, 부재 조각, 본체 측벽 오프닝).

통로 좌표 (X, Y): 원점 = 통로 중심선이 본체 외벽 바깥면과 만나는 점(중심 STA, 그 층 외벽 바깥면),
X = 선형에 직각으로 본체에서 멀어지는 방향, Y = 꺾이는 방향(선형 접선 방향 × turn). 둘 다 세계 평면에서 곧은 축이다.
모든 부재 조각은 X 또는 Y 축을 따라 곧게 뻗은 BoxPiece 이고, 단면 좌표는 (다른 축 좌표, 통로 기준 표고에서의 높이).
통로 기준 표고 = 바닥 상면: 측벽 접합부에서 그 층 FL, 구배로 변하며 꺾임부(모서리 사각형)는 수평.
"""
import math
from dataclasses import dataclass

from helper.box_piece import BoxPiece
from passages.passage_type import PassagePartKind


@dataclass
class PassageFrame:
    """통로 좌표 → 세계 / 정거장 로컬 변환"""
    s_center: float
    side: int
    turn: int
    t_face: float            # 외벽 바깥면의 |t| (그 층 내공 반폭 + 외벽 두께)
    px: float
    py: float
    nx: float                # X 축 (세계 단위벡터)
    ny: float
    dx: float                # Y 축 (세계 단위벡터)
    dy: float

    def world(self, X: float, Y: float) -> tuple[float, float]:
        return self.px + X * self.nx + Y * self.dx, self.py + X * self.ny + Y * self.dy

    def station(self, X: float, Y: float) -> tuple[float, float]:
        """정거장 로컬 (s, t). 직선 선형에서 정확하고, 곡선에서는 중심 STA 의 접선 기준 근사 (2D 도면용)"""
        return self.s_center + self.turn * Y, self.side * (self.t_face + X)


@dataclass
class PassageElementLayout:
    code: str                    # 예: S1_FLOOR, S2_WALL_OUT
    seg: int                     # 1 = 첫 구간, 2 = 꺾임 후 구간
    kind: PassagePartKind
    pieces: list                 # BoxPiece


@dataclass
class PassageLayout:
    name: str
    spec: object                 # PassageSpec
    floor: int
    frame: PassageFrame
    z_floor: float               # 측벽 접합부의 통로 바닥 상면 표고 (절대)
    elements: list               # PassageElementLayout
    wall_opening: tuple          # (이름, 층, side, s0, s1, z_rel0, z_rel1)  z_rel = 바닥 슬래브 상면 기준

    def pieces(self) -> list:
        return [p for e in self.elements for p in e.pieces]


def _rect(w0, w1, d0, d1):
    return [(w0, d0), (w1, d0), (w1, d1), (w0, d1)]


def _haunch_top(w_face, into, hw, hh, H):
    """천장 하면(H) 과 벽 안쪽 면(w_face) 의 모서리 삼각형. into = 내공 쪽 방향(±1)"""
    return [(w_face, H - hh), (w_face, H), (w_face + into * hw, H)]


def _haunch_bottom(w_face, into, hw, hh):
    return [(w_face, 0.0), (w_face + into * hw, 0.0), (w_face, hh)]


def layout_passage(cfg, spec, name: str) -> PassageLayout:
    """통로 1개의 배치 (spec 의 기본 범위 검사는 passage_check.check_passage_spec 이 먼저 한다)"""
    st = cfg.station
    k, sc = spec.floor, spec.s_center
    t_face = st.width / 2.0 + st.wall_t_at(k)
    th = cfg.theta_at(sc)
    tau = (math.cos(th), math.sin(th))
    left = (-tau[1], tau[0])
    n = (spec.side * left[0], spec.side * left[1])
    d2 = (spec.turn * tau[0], spec.turn * tau[1])
    px, py = cfg.to_world(sc, spec.side * t_face)
    frame = PassageFrame(sc, spec.side, spec.turn, t_face, px, py, n[0], n[1], d2[0], d2[1])

    # 단면 좌표의 부호: BoxPiece 의 v 는 축의 왼쪽 수직 방향
    sig_x = d2[0] * (-n[1]) + d2[1] * n[0]            # X 축 조각: v = sig_x · Y
    sig_y = n[0] * (-d2[1]) + n[1] * d2[0]            # Y 축 조각: v = sig_y · X

    g = spec.grade_permil / 1000.0
    a, b, H = spec.half_in, spec.half_out, spec.inner_height
    L1, L2 = spec.length1, spec.length2
    x_flat = L1 - b if spec.bent else L1                # 이 X 이후(꺾임부)는 수평
    z0 = cfg.lv(sc) - st.offset + st.floor_level(k)

    def zx(X):
        return z0 + g * min(X, x_flat)

    def zy(Y):
        return z0 + g * (x_flat + max(0.0, Y - b))

    def piece(axis, a0, a1, sect, zref, slope):
        if axis == "X":
            u, sig = n, sig_x
        else:
            u, sig = d2, sig_y
        return BoxPiece(ox=px, oy=py, ux=u[0], uy=u[1], a0=a0, a1=a1, sect=[(sig * w, dz) for w, dz in sect],
                        z0=zref, slope=slope, local={"axis": axis, "sect": list(sect)})

    def along_x(a0, a1, sect):
        """X 축 조각들: 꺾임부 경계(x_flat)에서 구배 / 수평으로 나눔"""
        out = []
        if a0 < x_flat - 1e-9:
            out.append(piece("X", a0, min(a1, x_flat), sect, zx(a0), g))
        if a1 > x_flat + 1e-9:
            out.append(piece("X", max(a0, x_flat), a1, sect, zx(max(a0, x_flat)), 0.0))
        return out

    def along_y(a0, a1, sect):
        """Y 축 조각들: 꺾임부(Y < b) 는 수평, 그 뒤 구배"""
        out = []
        if a0 < b - 1e-9:
            out.append(piece("Y", a0, min(a1, b), sect, zy(a0), 0.0))
        if a1 > b + 1e-9:
            out.append(piece("Y", max(a0, b), a1, sect, zy(max(a0, b)), g))
        return out

    th_w, th_h, bh_w, bh_h = spec.top_haunch_w, spec.top_haunch_h, spec.bottom_haunch_w, spec.bottom_haunch_h
    top_h = th_w > 0 and th_h > 0
    bot_h = bh_w > 0 and bh_h > 0
    ft, rt = spec.floor_t, spec.roof_t
    E = PassageElementLayout
    K = PassagePartKind
    els = []
    if not spec.bent:
        floor = along_x(0.0, L1, _rect(-b, b, -ft, 0.0))
        roof = along_x(0.0, L1, _rect(-b, b, H, H + rt))
        if bot_h:
            floor += along_x(0.0, L1, _haunch_bottom(-a, 1, bh_w, bh_h)) + along_x(0.0, L1, _haunch_bottom(a, -1, bh_w, bh_h))
        if top_h:
            roof += along_x(0.0, L1, _haunch_top(-a, 1, th_w, th_h, H)) + along_x(0.0, L1, _haunch_top(a, -1, th_w, th_h, H))
        els += [E("S1_FLOOR", 1, K.FLOOR, floor), E("S1_ROOF", 1, K.ROOF, roof),
                E("S1_WALL_A", 1, K.WALL, along_x(0.0, L1, _rect(-b, -a, 0.0, H))),
                E("S1_WALL_B", 1, K.WALL, along_x(0.0, L1, _rect(a, b, 0.0, H)))]
    else:
        # 첫 구간: 슬래브·바깥쪽 벽(A, 꺾는 반대쪽)은 모서리 바깥까지, 꺾는 쪽 벽(B)은 두 번째 구간 벽 앞까지
        floor = along_x(0.0, L1 + b, _rect(-b, b, -ft, 0.0))
        roof = along_x(0.0, L1 + b, _rect(-b, b, H, H + rt))
        if bot_h:
            floor += along_x(0.0, L1 + a, _haunch_bottom(-a, 1, bh_w, bh_h)) + along_x(0.0, L1 - a, _haunch_bottom(a, -1, bh_w, bh_h))
        if top_h:
            roof += along_x(0.0, L1 + a, _haunch_top(-a, 1, th_w, th_h, H)) + along_x(0.0, L1 - a, _haunch_top(a, -1, th_w, th_h, H))
        els += [E("S1_FLOOR", 1, K.FLOOR, floor), E("S1_ROOF", 1, K.ROOF, roof),
                E("S1_WALL_A", 1, K.WALL, along_x(0.0, L1 + b, _rect(-b, -a, 0.0, H))),
                E("S1_WALL_B", 1, K.WALL, along_x(0.0, L1 - b, _rect(a, b, 0.0, H)))]
        # 두 번째 구간 (단면 좌표 = X): 바깥 벽(OUT)은 모서리를 지나 끝까지, 안쪽 벽(IN)은 첫 구간 내공 끝(Y = a)부터
        floor2 = along_y(b, L2, _rect(L1 - b, L1 + b, -ft, 0.0))
        roof2 = along_y(b, L2, _rect(L1 - b, L1 + b, H, H + rt))
        if bot_h:
            floor2 += along_y(-a + bh_w, L2, _haunch_bottom(L1 + a, -1, bh_w, bh_h)) + along_y(a, L2, _haunch_bottom(L1 - a, 1, bh_w, bh_h))
        if top_h:
            roof2 += along_y(-a + th_w, L2, _haunch_top(L1 + a, -1, th_w, th_h, H)) + along_y(a, L2, _haunch_top(L1 - a, 1, th_w, th_h, H))
        els += [E("S2_FLOOR", 2, K.FLOOR, floor2), E("S2_ROOF", 2, K.ROOF, roof2),
                E("S2_WALL_OUT", 2, K.WALL, along_y(-a, L2, _rect(L1 + a, L1 + b, 0.0, H))),
                E("S2_WALL_IN", 2, K.WALL, along_y(a, L2, _rect(L1 - b, L1 - a, 0.0, H)))]

    fl = st.floor_level(k)
    opening = (name, k, spec.side, sc - a, sc + a, fl, fl + H)
    return PassageLayout(name=name, spec=spec, floor=k, frame=frame, z_floor=z0, elements=els, wall_opening=opening)
