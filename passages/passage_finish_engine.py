"""출구통로 마감 BIM 객체: 통로마다 바닥 마감재·채움·벽 마감·천장판·천장틀 (조각 = 세계 좌표 곧은 압출 BoxPiece).

배치는 passage_finish.layout_passage_finishes. 3D DXF(FIN_FLOOR / FIN_WALL / FIN_CEILING / FIN_FRAME — 실 마감과 같은 레이어),
횡단(SEC_FINISH 윤곽), 평면(PLAN_FINISH: 그 층 통로의 절단 높이를 지나는 벽 마감), IFC(IfcCovering FLOORING / CLADDING / CEILING,
천장틀 IfcMember — 통로 층 storey) 의 단일 원천. 천장이 내공에 들어가지 않으면 warnings 에 경고.
"""
import math
from dataclasses import dataclass, field

from bim_data.common_bim_data import CommonBIMData
from helper.view_item import ViewItem
from passages.passage_finish import CEILING, FILL, FLOOR, FRAME, SKIRT, WALL, layout_passage_finishes

LAYERS = {FLOOR: "FIN_FLOOR", FILL: "FIN_FLOOR", WALL: "FIN_WALL", SKIRT: "FIN_WALL", CEILING: "FIN_CEILING", FRAME: "FIN_FRAME"}
LABELS = {FLOOR: "바닥 마감", FILL: "바닥 채움", WALL: "벽 마감", SKIRT: "걸레받이", CEILING: "천장판", FRAME: "천장틀"}


@dataclass
class PassageFinishData(CommonBIMData):
    """통로 마감 부재 1개 (코드별). passage = 통로 이름, floor = 층, pieces = BoxPiece"""
    code: str = FLOOR
    passage: str = ""
    floor: int = 1
    pieces: list = field(default_factory=list)

    @property
    def volume(self) -> float:
        return sum(p.volume for p in self.pieces)


class PassageFinishEngine:
    def __init__(self, config):
        self.cfg = config
        self.elements: list[PassageFinishData] = []
        lays, self.warnings = layout_passage_finishes(config)
        self.layouts = lays
        st = config.station
        for lay in lays:
            ft = lay.ft
            mats = {FLOOR: ft.floor_material, FILL: "몰탈", WALL: ft.wall_material, SKIRT: ft.skirt_material, CEILING: ft.ceiling_material,
                    FRAME: f"{ft.frame}바 천장틀"}
            for code in (FILL, FLOOR, WALL, SKIRT, CEILING, FRAME):
                pieces = lay.parts.get(code) or []
                if not pieces:
                    continue
                self.elements.append(PassageFinishData(
                    name=f"{lay.name}_FIN_{code}", family_name="통로 마감", type_name=f"{ft.name} {LABELS[code]}",
                    level=st.level_name(lay.floor), material=mats[code], code=code, passage=lay.name, floor=lay.floor,
                    pieces=pieces))

    def element(self, passage: str, code: str):
        return next((e for e in self.elements if e.passage == passage and e.code == code), None)

    # ---------- 작도 ----------
    def add_passage_finish_mesh(self, msp):
        """3D 메쉬 (실 마감과 같은 FIN_* 레이어). 한 번만 호출할 것"""
        for e in self.elements:
            e.source_element = [msp.add_3dface(f, dxfattribs={"layer": LAYERS[e.code]}) for p in e.pieces for f in p.faces()]

    def section_items(self, sta):
        """횡단면도: 측점 sta 의 횡단 연직면으로 자른 마감 조각 윤곽 (SEC_FINISH)"""
        cx, cy = self.cfg.to_world(sta, 0.0)
        th = self.cfg.theta_at(sta)
        nx, ny = math.cos(th), math.sin(th)
        items = []
        for e in self.elements:
            if e.code == FRAME:
                continue
            for p in e.pieces:
                poly = p.cut_by_plane(cx, cy, nx, ny)
                if poly:
                    items.append(ViewItem(e.name, "SEC_FINISH", u0=min(w for w, _ in poly), u1=max(w for w, _ in poly), pts=poly))
        return items

    def plan_items(self, cut_h, floor=1):
        """평면도(floor 층): 그 층 통로의 절단 높이(층 FL 기준 cut_h)를 지나는 벽 마감 평면"""
        st = self.cfg.station
        items = []
        for e in self.elements:
            if e.code not in (WALL, SKIRT) or e.floor != floor:
                continue
            h = cut_h - st.floor_level(floor)                          # 통로 바닥(구조) 상면 기준 절단 높이
            for p in e.pieces:
                dz = [d for _, d in p.sect]
                if not (min(dz) - 1e-9 <= h <= max(dz) + 1e-9):
                    continue
                pts = [self.cfg.to_station(x, y) for x, y in p.footprint()]
                items.append(ViewItem(e.name, "PLAN_FINISH", u0=min(s for s, _ in pts), u1=max(s for s, _ in pts), pts=pts))
        return items
