"""역명판·안내사인 BIM 객체: 사인마다 1개 = 본체 판(STRUCT_SIGN) + 앞면 이미지 면(STRUCT_SIGN_FACE), 조각 = RoomPiece.

배치는 sign_layout.layout_signs, 이미지는 nameplate.py (텍스처 DAE 에서만 그려 붙임 — 2D 도면·IFC 는 문구만).
IFC: IfcBuildingElementProxy(USERDEFINED, ObjectType SIGNAGE) + 속성 세트 SSBIM_Sign(종류·문구).
"""
import math
from dataclasses import dataclass, field

from bim_data.common_bim_data import CommonBIMData
from finishes.finish_engine import room_piece
from helper import prism_member as PM
from helper.geometry_helper import CommonHelper
from helper.view_item import ViewItem
from signs.sign_layout import BOARDING, EXIT, NAMEPLATE, layout_signs, nameplate_input

KIND_LABEL = {NAMEPLATE: "역명판", BOARDING: "타는 곳 안내", EXIT: "출구 안내"}


@dataclass
class SignElementData(CommonBIMData):
    kind: str = NAMEPLATE
    floor: int = 1
    placement: object = None
    pieces: list = field(default_factory=list)       # [본체, 이미지 면] RoomPiece
    text: str = ""                                   # 문구 (도면 글자·IFC)
    face_entities: list = field(default_factory=list)

    @property
    def volume(self) -> float:
        return sum(p.shape.volume for p in self.pieces)


class SignEngine:
    def __init__(self, config):
        self.cfg = config
        self.settings = config.sign_settings
        self.elements: list[SignElementData] = []
        st = config.station
        for p in layout_signs(config):
            body, face = p.boxes()
            pieces = [room_piece(config, f"{p.name}_BODY", *body), room_piece(config, f"{p.name}_FACE", *face)]
            self.elements.append(SignElementData(
                name=p.name, family_name="사인", type_name=KIND_LABEL[p.kind], level=st.level_name(p.floor),
                material="사인 패널", kind=p.kind, floor=p.floor, placement=p, pieces=pieces, text=self._text(p)))

    def _text(self, p) -> str:
        si = self.settings.station
        if p.kind == NAMEPLATE:
            return f"{si.kname} {si.ename}".strip()
        if p.kind == BOARDING:
            return f"타는 곳 {p.content.get('dest', '')}".strip()
        return f"출구 {p.content.get('number', '')} {p.content.get('destinations', '')}".replace("\n", " ").strip()

    # ---------- 이미지 (텍스처 DAE) ----------
    def image(self, e: SignElementData):
        from signs.nameplate import render_boarding, render_exit, render_nameplate
        p, ss = e.placement, self.settings
        if e.kind == NAMEPLATE:
            return render_nameplate(ss.style, nameplate_input(ss, p.content["right_plus"]))
        if e.kind == BOARDING:
            return render_boarding(p.width, p.height, p.content.get("dest", ""), ss.station.rgb)
        return render_exit(p.width, p.height, p.content.get("number", ""), p.content.get("destinations", ""))

    def uv_frame(self, e: SignElementData) -> tuple:
        """이미지 면의 (왼쪽 아래 세계 좌표, 오른쪽 단위 벡터, 위쪽 단위 벡터, 폭, 높이, 구배) — 앞에서 볼 때.
        구배 = 오른쪽으로 1m 갈 때 판 하단이 오르는 높이 (판이 종단구배를 따르므로 텍스처 v 를 그만큼 보정)"""
        p, cfg = e.placement, self.cfg
        rs, rt = p.right()
        s0, t0 = p.s - rs * p.width / 2.0, p.t - rt * p.width / 2.0
        if not p.mounted:
            s0, t0 = s0 + p.normal[0] * p.thick / 2.0, t0 + p.normal[1] * p.thick / 2.0
        x0, y0 = cfg.to_world(s0, t0)
        x1, y1 = cfg.to_world(s0 + rs, t0 + rt)
        ln = math.hypot(x1 - x0, y1 - y0) or 1.0
        z0 = cfg.lv(s0) - cfg.station.offset + p.z0
        k = (cfg.lv(s0 + rs * p.width) - cfg.lv(s0)) / p.width
        return (x0, y0, z0), ((x1 - x0) / ln, (y1 - y0) / ln, 0.0), (0.0, 0.0, 1.0), p.width, p.height, k

    # ---------- 작도 ----------
    def add_sign_mesh(self, msp):
        """3D 메쉬 (STRUCT_SIGN 본체 / STRUCT_SIGN_FACE 이미지 면). 한 번만 호출할 것"""
        for e in self.elements:
            body = [msp.add_3dface(f, dxfattribs={"layer": "STRUCT_SIGN"}) for f in PM.mesh_faces(self.cfg, e.pieces[0])]
            e.face_entities = [msp.add_3dface(f, dxfattribs={"layer": "STRUCT_SIGN_FACE"})
                               for f in PM.mesh_faces(self.cfg, e.pieces[1])]
            e.source_element = body + e.face_entities

    def section_items(self, sta):
        items = []
        for e in self.elements:
            for p in e.pieces[:1]:
                cut = PM.section_rect(self.cfg, p, sta)
                if cut:
                    t0, t1, zb = cut
                    items.append(ViewItem.rect(e.name, "SEC_SIGN", t0, t1, zb, zb + p.shape.height))
        return items

    def profile_items(self, t_cut=0.0):
        return [PM.profile_view(self.cfg, e.pieces[0], "SEC_SIGN") for e in self.elements
                if CommonHelper.cut_by_t(*PM.t_range(e.pieces[0]), t_cut)]

    def plan_items(self, cut_h, floor=1):
        """평면도(floor 층): 사인 윤곽 + 문구 (매달림 사인은 절단 높이 위라도 표시)"""
        items = []
        for e in self.elements:
            if e.floor != floor:
                continue
            p = e.pieces[0]
            s0, s1 = PM.s_range(p)
            t0, t1 = PM.t_range(p)
            items.append(ViewItem.rect(e.name, "PLAN_SIGN", s0, s1, t0, t1))
            cs, ct = (s0 + s1) / 2.0, (t0 + t1) / 2.0
            items.append(ViewItem(f"{e.name}_TEXT", "PLAN_SIGN", u0=cs, u1=cs, pts=[],
                                  label=(e.text[:24], cs - 0.12 * min(len(e.text), 24), ct + 0.3, 0.25, "PLAN_SIGN")))
        return items
