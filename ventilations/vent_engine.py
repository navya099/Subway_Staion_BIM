import math

from config.master_config import StationProjectConfig
from helper.view_item import ViewItem
from ventilations.vent_data import VentData, VentElementData
from ventilations.vent_type import VentPartKind

_FAMILY = {VentPartKind.FLOOR: "콘크리트-환기구바닥슬래브", VentPartKind.ROOF: "콘크리트-환기구천장슬래브",
           VentPartKind.WALL: "콘크리트-환기구벽체", VentPartKind.MID_WALL: "콘크리트-환기구중벽",
           VentPartKind.END_WALL: "콘크리트-환기구끝벽", VentPartKind.SHAFT_WALL: "콘크리트-환기구수직구벽",
           VentPartKind.GRILL: "금속-환기구그릴"}
_WALLS = (VentPartKind.WALL, VentPartKind.MID_WALL, VentPartKind.END_WALL, VentPartKind.SHAFT_WALL)


class VentEngine:
    """환기구 BIM 객체(연속박스 덕트 부재, 수직구 벽, 칸별 그릴)를 만들고 3D DXF / 2D 도면 / IFC 의 단일 데이터 원천이 된다.

    - 배치는 cfg.vent_layouts() 결과를 그대로 쓴다 (벽체 엔진의 측벽 오프닝과 같은 계산)
    - 모든 조각은 세계 좌표의 곧은 압출(BoxPiece)이라 곡선 선형에서도 3D·IFC 가 정확하다
    - 횡단면도: 정거장 횡단 연직면으로 조각을 정확히 자름, 평면도: 그 층 환기구의 벽 평면
    """

    def __init__(self, config: StationProjectConfig):
        self.cfg = config
        self.sp = config.station
        self.vents: list[VentData] = []
        self._build()

    def _build(self):
        for lay in self.cfg.vent_layouts():
            spec = lay.spec
            level = self.sp.level_name(lay.floor)
            thick = {VentPartKind.FLOOR: spec.floor_t, VentPartKind.ROOF: spec.roof_t, VentPartKind.WALL: spec.wall_t,
                     VentPartKind.MID_WALL: spec.mid_wall_t, VentPartKind.END_WALL: spec.wall_t,
                     VentPartKind.SHAFT_WALL: spec.wall_t, VentPartKind.GRILL: spec.grill_t}

            def data(e):
                metal = e.kind == VentPartKind.GRILL
                return VentElementData(
                    name=f"{lay.name}_{e.code}", family_name=_FAMILY[e.kind],
                    type_name=f"{int(round(thick[e.kind] * 1000))}mm", level=level,
                    pos_z=min(p.z_range[0] for p in e.pieces), material="Steel" if metal else "Concrete_C24",
                    kind=e.kind, code=e.code, pieces=e.pieces)
            v0 = lay.vertices[0]
            self.vents.append(VentData(
                name=lay.name, family_name="환기구",
                type_name=f"{spec.cells}련 {spec.cell_width:g}x{spec.cell_height:g}",
                level=level, pos_x=v0.s, pos_y=v0.t, pos_z=lay.z_floor, floor=lay.floor, side=lay.side,
                cells=spec.cells, vertices=lay.vertices, shafts=lay.shafts, corners=lay.corners,
                grill_at_shaft=lay.grill_at_shaft, elements=[data(e) for e in lay.elements],
                grills=[data(e) for e in lay.grills]))

    def all_vents(self) -> list[VentData]:
        return list(self.vents)

    # ---------- 작도 ----------
    def add_vent_mesh(self, msp):
        """3D 절대 좌표계 메쉬 (콘크리트 = STRUCT_VENT, 그릴 = STRUCT_GRILL). 한 번만 호출할 것"""
        for vt in self.vents:
            for e in vt.elements + vt.grills:
                layer = "STRUCT_GRILL" if e.kind == VentPartKind.GRILL else "STRUCT_VENT"
                faces = [f for piece in e.pieces for f in piece.faces()]
                e.source_element = [msp.add_3dface(f, dxfattribs={"layer": layer}) for f in faces]

    # ---------- 2D 도면 ----------
    def section_items(self, sta):
        """횡단면도: 측점 sta 의 횡단 연직면(선형 접선이 법선)으로 자른 환기구 단면 (도면 u = t, v = 표고)"""
        cx, cy = self.cfg.to_world(sta, 0.0)
        th = self.cfg.theta_at(sta)
        nx, ny = math.cos(th), math.sin(th)
        items = []
        for vt in self.vents:
            labeled = False
            for e in vt.elements + vt.grills:
                metal = e.kind == VentPartKind.GRILL
                for p in e.pieces:
                    poly = p.cut_by_plane(cx, cy, nx, ny)
                    if poly is None:
                        continue
                    label = None
                    if not labeled and not metal:
                        t_lab = max(w for w, _ in poly) if vt.side > 0 else min(w for w, _ in poly)
                        label = (vt.name, t_lab, max(z for _, z in poly) + 0.4, 0.4, "SEC_TEXT")
                        labeled = True
                    items.append(ViewItem(e.name, "SEC_GRILL" if metal else "SEC_CONCRETE",
                                          u0=min(w for w, _ in poly), u1=max(w for w, _ in poly), pts=poly,
                                          hatch_layer=None if metal else "SEC_HATCH", label=label))
        return items

    def plan_items(self, cut_h, floor=1):
        """평면도(floor 층 절단): 그 층에 붙은 환기구의 벽 평면 (바깥 벽·중벽·끝 벽·수직구 벽, 정거장 로컬 (s, t) 다각형)"""
        items = []
        for vt in self.vents:
            if vt.floor != floor:
                continue
            v0, v1 = vt.vertices[0], vt.vertices[1]
            s_lab, t_lab = self.cfg.to_station((v0.x + v1.x) / 2.0, (v0.y + v1.y) / 2.0)
            label = (f"{vt.name} VENT {vt.cells}련", s_lab - 1.0, t_lab, 0.5, "PLAN_TEXT")
            for e in vt.elements:
                if e.kind not in _WALLS:
                    continue
                for p in e.pieces:
                    pts = [self.cfg.to_station(x, y) for x, y in p.footprint()]
                    items.append(ViewItem(e.name, "PLAN_VENT", u0=min(s for s, _ in pts), u1=max(s for s, _ in pts),
                                          pts=pts, label=label))
                    label = None
        return items
