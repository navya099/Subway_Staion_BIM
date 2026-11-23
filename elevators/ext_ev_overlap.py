"""외부 엘리베이터 겹침 검사 (평면이 아니라 실제 입체): 출입구 · 출구통로 · 환기구 · 정거장 본체 · 다른 외부 엘리베이터.

모든 대상을 세계 좌표 볼록 다면체(면 목록)로 바꿔 분리축 정리로 겹침을 판정 — 위아래로 떨어져 있거나 면끼리 맞닿은 것은 겹침이 아님.
- 외부 엘리베이터 = 외곽 상자(피트 슬래브 하면 ~ 지붕 — 승강로 속 빈 곳 포함) + 밖으로 나온 부재(캐노피·루버·지붕판·기단·경사로·턱·난간)
- 출입구 = 박스 부재·쐐기·헌치·캐노피 + 속 공간(측벽 사이, 바닥 ~ 측벽 윗면), 출구통로 = 구간마다 외곽 단면 전체(속 공간 포함),
  환기구 = 부재 조각, 본체 = 층마다 외곽 상자(단부 벽 포함, 구조물 확폭이면 2m 구간마다 바깥면)
"""
import numpy as np

from helper.box_piece import BoxPiece
from helper.strip_member import Strip, strip_faces

TOL = 1e-3          # 이보다 얕은 겹침(맞닿음·곡선 근사 오차)은 무시 (m)


class Convex:
    """볼록 다면체: 꼭짓점, 면 법선, 모서리 방향, 외접 상자"""

    def __init__(self, label: str, faces):
        self.label = label
        fs = [np.asarray(f, dtype=float) for f in faces]
        self.pts = np.unique(np.round(np.concatenate(fs), 9), axis=0)
        self.lo, self.hi = self.pts.min(axis=0), self.pts.max(axis=0)
        nrm, edg = [], []
        for f in fs:
            n = np.zeros(3)
            for i in range(len(f)):                                # Newell (퇴화한 앞 두 변에도 안전)
                a, b = f[i], f[(i + 1) % len(f)]
                n += np.cross(a - f[0], b - f[0])
                edg.append(b - a)
            nrm.append(n)
        self.normals, self.edges = _unique_dirs(nrm), _unique_dirs(edg)


def _unique_dirs(vs) -> np.ndarray:
    out = []
    for v in vs:
        ln = np.linalg.norm(v)
        if ln < 1e-9:
            continue
        u = v / ln
        if not any(abs(abs(float(u @ w)) - 1.0) < 1e-9 for w in out):
            out.append(u)
    return np.array(out)


def overlaps(a: Convex, b: Convex, tol: float = TOL) -> bool:
    """두 볼록 다면체가 tol 보다 깊게 겹치는가 (분리축 정리)"""
    if np.any(a.lo > b.hi - tol) or np.any(b.lo > a.hi - tol):
        return False
    cr = np.cross(a.edges[:, None, :], b.edges[None, :, :]).reshape(-1, 3)
    ln = np.linalg.norm(cr, axis=1)
    cr = cr[ln > 1e-6] / ln[ln > 1e-6][:, None]
    ax = np.concatenate([a.normals, b.normals, cr])
    pa, pb = a.pts @ ax.T, b.pts @ ax.T
    gap = np.minimum(pa.max(axis=0), pb.max(axis=0)) - np.maximum(pa.min(axis=0), pb.min(axis=0))
    return bool(np.all(gap > tol))


def _strip(label, frame, st, t0, t1) -> Convex:
    return Convex(label, strip_faces(frame, st, t0, t1))


_OUT = {"CANOPY", "LOUVER", "ROOF"}       # 외곽 상자 밖으로 나오는 띠 부재 (기단·경사로·턱·난간은 조각)

_INSIDE = {"COLUMN", "GIRT"}              # 승강로 상자 안 조각


def ev_solids(lay) -> list:
    U0, U1, T0, T1 = lay.outer
    z0 = min(st.zb0 for p in lay.parts if p.kind == "PIT_SLAB" for st in p.strips)
    z1 = max(st.zt for p in lay.parts if p.kind == "ROOF" for st in p.strips)
    out = [_strip("승강로", lay.frame, Strip(U0, U1, z0, z0, z1), T0, T1)]
    for p in lay.parts:
        if p.kind in _OUT:
            out += [_strip(p.code, lay.frame, st, *p.t_range) for st in p.strips]
        if p.kind not in _INSIDE:
            out += [Convex(p.code, h.faces()) for h in p.pieces]
    return out


