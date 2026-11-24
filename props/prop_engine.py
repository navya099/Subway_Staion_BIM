"""배치 객체(비품) BIM: 비품마다 1개 (조각 = 볼록 각기둥, prop_kinds). 배치·붙임·겹침 검사 후 3D DXF(STRUCT_PROP) / 횡단·종단(SEC_PROP) /
평면(PLAN_PROP) / IFC / DAE·웹 뷰어(형상 하나 + 배치 목록) 의 단일 원천.

비품은 연직·수평(종단구배를 따르지 않음): 놓인 자리 중심의 바닥 마감면(천장은 천장판 하면) 높이에 선형 방향 + angle 로 돌려 놓음.
"""
import math
from dataclasses import dataclass, field

import numpy as np

from bim_data.common_bim_data import CommonBIMData
from helper.view_item import ViewItem
from props.prop_check import FIXTURE, TOL, Obstacles, depth, length_text, rect, snap_to_wall
from props.prop_kinds import CEILING, EMPTY_SIZE, FLOOR, KINDS, MODEL_KINDS, ROD, WALL, rod_ys, size_box
from props.model_spec import mesh_size, model_mesh, placed_mesh, triangle_count
from props.prop_spec import resolve_prop_names
from signs.sign_layout import floor_and_ceiling

LAYER = "STRUCT_PROP"


@dataclass
class PropData(CommonBIMData):
    """비품 1개. s, t = 놓인 위치, angle = 앞면 방향(도), z = 객체 z=0 의 FL 기준 높이, parts = PropPart, values = 입력 값"""
    kind: str = "BENCH"
    floor: int = 1
    s: float = 0.0
    t: float = 0.0
    angle: float = 0.0
    z: float = 0.0
    values: dict = field(default_factory=dict)
    parts: list = field(default_factory=list)
    model: str = ""                                        # 외부 모델 이름 ("" = 코드 형상)
    mesh: list = field(default_factory=list)               # 외부 모델 삼각형 (객체 좌표, MeshPart) — parts 는 겹침·도면용 외곽 상자
    detail: bool = False                                   # 3D DXF·IFC 에 mesh 를 씀 (면 수 한도 안)
    image_entities: dict = field(default_factory=dict)     # 그림 이름 → 3DFACE 목록

    @property
    def volume(self) -> float:
        """코드 형상의 체적 (외부 모델은 외곽 상자 — 파일의 면이 닫혀 있다는 보장이 없음)"""
        return sum(p.volume for p in self.parts)

    def local(self, part) -> list:
        """조각 평면 다각형 (정거장 로컬 (s, t))"""
        a = math.radians(self.angle)
        c, n = math.cos(a), math.sin(a)
        return [(self.s + x * c - y * n, self.t + x * n + y * c) for x, y in part.poly]


