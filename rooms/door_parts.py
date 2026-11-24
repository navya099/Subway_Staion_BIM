"""실 문의 형상: 문틀(벽 마감 표면까지 감싸는 틀) · 문짝(양개·자동문은 두 짝) · 레버 손잡이 · 문턱, 그리고 문짝의 움직임(웹 뷰어 애니메이션).

모두 닫힌 상태의 정거장 로컬 상자 (s0, s1, t0, t1, z0, z1) — FL 기준 높이. 문 좌표 (u, v): u = 벽 방향, v = 벽 직교 방향
(±t 변의 문은 u = s, v = t / ±s 변의 문은 u = t, v = s).
- 폭·높이 = 벽 개구부(문틀 바깥) 치수, 높이는 바닥 마감면부터. 문틀은 개구부 안쪽에 폭 FRAME_W, 깊이 = 양쪽 벽 마감 표면 + FRAME_LIP
- 여닫이·방화문·양개: 문짝은 열리는 쪽 마감 표면과 같은 면, 경첩 축 = 그 면의 문틀 안쪽 모서리 (90° 열림)
- 미닫이: 열리는 쪽 벽면 바깥에 걸린 한 짝, 경첩 쪽으로 밀림 / 자동문: 같은 자리의 유리 두 짝이 양옆으로, 위에 구동부
- 경첩 hinge: 실 안에서 문을 볼 때 'left' | 'right', None = 좌표가 작은 쪽 (s 또는 t)
- 열림 swing: 'in' 실 안쪽 | 'out' 실 바깥쪽
"""
from dataclasses import dataclass, field

FRAME_W = 0.04                   # 문틀 폭 (개구부 안쪽)
FRAME_LIP = 0.01                 # 문틀이 벽 마감 표면에서 나온 거리
LEAF_T = 0.05                    # 문짝 두께
GAP = 0.004                      # 문짝 둘레 틈
BOTTOM = 0.008                   # 문짝 아래 틈
SLIDE_GAP = 0.02                 # 미닫이·자동문 문짝과 문틀 사이
SLIDE_OVER = 0.03                # 미닫이·자동문 문짝이 개구부보다 큰 폭 (한쪽)
AUTO_HEAD_H, AUTO_HEAD_D = 0.15, 0.14      # 자동문 구동부 높이·깊이
AUTO_STILE = 0.05                # 자동문 문짝 유리 둘레 틀
HANDLE_Z = 1.0                   # 손잡이 높이 (바닥 마감면 기준)
MIN_W, MIN_H = 0.6, 1.5          # 문 최소 폭·높이
IN, OUT = "in", "out"
SWINGS = (IN, OUT)
HINGES = (None, "left", "right")
AUTO = "자동문"
SLIDE = "미닫이"
DOUBLE = "양개 여닫이"


@dataclass
class DoorPart:
    """부재 1개. code = FRAME | SILL | LEAF | GLASS | HANDLE | HEADER, leaf = 움직이는 문짝 번호 (0 = 고정)"""
    code: str
    box: tuple
    leaf: int = 0


@dataclass
class DoorMotion:
    """문짝 1짝의 움직임: kind 'swing' = (s, t) 축 pivot 둘레로 angle 도(왼쪽 회전 +), 'slide' = (ds, dt) 만큼 이동"""
    leaf: int
    kind: str
    pivot: tuple = (0.0, 0.0)
    angle: float = 0.0
    move: tuple = (0.0, 0.0)


@dataclass
class DoorShape:
    parts: list = field(default_factory=list)
    motions: list = field(default_factory=list)
    symbol: list = field(default_factory=list)       # 평면 기호 폴리곤 [(s, t)]
    operation: str = "SINGLE_SWING_LEFT"


def along_s(side: str) -> bool:
    return side in ("+t", "-t")


def in_sign(side: str) -> int:
    """실 안쪽 방향 (v 축 부호)"""
    return -1 if side in ("+s", "+t") else 1


