"""스크린도어(PSD) BIM 객체: 부재(POST·구동부·고정부·가동문·비상문 겸용 고정부·채움 패널)마다 1개, 조각 = 선형 각기둥(RoomPiece).

배치는 psd_layout.layout_psds. 3D DXF(STRUCT_PSD 프레임·POST·구동부 / STRUCT_PSD_GLASS 유리) / 횡단·종단(SEC_PSD 윤곽) /
평면(PLAN_PSD, 최하층) / IFC(선로마다 IfcElementAssembly ⊃ IfcColumn·IfcMember·IfcDoor·IfcPlate) 의 단일 원천.
"""
from dataclasses import dataclass, field

from bim_data.common_bim_data import CommonBIMData
from finishes.finish_engine import room_piece
from helper import prism_member as PM
from helper.geometry_helper import CommonHelper
from helper.view_item import ViewItem
from psds.psd_layout import DOOR, EMERGENCY, FILL, FIXED, HEADER, POST, layout_psds

MATERIALS = {POST: "PSD 기둥 (Steel)", HEADER: "PSD 구동부 커버", DOOR: "PSD 강화유리 THK8", FIXED: "PSD 강화유리 THK8",
             EMERGENCY: "PSD 강화유리 THK8", FILL: "PSD 강화유리 THK8"}
LABELS = {POST: "POST", HEADER: "구동부", DOOR: "가동문", FIXED: "고정부", EMERGENCY: "고정부(비상문 겸용)", FILL: "고정부(채움)"}


@dataclass
class PsdElementData(CommonBIMData):
    kind: str = POST
    track: str = "R"
    unit: str = ""
    pieces: list = field(default_factory=list)      # RoomPiece
    glass: list = field(default_factory=list)       # 조각마다 유리 여부

    @property
    def volume(self) -> float:
        return sum(p.shape.volume for p in self.pieces)

    @property
    def s_range(self) -> tuple:
        return min(PM.s_range(p)[0] for p in self.pieces), max(PM.s_range(p)[1] for p in self.pieces)

    @property
    def height(self) -> float:
        return max(p.shape.height for p in self.pieces)


class PsdEngine:
    def __init__(self, config):
        self.cfg = config
        self.runs = layout_psds(config)
        self.elements: list[PsdElementData] = []
        level = config.station.level_name(1)
        for r in self.runs:
            for p in r.parts:
                pieces = [room_piece(config, f"{p.name}_{k}", *pc) for k, pc in enumerate(p.pieces, start=1)]
                self.elements.append(PsdElementData(
                    name=p.name, family_name="스크린도어", type_name=LABELS[p.kind], level=level,
                    material=MATERIALS[p.kind], kind=p.kind, track=p.track, unit=p.unit, pieces=pieces, glass=list(p.glass)))

    # ---------- 작도 ----------
    def add_psd_mesh(self, msp):
        """3D 메쉬 (STRUCT_PSD / STRUCT_PSD_GLASS). 한 번만 호출할 것"""
        for e in self.elements:
            ents = []
            for p, g in zip(e.pieces, e.glass):
                layer = "STRUCT_PSD_GLASS" if g else "STRUCT_PSD"
                ents += [msp.add_3dface(f, dxfattribs={"layer": layer}) for f in PM.mesh_faces(self.cfg, p)]
            e.source_element = ents

    def section_items(self, sta):
        items = []
        for e in self.elements:
            for p in e.pieces:
                cut = PM.section_rect(self.cfg, p, sta)
                if cut:
                    t0, t1, zb = cut
                    items.append(ViewItem.rect(e.name, "SEC_PSD", t0, t1, zb, zb + p.shape.height))
        return items

    def profile_items(self, t_cut=0.0):
        return [PM.profile_view(self.cfg, p, "SEC_PSD") for e in self.elements for p in e.pieces
                if CommonHelper.cut_by_t(*PM.t_range(p), t_cut)]

    def plan_items(self, cut_h, floor=1):
        """평면도(최하층): 절단 높이를 지나는 POST·패널 조각 윤곽"""
        if floor != 1:
            return []
        items = []
        for e in self.elements:
            for p in e.pieces:
                z0 = PM.z_off(self.cfg, p)
                if z0 - 1e-9 <= cut_h < z0 + p.shape.height - 1e-9:
                    items.append(ViewItem.rect(e.name, "PLAN_PSD", *PM.s_range(p), *PM.t_range(p)))
        return items
