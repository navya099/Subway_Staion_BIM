"""미리보기 작도 (화면 비의존): 도면 DXF 문서를 matplotlib Axes 에 그림.

2D(평면·종단·횡단)는 StationCADEngine.build_*_doc 이 만든 DXF 문서를 ezdxf drawing 으로 그대로 그리고,
3D 는 3D DXF 문서의 3DFACE 를 레이어별 Poly3DCollection 으로 그린다.
도면 파일과 같은 문서를 쓰므로 미리보기 = 출력 도면 (기하를 따로 계산하지 않음).
"""
from dataclasses import dataclass, field

import numpy as np
from ezdxf.colors import aci2rgb

from config.cadconfig import LAYER_DEFINITIONS
from config.master_config import StationProjectConfig

PREVIEW_FONT = "malgun.ttf"      # 한글 글자(실 이름 등)가 깨지지 않게 미리보기 문서의 기본 글꼴만 바꿈

# 3D 표시 묶음: (이름, 레이어, 기본 표시). 천장틀은 면이 매우 많아 기본으로 끔
LAYER_GROUPS = [
    ("구조체", ("STRUCT_WALL", "STRUCT_SLAB", "STRUCT_PLATFORM", "STRUCT_COLUMN"), True),
    ("계단·ESC·EV", ("STRUCT_STAIR", "STRUCT_ESCALATOR", "STRUCT_ELEVATOR", "STRUCT_ELEVATOR_CAR"), True),
    ("통로·출입구·환기구", ("STRUCT_PASSAGE", "STRUCT_ENTRANCE", "STRUCT_VENT", "STRUCT_GRILL"), True),
    ("칸막이·문", ("STRUCT_PARTITION", "STRUCT_SEPARATION", "STRUCT_DOOR"), True),
    ("바닥·벽 마감", ("FIN_FLOOR", "FIN_WALL"), True),
    ("천장판", ("FIN_CEILING",), False),
    ("천장틀", ("FIN_FRAME",), False),
]


def group_names() -> list:
    return [g[0] for g in LAYER_GROUPS]


def default_groups() -> set:
    return {name for name, _, on in LAYER_GROUPS if on}


def layers_of(groups) -> set:
    """표시 묶음 이름들 → 레이어 이름 집합"""
    return {ly for name, layers, _ in LAYER_GROUPS if name in groups for ly in layers}


def layer_rgb(layer: str) -> tuple:
    """레이어 색 (0~1 RGB). 흰색(7)·검정은 회색으로"""
    aci = LAYER_DEFINITIONS.get(layer, {}).get("color", 8)
    if aci in (0, 7):
        aci = 9
    r, g, b = aci2rgb(aci)
    return r / 255.0, g / 255.0, b / 255.0


# ================================================================== 2D
def use_preview_font(doc):
    """미리보기용 문서의 글꼴을 한글 글꼴로 (저장할 도면에는 쓰지 않음)"""
    style = doc.styles.get("Standard")
    if style is not None:
        style.dxf.font = PREVIEW_FONT
    return doc


def draw_doc_2d(ax, doc):
    """DXF 문서의 모델스페이스를 Axes 에 그림 (ezdxf drawing, CAD 와 같은 어두운 배경)"""
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    fig = ax.figure
    size = fig.get_size_inches().copy()                # ezdxf 가 그림 크기를 도면 비율로 바꾸므로 창 크기로 되돌림
    ax.clear()
    ax.set_axis_off()
    use_preview_font(doc)
    Frontend(RenderContext(doc), MatplotlibBackend(ax)).draw_layout(doc.modelspace(), finalize=True)
    fig.set_size_inches(size, forward=False)
    ax.set_aspect("equal", adjustable="datalim")