def entrance_solids(lay) -> list:
    out = []
    for p in list(lay.box_parts) + list(lay.canopy):
        out += [_strip(p.code, lay.frame, st, *p.t_range) for st in p.strips]
        out += [Convex(p.code, q.faces()) for q in p.pieces]
        if p.code.startswith("WALL_L"):                            # 속 공간 (+t 측벽 안쪽 면 ~ 대칭)
            a = p.t_range[0]
            out += [_strip("내부", lay.frame, st, -a, a) for st in p.strips]
    return out + [Convex("HAUNCH", h.faces()) for h in lay.haunches]


def passage_solids(lay) -> list:
    sp = lay.spec
    sect = [(-sp.half_out, -sp.floor_t), (sp.half_out, -sp.floor_t), (sp.half_out, sp.inner_height + sp.roof_t),
            (-sp.half_out, sp.inner_height + sp.roof_t)]
    return [Convex(f"구간 {sg.index + 1}", BoxPiece(sg.x, sg.y, sg.ux, sg.uy, 0.0, sg.length, sect, sg.z, sg.slope, sg.tp, -sg.tn).faces())
            for sg in lay.segments]


def station_solids(cfg) -> list:
    """본체: 층마다 바깥면까지의 상자 (바닥 슬래브 하면 ~ 천장 슬래브 상면, 단부 벽 포함)"""
    from config.widening import outer_at
    st = cfg.station
    out = []
    for n in range(1, st.floors + 1):
        w = st.wall_t_at(n)
        z0 = -st.floor_t if n == 1 else st.floor_level(n)
        z1 = st.floor_level(n + 1)
        ss = cfg.sample_s(-w, st.length + w)
        if cfg.widenings:
            k = max(1, int((st.length + 2 * w) // 2.0))
            ss = sorted(set(ss) | {-w + (st.length + 2 * w) * i / k for i in range(k + 1)})
        for a, b in zip(ss, ss[1:]):
            lim = {}
            for sd in (1, -1):
                lim[sd] = max(outer_at(cfg, n, sd, s) for s in (a, b)) if cfg.widenings else st.width / 2.0 + w
            ring = []
            for s in (a, b):
                fl = cfg.lv(s) - st.offset
                for t in (-lim[-1], lim[1]):
                    x, y = cfg.to_world(s, t)
                    ring += [(x, y, fl + z0), (x, y, fl + z1)]
            p = ring                                               # (a,-),(a,+),(b,-),(b,+) 의 아래·위
            faces = [(p[0], p[2], p[6], p[4]), (p[1], p[3], p[7], p[5]), (p[0], p[1], p[3], p[2]), (p[4], p[5], p[7], p[6]),
                     (p[0], p[1], p[5], p[4]), (p[2], p[3], p[7], p[6])]
            out.append(Convex(st.level_name(n), faces))
    return out


def _hit(mine, others):
    for a in mine:
        for b in others:
            if overlaps(a, b):
                return a.label, b.label
    return None


def check_ext_ev_overlaps(cfg, layouts: list):
    """외부 엘리베이터가 다른 구조물과 입체로 겹치면 오류 (높이가 떨어져 있거나 맞닿은 것은 허용)"""
    if not layouts:
        return
    targets = [("정거장 본체", station_solids(cfg))]
    targets += [(f"출구통로 {p.name}", passage_solids(p)) for p in cfg.passage_layouts()]
    targets += [(f"출입구 {e.name}", entrance_solids(e)) for e in cfg.entrance_layouts()]
    targets += [(f"환기구 {v.name}", [Convex("덕트", q.faces()) for q in v.pieces()]) for v in cfg.vent_layouts()]
    solids = [(x.name, ev_solids(x)) for x in layouts]
    for i, (name, mine) in enumerate(solids):
        for what, others in targets + [(f"외부 엘리베이터 {n}", s) for n, s in solids[:i]]:
            hit = _hit(mine, others)
            if hit:
                raise ValueError(f"외부 엘리베이터 {name}: {hit[0]} 이(가) {what} ({hit[1]}) 와(과) 겹칩니다")
