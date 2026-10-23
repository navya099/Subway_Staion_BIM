"""선형을 따라 놓이는 각기둥 부재(벽체 · 슬래브 · 승강장 · 지지벽체)의 공통 기하.

부재 = (s 구간) x (t 구간) x (연직 치수). 중심 좌표 pos_x(s), pos_y(t) 와 shape.length / width / vertical 로 정의하고,
하단 표고는 선형 표고를 따른다:  z(s) = lv(s) - offset + z_off,  z_off = pos_z - (lv(pos_x) - offset).

직선 선형이면 부재는 단일 각기둥(표본 측점 2개)이고, 곡선이면 선형을 따라 표본 측점마다 단면(링)을 만들어 이은 스윕이다.
"""

from helper.geometry_helper import CommonHelper
from helper.view_item import ViewItem


def s_range(m) -> tuple[float, float]:
    return m.pos_x - m.shape.length / 2.0, m.pos_x + m.shape.length / 2.0


def t_range(m) -> tuple[float, float]:
    return m.pos_y - m.shape.width / 2.0, m.pos_y + m.shape.width / 2.0


def z_off(cfg, m) -> float:
    return m.pos_z - (cfg.lv(m.pos_x) - cfg.station.offset)


def z_at(cfg, m, s: float) -> float:
    """측점 s 에서의 부재 하단 표고"""
    return cfg.lv(s) - cfg.station.offset + z_off(cfg, m)


def corners(cfg, m) -> tuple[float, float, float, float, float, float]:
    """(s0, s1, t0, t1, z_bot(s0), z_bot(s1)) - 구간 양 끝의 하단 표고 (곡선 종단에서는 현 기준)"""
    s0, s1 = s_range(m)
    t0, t1 = t_range(m)
    return s0, s1, t0, t1, z_at(cfg, m, s0), z_at(cfg, m, s1)


def samples(cfg, m) -> list[float]:
    s0, s1 = s_range(m)
    return cfg.sample_s(s0, s1)


def curve_factor(cfg, s0: float, s1: float, t_center: float) -> float:
    """(1/L) ∫ (1 - κ(s)·t) ds : 곡선에서 중심선 길이가 t 만큼 떨어진 부재의 체적 보정 (직선 = 1.0)"""
    xs = cfg.sample_s(s0, s1)
    if cfg.align.is_straight:
        return 1.0
    total = 0.0
    for a, b in zip(xs, xs[1:]):
        total += (b - a) * (1.0 - 0.5 * (cfg.curvature_at(a) + cfg.curvature_at(b)) * t_center)
    return total / (s1 - s0)


# ---------------- 2D ----------------
def section_rect(cfg, m, sta: float):
    """측점 sta 의 횡단면이 부재를 자르면 (t0, t1, z_bot) 아니면 None"""
    s0, s1 = s_range(m)
    if not CommonHelper.cut_by_s(sta, s0, s1, cfg.station.length):
        return None
    t0, t1 = t_range(m)
    return t0, t1, z_at(cfg, m, sta)


def cut_by_centerline(m) -> bool:
    """종단면(선형 중심 t=0)이 부재를 자르는가"""
    t0, t1 = t_range(m)
    return CommonHelper.cut_by_t(t0, t1)


def profile_view(cfg, m, layer: str, **kw) -> ViewItem:
    """종단면 윤곽: 직선이면 평행사변형(병합 가능), 곡선이면 선형 표고를 따르는 다각형"""
    xs = samples(cfg, m)
    v = m.shape.vertical
    if len(xs) == 2:
        s0, s1, _, _, z0, z1 = corners(cfg, m)
        return ViewItem.sloped(m.name, layer, s0, s1, z0, z1, v, **kw)
    bottom = [(s, z_at(cfg, m, s)) for s in xs]
    top = [(s, z + v) for s, z in reversed(bottom)]
    kw.pop("merge", None)
    return ViewItem(m.name, layer, u0=xs[0], u1=xs[-1], pts=bottom + top, **kw)


# ---------------- 3D ----------------
def rings(cfg, m) -> list[list[tuple[float, float, float]]]:
    """표본 측점마다의 단면 링: [t0 하단, t1 하단, t1 상단, t0 상단] (WCS 좌표)"""
    t0, t1 = t_range(m)
    v = m.shape.vertical
    out = []
    for s in samples(cfg, m):
        zb = z_at(cfg, m, s)
        (xa, ya), (xb, yb) = cfg.to_world(s, t0), cfg.to_world(s, t1)
        out.append([(xa, ya, zb), (xb, yb, zb), (xb, yb, zb + v), (xa, ya, zb + v)])
    return out


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _mean(pts):
    n = len(pts)
    return tuple(sum(p[i] for p in pts) / n for i in range(3))


def _outward(quad, ref):
    """quad 의 법선이 ref(부재 안쪽 기준점)에서 멀어지는 방향이 되도록 꼭짓점 순서를 맞춤"""
    n = _cross(_sub(quad[1], quad[0]), _sub(quad[3], quad[0]))
    d = _sub(_mean(quad), ref)
    return quad if sum(n[i] * d[i] for i in range(3)) >= 0 else tuple(reversed(quad))


def sweep_quads(rs) -> list[tuple]:
    """링 목록을 이은 닫힌 각기둥 스윕의 바깥쪽 사각 면 (구간별 4면 + 양 끝 마개 2면)"""
    quads = []
    for r0, r1 in zip(rs, rs[1:]):
        ref = _mean(r0 + r1)
        for quad in ((r0[0], r1[0], r1[1], r0[1]),     # 하면
                     (r0[3], r0[2], r1[2], r1[3]),     # 상면
                     (r0[0], r0[3], r1[3], r1[0]),     # t0 측면
                     (r0[1], r1[1], r1[2], r0[2])):    # t1 측면
            quads.append(_outward(quad, ref))
    # 마개 면은 인접한 첫/끝 구간의 안쪽 점을 기준으로 방향을 정함 (부재 전체 평균점은 급곡선에서 부재 밖에 놓일 수 있음)
    quads.append(_outward(tuple(rs[0]), _mean(rs[0] + rs[1])))
    quads.append(_outward(tuple(rs[-1]), _mean(rs[-2] + rs[-1])))
    return quads


def mesh_faces(cfg, m) -> list[tuple]:
    """DXF 3DFACE 용 면. 직선은 기존과 같은 6면 각기둥, 곡선은 스윕 면"""
    if len(samples(cfg, m)) == 2:
        s0, s1, t0, t1, z0, z1 = corners(cfg, m)
        v = m.shape.vertical
        return CommonHelper.create_sloped_box_faces_global(s0, s1, t0, t1, z0, z1, z0 + v, z1 + v, cfg.to_world)
    return sweep_quads(rings(cfg, m))


def mesh_volume(quads) -> float:
    """닫힌 면 집합의 체적 (발산 정리). 면이 바깥 방향이면 양수"""
    total = 0.0
    for q in quads:
        for tri in ((q[0], q[1], q[2]), (q[0], q[2], q[3])):
            c = _cross(tri[1], tri[2])
            total += sum(tri[0][i] * c[i] for i in range(3))
    return total / 6.0