# ================================================================== 3D
@dataclass
class Mesh3D:
    """3D 미리보기 자료 (원점 기준 상대 좌표, m)
    faces: 레이어 → 면 목록. 면 = np.ndarray (n, 5) — 꼭짓점마다 (x, y, z, s, h):
    s = 정거장 로컬 거리 근사, h = 그 s 의 본체 FL 기준 높이 (config 를 주었을 때만 계산, 아니면 nan) — 범위·층 잘라 보기용"""
    origin: tuple
    faces: dict = field(default_factory=dict)
    alignment: list = field(default_factory=list)

    @property
    def count(self) -> int:
        return sum(len(v) for v in self.faces.values())

    def select(self, layers, s_range=None, h_max=None) -> dict:
        """보일 면: 레이어 → 면 목록 (n, 3). s_range = (s0, s1) 정거장 로컬 구간, h_max = FL 기준 이 높이 위는 잘라냄.
        걸친 면은 그 경계에서 잘라 남김 (긴 벽·슬래브도 구간만큼만 보임)"""
        cuts = []
        if s_range is not None:
            cuts += [(3, s_range[0], -1.0), (3, s_range[1], 1.0)]
        if h_max is not None:
            cuts.append((4, h_max, 1.0))
        out = {}
        for ly, fs in self.faces.items():
            if ly not in layers or not fs:
                continue
            sel = []
            for f in fs:
                for col, lim, sign in cuts:
                    if np.isnan(f[0, col]):
                        continue
                    f = _clip(f, col, lim, sign)
                    if f is None:
                        break
                if f is not None:
                    sel.append(f[:, :3])
            if sel:
                out[ly] = sel
        return out


def _clip(f, col, lim, sign):
    """다각형 f (n, k) 를 sign·(f[:, col] − lim) ≤ 0 쪽만 남기도록 자름 (Sutherland–Hodgman, 열 값은 선형 보간). 다 잘리면 None"""
    d = sign * (f[:, col] - lim)
    if (d > -1e-6).all():                     # 경계면 위에 놓인 면(잘린 슬래브 하면 등)도 버림
        return None
    if (d <= 1e-6).all():
        return f
    out = []
    n = len(f)
    for i in range(n):
        a, b, da, db = f[i], f[(i + 1) % n], d[i], d[(i + 1) % n]
        if da <= 0:
            out.append(a)
        if (da < 0 < db) or (db < 0 < da):
            out.append(a + (b - a) * (da / (da - db)))
    return np.array(out) if len(out) >= 3 else None


def station_of(cfg, pts_xy: np.ndarray, lo: float, hi: float):
    """세계 평면 좌표 → 정거장 로컬 s 근사 (1m 간격 중심선 표본 중 가장 가까운 점 + 접선 방향 투영)"""
    ss = np.arange(lo, hi + 1e-9, 1.0)
    c = np.array([cfg.to_world(s, 0.0) for s in ss])
    th = np.array([cfg.theta_at(s) for s in ss])
    out = np.empty(len(pts_xy))
    for i0 in range(0, len(pts_xy), 2000):                 # 메모리 절약: 2000 개씩
        p = pts_xy[i0:i0 + 2000]
        d2 = ((p[:, None, :] - c[None, :, :]) ** 2).sum(axis=2)
        k = d2.argmin(axis=1)
        dv = p - c[k]
        out[i0:i0 + 2000] = ss[k] + dv[:, 0] * np.cos(th[k]) + dv[:, 1] * np.sin(th[k])
    return out


def mesh_from_doc(doc, cfg=None) -> Mesh3D:
    """3D DXF 문서 → Mesh3D. 3DFACE 의 넷째 꼭짓점이 셋째와 같으면 삼각형. 세계 좌표가 커서 정수 원점 기준 상대 좌표로.
    cfg 를 주면 꼭짓점마다 정거장 로컬 s·FL 기준 높이를 계산 (잘라 보기용)"""
    raw, align = {}, []
    for e in doc.modelspace():
        kind = e.dxftype()
        if kind == "3DFACE":
            d = e.dxf
            v = [tuple(d.vtx0), tuple(d.vtx1), tuple(d.vtx2), tuple(d.vtx3)]
            if v[3] == v[2]:
                v = v[:3]
            raw.setdefault(d.layer, []).append(v)
        elif kind == "POLYLINE" and e.dxf.layer == "ALIGNMENT_CL":
            align = [tuple(p) for p in e.points()]
    first = next((fs[0][0] for fs in raw.values() if fs), (align[0] if align else (0.0, 0.0, 0.0)))
    o = np.floor(np.array(first, dtype=float))
    mesh = Mesh3D(origin=tuple(o), alignment=[np.asarray(p, dtype=float) - o for p in align])
    if not raw:
        return mesh
    if cfg is not None:
        a, base = cfg.align, cfg.station.start_station
        lo = max(a.start_station, base - 300.0) - base
        hi = min(a.end_station, base + cfg.station.length + 300.0) - base
        sq = np.arange(lo, hi + 1e-9, 1.0)
        flq = np.array([cfg.lv(x) for x in sq]) - cfg.station.offset
    for ly, fs in raw.items():
        sizes = [len(f) for f in fs]
        pts = np.array([p for f in fs for p in f], dtype=float)
        ext = np.full((len(pts), 5), np.nan)
        ext[:, :3] = pts - o
        if cfg is not None:
            s = station_of(cfg, pts[:, :2], lo, hi)
            ext[:, 3] = s
            ext[:, 4] = pts[:, 2] - np.interp(s, sq, flq)
        k, out = 0, []
        for n in sizes:
            out.append(ext[k:k + n])
            k += n
        mesh.faces[ly] = out
    return mesh