class PropEngine:
    def __init__(self, config, engine):
        """engine: 이미 만든 StationCADEngine (벽 붙임·겹침 검사에 다른 부재를 씀)"""
        self.cfg = config
        self.elements: list[PropData] = []
        self.warnings: list[str] = []
        if not config.props:
            return
        st = config.station
        obs = Obstacles(engine)
        ops = {n: [rect(o.s_start, o.s_end, o.t_lo, o.t_hi) for o in config.all_openings() if n - 1 in o.slabs] for n in range(1, st.floors + 1)}
        models = self._load_models()
        for name, sp in zip(resolve_prop_names(config.props), config.props):
            k, v = KINDS[sp.kind], sp.resolved()
            mesh, build = models.get(sp.model), k.build
            if mesh:
                mesh = placed_mesh(mesh, k.mount, v.get("z", 0.0))
                build = lambda v, b=size_box(k.mount, mesh_size(mesh), v.get("z", 0.0)): [b]
            elif sp.kind in MODEL_KINDS:                                 # 파일을 못 읽음 → 마지막 크기의 상자
                v["size"] = next(m.size for m in config.prop_models if m.name.strip() == sp.model) or EMPTY_SIZE
            w = f"비품 {name}"
            s, t, ang = sp.s, sp.t, sp.angle % 360.0
            base, ceil = floor_and_ceiling(config, sp.floor, s, t)
            if k.mount == WALL:
                zs = [(p.z0, p.z1) for p in build(v)]
                mid = base + (min(a for a, _ in zs) + max(b for _, b in zs)) / 2.0
                hit = snap_to_wall(engine, sp.floor, s, t, mid)
                if hit is None:
                    raise ValueError(f"{w}: 고른 자리에서 0.5m 안에 붙일 벽이 없습니다 ({st.level_name(sp.floor)}, s {s:g}, t {t:g})")
                s, t, ang = hit
                n = math.radians(ang)
                base, ceil = floor_and_ceiling(config, sp.floor, s + 0.05 * math.cos(n), t + 0.05 * math.sin(n))
            v = dict(v, ceil=ceil - base)
            if sp.kind == "HSIGN" and not mesh:
                v["rods"] = self._rods(obs, v, s, t, ang, ceil)
            e = PropData(name=name, family_name="비품", type_name=k.label, level=st.level_name(sp.floor), material=k.material, pos_x=s, pos_y=t,
                         kind=sp.kind, floor=sp.floor, s=s, t=t, angle=ang, z=ceil if k.mount == CEILING else base, values=v, parts=build(v),
                         model=sp.model if mesh else "", mesh=mesh or [], detail=bool(mesh) and triangle_count(mesh) <= config.prop_model_limit)
            e.pos_z = config.lv(s) - st.offset + e.z
            self._check(e, k, w, obs, ops[sp.floor], ceil)
            self.elements.append(e)

    def _load_models(self) -> dict:
        """모델 이름 → MeshPart 목록 (쓰는 것만). 못 읽은 모델은 빠지고 경고"""
        out, used = {}, {sp.model for sp in self.cfg.props if sp.model}
        for m in self.cfg.prop_models:
            if m.name.strip() in used:
                try:
                    out[m.name.strip()] = model_mesh(m)
                except ValueError as e:
                    self.warnings.append(f"비품 모델 '{m.name.strip()}': {e} — 코드 형상(외부 모델은 상자)으로 대신함")
        return out

    @staticmethod
    def _rods(obs, v, s, t, ang, ceil) -> tuple:
        """매달림 사인 행거 두 자리: 천장 기구(천장판 하면 아래로 조금 나옴)와 만나면 사인 폭 안의 가장 가까운 빈 자리로
        (둘 사이는 폭의 1/4 이상). 빈 자리가 없으면 기본 자리 (겹침 검사가 오류)"""
        c, n = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        fixtures = [q for q in obs.items if q[0].startswith(FIXTURE) and q[2] < ceil - 1e-6 < q[3] + 1.0]
        g = ROD + 0.02                                                   # 여유 0.02

        def free(y):
            sq = [(s + dx * c - (y + dy) * n, t + dx * n + (y + dy) * c) for dx, dy in ((-g, -g), (g, -g), (g, g), (-g, g))]
            return all(depth(sq, q[1]) <= 0 for q in fixtures)
        y0, y1 = rod_ys(v["w"])
        if free(y0) and free(y1):
            return y0, y1
        m = int((v["w"] / 2 - 0.05) / 0.02)
        ys = [round(0.02 * k, 4) for k in range(-m, m + 1) if free(0.02 * k)]
        pairs = [(a, b) for a in ys for b in ys if b - a >= v["w"] / 4]
        return min(pairs, key=lambda p: abs(p[0] - y0) + abs(p[1] - y1), default=(y0, y1))

    # ---------- 검사 ----------
    def _check(self, e, k, w, obs, openings, ceil):
        cfg, st, pl = self.cfg, self.cfg.station, self.cfg.platform
        from config.widening import clear_contains_rect
        fl = next(f for f in cfg.room_layouts() if f.floor == e.floor)
        if not any(r.contains(e.s + (1e-3 * math.cos(math.radians(e.angle)) if k.mount == WALL else 0.0),
                              e.t + (1e-3 * math.sin(math.radians(e.angle)) if k.mount == WALL else 0.0)) for r in fl.rooms):
            raise ValueError(f"{w}: 위치 (s {e.s:g}, t {e.t:g}) 이(가) {st.level_name(e.floor)} 실 안이 아닙니다")
        pts = [p for part in e.parts for p in e.local(part)]
        box = (min(p[0] for p in pts), max(p[0] for p in pts), min(p[1] for p in pts), max(p[1] for p in pts))
        if not clear_contains_rect(cfg, e.floor, box, 2e-3):
            raise ValueError(f"{w}: 평면(s {box[0]:.2f} ~ {box[1]:.2f}, t {box[2]:.2f} ~ {box[3]:.2f})이 내공을 벗어납니다")
        if k.mount == FLOOR:
            if e.floor == 1 and pl.exists:
                from config.widening import platform_ranges
                on = [any(a - TOL <= p[1] <= b + TOL for a, b in platform_ranges(cfg)) for p in pts]
                if any(on) and not all(on):
                    raise ValueError(f"{w}: 승강장 끝에 걸쳐 있습니다 (승강장 안으로 옮기세요)")
            for part in e.parts:
                if any(depth(e.local(part), o) > TOL for o in openings):
                    raise ValueError(f"{w}: 바닥 슬래브 오프닝 위에 놓입니다")
        for part in e.parts:
            poly, z0, z1 = e.local(part), e.z + part.z0, e.z + part.z1
            hit = obs.hit(poly, z0, z1)
            if hit:
                raise ValueError(f"{w}: {hit[0]} 과(와) {length_text(hit[1])} 겹칩니다 (위치·방향·치수를 바꾸세요)")
            if z1 > ceil + TOL and k.mount != CEILING:
                raise ValueError(f"{w}: 윗면(바닥 마감면 + {z1 - e.z:.2f}m)이 천장보다 높습니다")
            for q in self.elements:
                for other in q.parts:
                    if min(z1, q.z + other.z1) - max(z0, q.z + other.z0) > TOL and depth(poly, q.local(other)) > TOL:
                        raise ValueError(f"{w}: 비품 {q.name} 과(와) 겹칩니다")

    # ---------- 기하 ----------
    def transform(self, e) -> tuple:
        """(x, y, z, 세계 방향각) — 객체 좌표 원점의 세계 위치와 앞면 방향"""
        x, y = self.cfg.to_world(e.s, e.t)
        return x, y, self.cfg.lv(e.s) - self.cfg.station.offset + e.z, self.cfg.theta_at(e.s) + math.radians(e.angle)

    def part_faces(self, e, part) -> list:
        """조각의 면 (세계, 바깥 방향): 옆면들, 아래, 위"""
        x, y, z, th = self.transform(e)
        c, n = math.cos(th), math.sin(th)
        w = lambda p, h: (x + p[0] * c - p[1] * n, y + p[0] * n + p[1] * c, z + h)
        lo, hi = [w(p, part.z0) for p in part.poly], [w(p, part.z1) for p in part.poly]
        m = len(lo)
        out = [(lo[i], lo[(i + 1) % m], hi[(i + 1) % m], hi[i]) for i in range(m)]
        return out + [tuple(reversed(lo)), tuple(hi)]

    def model_faces(self, e) -> list:
        """외부 모델의 세계 삼각형 [(MeshPart, 점 (M, 3, 3))] — 넓이 0 인 면은 뺌"""
        x, y, z, th = self.transform(e)
        c, n = math.cos(th), math.sin(th)
        R = np.array([[c, -n, 0], [n, c, 0], [0, 0, 1]])
        out = []
        for p in e.mesh:
            t = (p.pos @ R.T + (x, y, z))[p.idx]
            out.append((p, t[np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1) > 1e-10]))
        return out

    @staticmethod
    def image_index(part) -> int:
        """그림이 붙는 옆면 번호 (사각 조각: 변 1 = +x, 변 3 = −x)"""
        return 1 if part.image_face == "+x" else 3

    # ---------- 작도 ----------
    def add_prop_mesh(self, msp):
        """3D 메쉬 (STRUCT_PROP). 다각형 윗·아랫면은 부채꼴 삼각형. 한 번만 호출할 것"""
        for e in self.elements:
            e.source_element, e.image_entities, e.part_entities = [], {}, []
            if e.detail:
                for part, tris in self.model_faces(e):
                    ents = [msp.add_3dface([tuple(map(float, q)) for q in t], dxfattribs={"layer": LAYER}) for t in tris]
                    e.part_entities.append(("비품 흰색", ents))
                    e.source_element += ents
                continue
            for part in e.parts:
                ents = []
                for i, f in enumerate(self.part_faces(e, part)):
                    tris = [f] if len(f) <= 4 else [(f[0], f[j], f[j + 1]) for j in range(1, len(f) - 1)]
                    new = [msp.add_3dface(q, dxfattribs={"layer": LAYER}) for q in tris]
                    if part.image and i == self.image_index(part):
                        e.image_entities[part.image] = new
                    ents += new
                e.part_entities.append((part.material, ents))
                e.source_element += ents

    def images(self, e) -> dict:
        """그림 이름 → PIL 이미지"""
        k = KINDS[e.kind]
        if e.mesh:
            return {}
        return {n: fn() for n, fn in (k.images(e.values) if k.images else {}).items()}

    def sign_images(self) -> list:
        """DAE: [(재질 이름, PIL 이미지, uv 틀, 3DFACE 목록)]. 앞에서 볼 때 왼쪽 아래 ~ 오른쪽 위에 한 장"""
        out = []
        for e in self.elements:
            imgs = self.images(e)
            x, y, z, th = self.transform(e)
            for part in e.parts:
                if not part.image:
                    continue
                xs, ys = [p[0] for p in part.poly], [p[1] for p in part.poly]
                front = part.image_face == "+x"
                px, py = (max(xs), min(ys)) if front else (min(xs), max(ys))          # 왼쪽 아래 (앞에서 볼 때 오른쪽 = +y)
                o = (x + px * math.cos(th) - py * math.sin(th), y + px * math.sin(th) + py * math.cos(th), z + part.z0)
                sg = 1.0 if front else -1.0
                u = (-math.sin(th) * sg, math.cos(th) * sg, 0.0)
                out.append((f"사인 {e.name} {part.image}", imgs[part.image], (o, u, (0.0, 0.0, 1.0), max(ys) - min(ys), part.z1 - part.z0, 0.0),
                            e.image_entities[part.image]))
        return out

    # ---------- 2D 도면 ----------
    def plan_items(self, cut_h, floor=1):
        """평면도(floor 층): 비품 윤곽 (높이와 관계없이 — 매달림·벽 부착·천장 포함) + 이름"""
        items = []
        for e in self.elements:
            if e.floor != floor:
                continue
            for part in e.parts:
                pts = e.local(part)
                items.append(ViewItem(e.name, "PLAN_PROP", u0=min(p[0] for p in pts), u1=max(p[0] for p in pts), pts=pts))
            items.append(ViewItem(e.name, "PLAN_PROP", u0=e.s, u1=e.s, pts=[], label=(e.name, e.s, e.t, 0.2, "PLAN_PROP")))
        return items

    def _cut(self, pts, axis, c):
        """다각형을 좌표 axis(0 = s, 1 = t) = c 선으로 자른 다른 좌표 구간"""
        vals = []
        for p, q in zip(pts, pts[1:] + pts[:1]):
            a, b = p[axis] - c, q[axis] - c
            if (a <= 0 < b) or (b <= 0 < a):
                vals.append(p[1 - axis] + (q[1 - axis] - p[1 - axis]) * a / (a - b))
        return (min(vals), max(vals)) if len(vals) >= 2 and max(vals) - min(vals) > 1e-9 else None

    def section_items(self, sta):
        items = []
        for e in self.elements:
            z = self.cfg.lv(e.s) - self.cfg.station.offset + e.z
            for part in e.parts:
                iv = self._cut(e.local(part), 0, sta)
                if iv:
                    items.append(ViewItem.rect(e.name, "SEC_PROP", *iv, z + part.z0, z + part.z1))
        return items

    def profile_items(self, t_cut=0.0):
        items = []
        for e in self.elements:
            z = self.cfg.lv(e.s) - self.cfg.station.offset + e.z
            for part in e.parts:
                iv = self._cut(e.local(part), 1, t_cut)
                if iv:
                    items.append(ViewItem.rect(e.name, "SEC_PROP", *iv, z + part.z0, z + part.z1))
        return items
