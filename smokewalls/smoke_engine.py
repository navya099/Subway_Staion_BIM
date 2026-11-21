"""제연경계벽 BIM 객체: 오프닝마다 1개 ⊃ 프레임(위·아래)·유리, 조각 = 선형 각기둥(RoomPiece).
3D DXF(STRUCT_SMOKE 프레임 / STRUCT_SMOKE_GLASS 유리) / 횡단·종단(SEC_RAILING 윤곽) / 평면(PLAN_RAILING, 그 층 — 천장 아래라
절단 높이와 무관하게 점선 대신 윤곽) / IFC(IfcCurtainWall USERDEFINED SMOKE_BARRIER ⊃ 프레임 IfcMember · 유리 IfcPlate)"""
from dataclasses import dataclass, field

from bim_data.common_bim_data import CommonBIMData
from finishes.finish_engine import room_piece
from helper import prism_member as PM
from helper.geometry_helper import CommonHelper
from helper.view_item import ViewItem
from smokewalls.smoke_layout import FRAME, GLASS, layout_smoke_barriers

GLASS_MATERIAL = "제연 유리"
LABELS = {FRAME: "프레임", GLASS: "유리판"}


@dataclass
class SmokePartData(CommonBIMData):
    code: str = FRAME
    pieces: list = field(default_factory=list)

    @property
    def volume(self) -> float:
        return sum(p.shape.volume for p in self.pieces)


@dataclass
class SmokeBarrierData(CommonBIMData):
    opening: str = ""
    floor: int = 1
    parts: list = field(default_factory=list)

    def part(self, code):
        return next((p for p in self.parts if p.code == code), None)


class SmokeBarrierEngine:
    def __init__(self, config):
        self.cfg = config
        self.barriers: list[SmokeBarrierData] = []
        sb = config.smoke_settings
        for lay in layout_smoke_barriers(config):
            level = config.station.level_name(lay.floor)
            parts = []
            for code in (FRAME, GLASS):
                name = f"{lay.name}_{code}"
                parts.append(SmokePartData(
                    name=name, family_name="제연경계벽", type_name=LABELS[code], level=level,
                    material=sb.frame_material if code == FRAME else GLASS_MATERIAL, code=code,
                    pieces=[room_piece(config, f"{name}_{k}", *r) for k, r in enumerate(lay.parts[code], start=1)]))
            self.barriers.append(SmokeBarrierData(name=lay.name, family_name="제연경계벽",
                                                  type_name=f"유리 제연경계벽 {sb.depth:g}m", level=level,
                                                  opening=lay.opening, floor=lay.floor, parts=parts))

    @property
    def elements(self) -> list:
        return [p for b in self.barriers for p in b.parts]

    def add_smoke_mesh(self, msp):
        """3D 메쉬 (STRUCT_SMOKE / STRUCT_SMOKE_GLASS). 한 번만 호출할 것"""
        for e in self.elements:
            layer = "STRUCT_SMOKE_GLASS" if e.code == GLASS else "STRUCT_SMOKE"
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
        """평면도(floor 층): 경계벽 윤곽 (천장 아래 매달림 — 절단 높이와 무관)"""
        return [PM.plan_item(e.name, "PLAN_RAILING", p) for b in self.barriers if b.floor == floor
                for e in b.parts if e.code == FRAME for p in e.pieces[:1]]
