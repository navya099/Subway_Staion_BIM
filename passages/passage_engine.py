import math

from config.master_config import StationProjectConfig
from helper.view_item import ViewItem
from passages.passage_data import PassageData, PassageElementData
from passages.passage_package import PassagePackage
from passages.passage_type import PassagePartKind

_FAMILY = {PassagePartKind.FLOOR: "콘크리트-통로바닥슬래브", PassagePartKind.ROOF: "콘크리트-통로천장슬래브",
           PassagePartKind.WALL: "콘크리트-통로벽체"}


class PassageEngine:
    """출구통로 BIM 객체(평면 직선 구간별 바닥·천장 슬래브, 좌·우 벽)를 만들고, 3D DXF / 2D 도면 / IFC 의 단일 데이터 원천이 된다.

    - 배치(경로 꼭짓점·부재 조각·측벽 오프닝)는 cfg.passage_layouts() 결과를 그대로 쓴다 (벽체 엔진과 같은 계산)
    - 조각은 세계 좌표의 곧은 압출이라 3D·IFC 는 곡선 선형에서도 정확하다
    - 횡단면도: 정거장 횡단면(측점 sta 의 연직면)으로 조각을 정확히 자른 단면, 평면도: 조각 평면을 정거장 로컬로 옮김
    """

    def __init__(self, config: StationProjectConfig):
        self.cfg = config
        self.sp = config.station
        self.passage_packages: list[PassagePackage] = []
        self._build()

    def _build(self):
        by_level: dict[str, PassagePackage] = {}
        for lay in self.cfg.passage_layouts():
            spec = lay.spec
            level = self.sp.level_name(lay.floor)
            package = by_level.setdefault(level, PassagePackage(level=level, package_id=f"PKG_{level}_PASSAGES"))
            elements = []
            for e in lay.elements:
                thick = {PassagePartKind.FLOOR: spec.floor_t, PassagePartKind.ROOF: spec.roof_t,
                         PassagePartKind.WALL: spec.wall_t}[e.kind]
                elements.append(PassageElementData(
                    name=f"{lay.name}_{e.code}", family_name=_FAMILY[e.kind], type_name=f"{int(round(thick * 1000))}mm",
                    level=level, pos_z=min(p.z_range[0] for p in e.pieces), material="Concrete_C24",
                    kind=e.kind, run=e.run, pieces=e.pieces))
            v0 = lay.vertices[0]
            package.add_passage(PassageData(
                name=lay.name, family_name="출구통로",
                type_name=f"{spec.inner_width:g}x{spec.inner_height:g}",
                level=level, pos_x=v0.s, pos_y=v0.t, pos_z=lay.z_floor,
                floor=lay.floor, side=lay.side, vertices=lay.vertices, corners=lay.corners,
                opening_name=f"OPEN_{lay.name}", elements=elements))
        floor_no = {self.sp.level_name(n): n for n in range(1, self.sp.floors + 1)}
        self.passage_packages = sorted(by_level.values(), key=lambda pk: floor_no[pk.level])

    def all_passages(self) -> list[PassageData]:
        return [p for pk in self.passage_packages for p in pk.passages]

    # ---------- 작도 ----------
    def add_passage_mesh(self, msp):
        """3D 절대 좌표계 메쉬 (조각마다 곧은 각기둥, 꺾임부는 연귀). 한 번만 호출할 것"""
        for ps in self.all_passages():
            for e in ps.elements:
                faces = [f for piece in e.pieces for f in piece.faces()]
                e.source_element = [msp.add_3dface(f, dxfattribs={"layer": "STRUCT_PASSAGE"}) for f in faces]

    # ---------- 2D 도면 ----------
    def section_items(self, sta):
        """횡단면도: 측점 sta 의 횡단 연직면(선형 접선이 법선)으로 자른 통로 부재 단면 (도면 u = t, v = 표고)"""
        cx, cy = self.cfg.to_world(sta, 0.0)
        th = self.cfg.theta_at(sta)
        nx, ny = math.cos(th), math.sin(th)
        items = []
        for ps in self.all_passages():
            labeled = False
            for e in ps.elements:
                for p in e.pieces:
                    poly = p.cut_by_plane(cx, cy, nx, ny)       # w = 법선을 +90° 돌린 방향 = 정거장 t
                    if poly is None:
                        continue
                    label = None
                    if not labeled:
                        t_lab = max(w for w, _ in poly) if ps.side > 0 else min(w for w, _ in poly)
                        label = (ps.name, t_lab, max(z for _, z in poly) + 0.4, 0.4, "SEC_TEXT")
                        labeled = True
                    items.append(ViewItem(e.name, "SEC_CONCRETE", u0=min(w for w, _ in poly), u1=max(w for w, _ in poly),
                                          pts=poly, hatch_layer="SEC_HATCH", label=label))
        return items

    def plan_items(self, cut_h, floor=1):
        """평면도(floor 층 절단): 그 층에 붙은 통로의 벽 평면 (정거장 로컬 (s, t) 다각형)"""
        items = []
        for ps in self.all_passages():
            if ps.floor != floor:
                continue
            v0, v1 = ps.vertices[0], ps.vertices[1]
            s_lab, t_lab = self.cfg.to_station((v0.x + v1.x) / 2.0, (v0.y + v1.y) / 2.0)
            label = (f"{ps.name} EXIT", s_lab - 1.0, t_lab, 0.5, "PLAN_TEXT")
            for e in ps.elements:
                if e.kind != PassagePartKind.WALL:
                    continue
                for p in e.pieces:
                    pts = [self.cfg.to_station(x, y) for x, y in p.footprint()]
                    items.append(ViewItem(e.name, "PLAN_PASSAGE", u0=min(s for s, _ in pts), u1=max(s for s, _ in pts),
                                          pts=pts, label=label))
                    label = None
        return items