def draw_mesh_3d(ax, mesh: Mesh3D, layers, s_range=None, h_max=None, transparent=False, keep_view=False):
    """Mesh3D 를 3D Axes 에 그림 (잘라 보기: Mesh3D.select). transparent = 슬래브·벽·승강장 반투명 (천장판은 늘 반투명).
    keep_view = 시점(elev/azim)·범위 유지. 그린 면 개수를 돌려줌"""
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    view = (ax.elev, ax.azim, ax.get_xlim3d(), ax.get_ylim3d(), ax.get_zlim3d()) if keep_view else None
    ax.clear()
    shown = mesh.select(layers, s_range, h_max)
    see_through = {"STRUCT_SLAB", "STRUCT_WALL", "FIN_CEILING", "STRUCT_PLATFORM"} if transparent else {"FIN_CEILING"}
    polys, fc, ec = [], [], []
    for ly, fs in shown.items():                    # 면 하나하나 깊이 정렬되도록 한 컬렉션에 모두 넣음 (레이어별로 나누면 앞뒤가 틀림)
        rgb = np.array(layer_rgb(ly)) * 0.75 + 0.25 * 0.6     # 원색을 조금 누그러뜨림
        alpha = 0.25 if ly in see_through else 1.0
        for f in fs:
            shade = _shade(f)
            for q in _tiles(f):                     # 큰 면은 잘게 나눠 화가 알고리즘(면 단위 깊이 정렬)의 앞뒤 오류를 줄임
                polys.append(q)
                fc.append((*(rgb * shade), alpha))
                ec.append((*(rgb * shade * 0.6), min(1.0, alpha + 0.2)))
    if polys:
        ax.add_collection3d(Poly3DCollection(polys, facecolors=fc, edgecolors=ec, linewidths=0.2))
    pts = [f for fs in shown.values() for f in fs]
    if pts:
        allp = np.concatenate(pts)
        lo, hi = allp.min(axis=0), allp.max(axis=0)
        if mesh.alignment:
            a = np.array(mesh.alignment)
            pad = 10.0
            a = a[np.all((a[:, :2] >= lo[:2] - pad) & (a[:, :2] <= hi[:2] + pad), axis=1)]
            if len(a) > 1:
                ax.plot(a[:, 0], a[:, 1], a[:, 2], color=layer_rgb("ALIGNMENT_CL"), linewidth=0.8)
        set_equal_box(ax, lo, hi)
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_zlabel("Z")
    if view is not None:
        ax.view_init(elev=view[0], azim=view[1])
        ax.set_xlim3d(view[2])
        ax.set_ylim3d(view[3])
        ax.set_zlim3d(view[4])
    return sum(len(v) for v in shown.values())


TILE = 6.0         # 3D 미리보기에서 이보다 긴 사각 면은 나눠 그림 (m)
_LIGHT = np.array([0.35, -0.5, 0.8]) / np.linalg.norm([0.35, -0.5, 0.8])


def _shade(f) -> float:
    """면 밝기 (빛 방향과 법선의 각도, 0.55 ~ 1.0) — 면의 방향을 구분해 입체감"""
    n = np.zeros(3)
    for i in range(len(f)):                        # Newell 법선
        a, b = f[i], f[(i + 1) % len(f)]
        n += np.cross(a, b)
    ln = np.linalg.norm(n)
    return 0.55 + 0.45 * (abs(float(n @ _LIGHT)) / ln if ln > 1e-12 else 1.0)