def hinge_low(side: str, hinge) -> bool:
    """경첩이 좌표(u)가 작은 쪽인가. left/right 는 실 안에서 문을 보는 사람 기준"""
    if hinge is None:
        return True
    left_low = side in ("+t", "-s")              # +t 를 보면 왼쪽 = −s, −s 를 보면 왼쪽 = −t
    return (hinge == "left") == left_low


def door_shape(d, f_in: float = 0.0, f_out: float = 0.0) -> DoorShape:
    """DoorLayout d → 부재·움직임·평면 기호. f_in / f_out = 실 안쪽·바깥쪽 벽 구조면 → 마감 표면 거리"""
    import math
    o = d.opening
    s_dir = along_s(d.side)
    a, b = (o[0], o[1]) if s_dir else (o[2], o[3])
    c0, c1 = (o[2], o[3]) if s_dir else (o[0], o[1])
    z0, top = o[4], o[5]
    zb = z0 + d.ffl
    si = in_sign(d.side)
    f_lo, f_hi = (f_in, f_out) if si < 0 else (f_out, f_in)
    v0, v1 = c0 - f_lo, c1 + f_hi                          # 양쪽 벽 마감 표면
    so = si if d.swing == IN else -si                      # 열리는 쪽
    vf = v1 if so > 0 else v0
    out = DoorShape()

    def box(u0, u1, w0, w1, za, zc):
        w0, w1 = min(w0, w1), max(w0, w1)
        u0, u1 = min(u0, u1), max(u0, u1)
        return (u0, u1, w0, w1, za, zc) if s_dir else (w0, w1, u0, u1, za, zc)

    def st(u, v):
        return (u, v) if s_dir else (v, u)

    def add(code, leaf, *q):
        out.parts.append(DoorPart(code, box(*q), leaf))
    lip0, lip1 = v0 - FRAME_LIP, v1 + FRAME_LIP
    ua, ub, zt = a + FRAME_W, b - FRAME_W, top - FRAME_W
    add("FRAME", 0, a, ua, lip0, lip1, zb, top)
    add("FRAME", 0, ub, b, lip0, lip1, zb, top)
    add("FRAME", 0, ua, ub, lip0, lip1, zt, top)
    if d.ffl > 1e-9:
        add("SILL", 0, a, b, c0, c1, z0, zb)
    low = hinge_low(d.side, d.hinge)
    at = lambda off: vf + so * off                         # 열리는 쪽 마감 표면에서 바깥으로 off

    def left_of_opening(hu):
        """열리는 방향을 볼 때 u 부호 hu 쪽이 왼쪽인가 (IFC OperationType)"""
        # 열림 방향 e = so·v축. 왼쪽 = e 를 +90° 돌린 방향
        lx = (-so, 0.0) if s_dir else (0.0, so)            # s_dir: e = (0, so) → (−so, 0) / 아니면 e = (so, 0) → (0, so)
        comp = lx[0] if s_dir else lx[1]
        return comp * hu > 0

    def lever(leaf, edge, toward):
        """레버 손잡이 (양면): edge = 손잡이 중심 u, toward = 레버가 뻗는 방향(경첩 쪽)"""
        zc = zb + HANDLE_Z
        for face, sg in ((vf, so), (vf - so * LEAF_T, -so)):
            add("HANDLE", leaf, edge - 0.025, edge + 0.025, face, face + sg * 0.008, zc - 0.08, zc + 0.08)
            add("HANDLE", leaf, edge - 0.01, edge + 0.01, face + sg * 0.008, face + sg * 0.04, zc - 0.01, zc + 0.01)
            add("HANDLE", leaf, edge - toward * 0.01, edge + toward * 0.13, face + sg * 0.04, face + sg * 0.058, zc - 0.01, zc + 0.01)

    def swing_leaf(leaf, u0, u1, at_low):
        add("LEAF", leaf, u0, u1, vf - so * LEAF_T, vf, zb + BOTTOM, zt - GAP)
        hu, dr = (u0, 1.0) if at_low else (u1, -1.0)
        lever(leaf, (u1 if at_low else u0) - dr * 0.07, -dr)
        out.motions.append(DoorMotion(leaf, "swing", pivot=st(hu, vf), angle=90.0 * dr * so * (1.0 if s_dir else -1.0)))
        w = u1 - u0
        out.symbol.append([st(hu, vf)] + [st(hu + dr * w * math.cos(math.radians(k * 15)), vf + so * w * math.sin(math.radians(k * 15)))
                                           for k in range(7)])

    if d.kind == AUTO:
        mid, t = (a + b) / 2.0, 0.04
        w0, w1 = at(FRAME_LIP + SLIDE_GAP), at(FRAME_LIP + SLIDE_GAP + t)
        zl, zh = zb + BOTTOM, top + SLIDE_OVER - GAP
        for leaf, (u0, u1), dr in ((1, (a - SLIDE_OVER, mid - GAP / 2), -1.0), (2, (mid + GAP / 2, b + SLIDE_OVER), 1.0)):
            s, kick = AUTO_STILE, 0.1
            add("LEAF", leaf, u0, u0 + s, w0, w1, zl, zh)
            add("LEAF", leaf, u1 - s, u1, w0, w1, zl, zh)
            add("LEAF", leaf, u0 + s, u1 - s, w0, w1, zl, zl + kick)
            add("LEAF", leaf, u0 + s, u1 - s, w0, w1, zh - s, zh)
            m = (w0 + w1) / 2.0
            add("GLASS", leaf, u0 + s, u1 - s, m - 0.005, m + 0.005, zl + kick, zh - s)
            mv = dr * ((b - a) / 2.0 - 0.02)
            out.motions.append(DoorMotion(leaf, "slide", move=st(mv, 0.0)))
            out.symbol.append([st(u0, w0), st(u1, w0), st(u1, w1), st(u0, w1)])
        half = (b - a) / 2.0
        add("HEADER", 0, a - half, b + half, vf, at(AUTO_HEAD_D), top + SLIDE_OVER, top + SLIDE_OVER + AUTO_HEAD_H)
        out.operation = "DOUBLE_DOOR_SLIDING"
    elif d.kind == SLIDE:
        u0, u1 = a - SLIDE_OVER, b + SLIDE_OVER
        w0, w1 = at(FRAME_LIP + SLIDE_GAP), at(FRAME_LIP + SLIDE_GAP + LEAF_T)
        add("LEAF", 1, u0, u1, w0, w1, zb + BOTTOM, top + SLIDE_OVER)
        dr = -1.0 if low else 1.0                          # 경첩 쪽으로 밀림
        edge = (u1 - 0.06) if low else (u0 + 0.06)
        add("HANDLE", 1, edge - 0.015, edge + 0.015, w1, w1 + so * 0.03, zb + HANDLE_Z - 0.15, zb + HANDLE_Z + 0.15)
        out.motions.append(DoorMotion(1, "slide", move=st(dr * (ub - ua + FRAME_W), 0.0)))
        out.symbol.append([st(u0, w0), st(u1, w0), st(u1, w1), st(u0, w1)])
        out.operation = "SLIDING_TO_LEFT" if left_of_opening(dr) else "SLIDING_TO_RIGHT"
    elif d.kind == DOUBLE:
        mid = (ua + ub) / 2.0
        swing_leaf(1, ua + GAP, mid - GAP / 2, True)
        swing_leaf(2, mid + GAP / 2, ub - GAP, False)
        out.operation = "DOUBLE_DOOR_SINGLE_SWING"
    else:
        swing_leaf(1, ua + GAP, ub - GAP, low)
        out.operation = "SINGLE_SWING_LEFT" if left_of_opening(-1.0 if low else 1.0) else "SINGLE_SWING_RIGHT"
    return out
