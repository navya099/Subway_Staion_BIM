"""계단·에스컬레이터 오프닝 유리난간 BIM 객체: 오프닝마다 난간 1개 ⊃ 부재(경계석·POST·레일·유리), 조각 = 선형 각기둥(RoomPiece).

배치는 railing_layout.layout_railings. 3D DXF(STRUCT_RAILING 경계석·POST·레일 / STRUCT_RAILING_GLASS 유리) / 횡단·종단
(SEC_RAILING 윤곽) / 평면(PLAN_RAILING, 그 층 절단 높이를 지나는 조각) / IFC(IfcRailing GUARDRAIL ⊃ 경계석
석판·걸레받이·속채움 IfcBuildingElementPart · POST IfcMember(POST) · 레일 IfcMember(USERDEFINED HANDRAIL) · 유리 IfcPlate) 의 단일 원천.
"""
from dataclasses import dataclass, field

from bim_data.common_bim_data import CommonBIMData
from finishes.finish_engine import room_piece
from helper import prism_member as PM
from helper.geometry_helper import CommonHelper
from helper.view_item import ViewItem
from railings.railing_layout import CORE, CURB, GLASS, POST, RAIL, SKIRT, layout_railings

LABELS = {CURB: "경계석 석판", SKIRT: "경계석 걸레받이", CORE: "경계석 속채움", POST: "POST", RAIL: "파이프 레일", GLASS: "유리판"}
GLASS_MATERIAL = "난간 유리"


@dataclass
class RailingPartData(CommonBIMData):
    code: str = POST
    pieces: list = field(default_factory=list)      # RoomPiece

    @property
    def volume(self) -> float:
        return sum(p.shape.volume for p in self.pieces)


@dataclass
class RailingData(CommonBIMData):
    """오프닝 하나의 유리난간. floor = 난간이 서는 층, edges = 난간이 있는 가장자리"""
    opening: str = ""
    floor: int = 1
    edges: tuple = ()
    parts: list = field(default_factory=list)       # RailingPartData

    def part(self, code: str):
        return next((p for p in self.parts if p.code == code), None)


class RailingEngine:
    def __init__(self, config):
        self.cfg = config
        self.railings: list[RailingData] = []
        rs = config.railing_settings
        mats = {CURB: rs.curb_material, SKIRT: rs.skirt_material, CORE: rs.core_material, POST: rs.post_material,
                RAIL: rs.post_material, GLASS: GLASS_MATERIAL}
        for lay in layout_railings(config):
            level = config.station.level_name(lay.floor)
            parts = []
            for code in (CURB, SKIRT, CORE, POST, RAIL, GLASS):
                rects = lay.parts.get(code) or []
                if not rects:
                    continue
                name = f"{lay.name}_{code}"
                parts.append(RailingPartData(
                    name=name, family_name="유리난간", type_name=LABELS[code], level=level, material=mats[code], code=code,
                    pieces=[room_piece(config, f"{name}_{k}", *r) for k, r in enumerate(rects, start=1)]))
            self.railings.append(RailingData(name=lay.name, family_name="유리난간", type_name="오프닝 유리난간", level=level,
                                             opening=lay.opening, floor=lay.floor, edges=lay.edges, parts=parts))

    @property
    def elements(self) -> list:
        return [p for r in self.railings for p in r.parts]

    # ---------- 작도 ----------
    def add_railing_mesh(self, msp):
        """3D 메쉬 (STRUCT_RAILING / STRUCT_RAILING_GLASS). 한 번만 호출할 것"""
        for e in self.elements:
            layer = "STRUCT_RAILING_GLASS" if e.code == GLASS else "STRUCT_RAILING"
            e.source_element = [msp.add_3dface(f, dxfattribs={"layer": layer}) for p in e.pieces
                                for f in PM.mesh_faces(self.cfg, p)]

    def section_items(self, sta):
        items = []
        for e in self.elements:
            for p in e.pieces:
                cut = PM.section_rect(self.cfg, p, sta)
                if cut:
                    t0, t1, zb = cut
                    items.append(ViewItem.rect(e.name, "SEC_RAILING", t0, t1, zb, zb + p.shape.height))
        return items

    def profile_items(self, t_cut=0.0):
        return [PM.profile_view(self.cfg, p, "SEC_RAILING") for e in self.elements for p in e.pieces
                if CommonHelper.cut_by_t(*PM.t_range(p), t_cut)]

    def plan_items(self, cut_h, floor=1):
        """평면도(floor 층): 경계석 윤곽 + 절단 높이를 지나는 POST·유리"""
        items = []
        for r in self.railings:
            if r.floor != floor:
                continue
            for e in r.parts:
                for p in e.pieces:
                    z0 = PM.z_off(self.cfg, p)
                    if e.code in (CURB, SKIRT) or z0 - 1e-9 <= cut_h < z0 + p.shape.height - 1e-9:
                        items.append(PM.plan_item(e.name, "PLAN_RAILING", p))
        return items