def _tiles(f, tile=TILE):
    """사각 면을 변 길이 tile 이하 조각으로 (양선형 분할). 사각형이 아니거나 작으면 그대로"""
    if len(f) != 4:
        return [f]
    nu = int(np.ceil(max(np.linalg.norm(f[1] - f[0]), np.linalg.norm(f[2] - f[3])) / tile))
    nv = int(np.ceil(max(np.linalg.norm(f[3] - f[0]), np.linalg.norm(f[2] - f[1])) / tile))
    if nu <= 1 and nv <= 1:
        return [f]
    nu, nv = max(nu, 1), max(nv, 1)

    def at(u, v):
        return (1 - u) * (1 - v) * f[0] + u * (1 - v) * f[1] + u * v * f[2] + (1 - u) * v * f[3]
    out = []
    for i in range(nu):
        for j in range(nv):
            u0, u1, v0, v1 = i / nu, (i + 1) / nu, j / nv, (j + 1) / nv
            out.append(np.array([at(u0, v0), at(u1, v0), at(u1, v1), at(u0, v1)]))
    return out


def set_equal_box(ax, lo, hi):
    """x·y·z 축척을 같게 (긴 정거장이 납작하게 찌그러지지 않도록)"""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    c, half = (lo + hi) / 2.0, max(float(np.max(hi - lo)) / 2.0, 1.0)
    ax.set_xlim3d(c[0] - half, c[0] + half)
    ax.set_ylim3d(c[1] - half, c[1] + half)
    ax.set_zlim3d(c[2] - half, c[2] + half)
    ax.set_box_aspect((1, 1, 1))


def zoom_3d(ax, factor: float):
    """3D 범위를 중심 기준으로 factor 배 (factor < 1 = 확대)"""
    for get, put in ((ax.get_xlim3d, ax.set_xlim3d), (ax.get_ylim3d, ax.set_ylim3d), (ax.get_zlim3d, ax.set_zlim3d)):
        a, b = get()
        c, h = (a + b) / 2.0, (b - a) / 2.0 * factor
        put(c - h, c + h)


# ================================================================== 보기 선택 (화면 입력 → 도면 인자)
def floor_choices(cfg: StationProjectConfig) -> list:
    """평면 층 선택지 [(표시 이름, 층 번호)] — 최하층부터"""
    p = cfg.station
    return [(p.level_name(n), n) for n in range(1, p.floors + 1)]


def axis_choices(cfg: StationProjectConfig) -> list:
    """종단 축 선택지 [(표시 이름, offset t)] — 선형 중심, 왼쪽·오른쪽 선로 중심"""
    d = getattr(cfg.platform, "track_spacing", None)
    out = [("선형 중심 (C.L.)", 0.0)]
    if d:
        out += [(f"왼쪽 선로 (C.L.+{d / 2:g})", d / 2.0), (f"오른쪽 선로 (C.L.-{d / 2:g})", -d / 2.0)]
    return out


def parse_axis(text: str, cfg: StationProjectConfig) -> float:
    """종단 축 입력 → offset t. 선택지 이름 또는 숫자 (왼쪽 +)"""
    t = str(text).strip()
    for name, off in axis_choices(cfg):
        if t == name:
            return off
    try:
        off = float(t)
    except ValueError:
        raise ValueError(f"종단 축: 선택지 이름이나 숫자(선형 중심에서의 거리, 왼쪽 +)를 입력하세요 ('{t}')") from None
    p = cfg.station
    lim = p.width / 2.0 + p.max_wall_t
    if abs(off) > lim:
        raise ValueError(f"종단 축: offset {off:g}m 가 본체 외곽(±{lim:g}m) 밖입니다")
    return off


def parse_section_s(text: str, cfg: StationProjectConfig) -> float:
    """횡단 측점 입력(절대 STA, '134.45' 또는 '0+134.45') → 로컬 s. 내공 범위 밖이면 오류"""
    from gui.print_draft import parse_station
    p = cfg.station
    s = parse_station(text, "횡단면") - p.start_station
    if not -1e-6 <= s <= p.length + 1e-6:
        raise ValueError(f"횡단면: 측점이 정거장 내공 범위({p.start_station:.2f} ~ {p.start_station + p.length:.2f}) 밖입니다")
    return min(max(s, 0.0), p.length)


def parse_cut_h(text: str, cfg: StationProjectConfig, floor: int) -> float:
    """평면 절단 높이(층 FL 기준) 입력 검사"""
    try:
        h = float(str(text).strip())
    except ValueError:
        raise ValueError(f"평면: 절단 높이가 숫자가 아닙니다 ('{text}')") from None
    ch = cfg.station.clear_height(floor)
    if not 0 < h < ch:
        raise ValueError(f"평면: 절단 높이는 0 보다 크고 그 층 내공 높이({ch:.2f}m)보다 작아야 합니다 ({h:g})")
    return h
