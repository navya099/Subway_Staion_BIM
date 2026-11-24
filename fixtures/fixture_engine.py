"""천장 기구 BIM 객체 (조명·디퓨저): 기구마다 1개 = 몸체(천장판 위) + 면(천장판 하면 아래, 이미지 한 장), 선형 각기둥(RoomPiece).

배치는 finish_layout (RoomFinishData.lights / diffusers — 천장판·천장틀은 그 자리를 비움). 3D DXF(FIN_LIGHT / FIN_DIFFUSER) /
횡단·종단(SEC_FINISH 윤곽) / IFC(IfcLightFixture · IfcAirTerminal DIFFUSER, 층 storey) 의 단일 원천. 웹 뷰어는 같은 부재를
형상 하나 + 배치 목록(instances)으로 보냄 — instance() 의 변환이 RoomPiece 꼭짓점과 같음.
"""
import math
from dataclasses import dataclass

from bim_data.common_bim_data import CommonBIMData
from finishes.finish_engine import room_piece
from fixtures.fixture_layout import DEPTH, FACE
from helper import prism_member as PM
from helper.geometry_helper import CommonHelper
from helper.view_item import ViewItem

LIGHT, DIFFUSER = "LIGHT", "DIFFUSER"
LAYERS = {LIGHT: "FIN_LIGHT", DIFFUSER: "FIN_DIFFUSER"}
LABELS = {LIGHT: "매입 평판 조명", DIFFUSER: "사각 디퓨저"}
FACE_MATERIAL = {LIGHT: "조명", DIFFUSER: "디퓨저"}
BODY_MATERIAL = "기구 몸체"


@dataclass
class FixtureData(CommonBIMData):
    """기구 1개. rect = (s0, s1, t0, t1), z = 천장판 하면 (FL 기준), along = 긴 방향 ('s' | 't')"""
    kind: str = LIGHT
    room: str = ""
    floor: int = 1
    rect: tuple = (0.0, 0.0, 0.0, 0.0)
    z: float = 0.0
    along: str = "s"
    depth: float = 0.08
    host: str = ""                # 통로·출입구 이름 (실 = "", corridor_fixtures)
    body: object = None
    face: object = None

    @property
    def volume(self) -> float:
        return sum(p.volume if hasattr(p, "faces") else p.shape.volume for p in (self.body, self.face))      # 통로·출입구 = BoxPiece


class FixtureEngine:
    def __init__(self, config, finish_engine):
        self.cfg = config
        self.elements: list[FixtureData] = []
        st = config.station
        from rooms.room_layout import ceiling_rel
        for r in finish_engine.rooms:
            top = ceiling_rel(st, r.floor)
            for kind, rects, tag in ((LIGHT, r.lights, "LT"), (DIFFUSER, r.diffusers, "DF")):
                for k, q in enumerate(rects, start=1):
                    name = f"{tag}_{r.room}_{k:03d}"
                    rect, c = tuple(q[:4]), r.ceiling_rel
                    depth = min(DEPTH[kind], top - c)
                    body = room_piece(config, f"{name}_BODY", *rect, c, c + depth)
                    face = room_piece(config, f"{name}_FACE", *rect, c - FACE[kind], c)
                    w, l = sorted((rect[1] - rect[0], rect[3] - rect[2]))
                    self.elements.append(FixtureData(
                        name=name, family_name="천장 기구", type_name=f"{LABELS[kind]} {w:g}x{l:g}", level=st.level_name(r.floor),
                        material=FACE_MATERIAL[kind], pos_x=body.pos_x, pos_y=body.pos_y, pos_z=face.pos_z, kind=kind, room=r.room,
                        floor=r.floor, rect=rect, z=c, along=q[4] if len(q) > 4 else "s", depth=depth, body=body, face=face))

    # ---------- 작도 ----------
    def add_fixture_mesh(self, msp):
        """3D 메쉬 (FIN_LIGHT / FIN_DIFFUSER). 한 번만 호출할 것"""
        for e in self.elements:
            add = lambda p: [msp.add_3dface(f, dxfattribs={"layer": LAYERS[e.kind]}) for f in PM.mesh_faces(self.cfg, p)]
            e.body_entities, e.face_entities = add(e.body), add(e.face)
            e.source_element = e.body_entities + e.face_entities

    def frame(self, e) -> tuple:
        """면 아래쪽 이미지 한 장의 텍스처 틀 (원점, u = 짧은 방향, v = 긴 방향, 폭, 길이)"""
        s0, s1, t0, t1 = e.rect
        o = self.cfg.to_world(s0, t0)
        th = self.cfg.theta_at((s0 + s1) / 2.0)
        es, et = (math.cos(th), math.sin(th), 0.0), (-math.sin(th), math.cos(th), 0.0)
        u, v, w, h = (et, es, t1 - t0, s1 - s0) if e.along == "s" else (es, et, s1 - s0, t1 - t0)
        return (o[0], o[1], 0.0), u, v, w, h

    def instance(self, e) -> tuple:
        """웹 뷰어 배치: (x, y, z, cosθ, sinθ, 구배, s 축척) — 로컬 (ds, dt, dz) → 세계 (기구 평면 중심·천장판 하면 기준)"""
        s0, s1, t0, t1 = e.rect
        cfg, sm, tm = self.cfg, (s0 + s1) / 2.0, (t0 + t1) / 2.0
        x, y = cfg.to_world(sm, tm)
        a, b = cfg.to_world(s0, tm), cfg.to_world(s1, tm)
        th = math.atan2(b[1] - a[1], b[0] - a[0])
        return x, y, cfg.lv(sm) - cfg.station.offset + e.z, math.cos(th), math.sin(th), (cfg.lv(s1) - cfg.lv(s0)) / (s1 - s0), math.hypot(b[0] - a[0], b[1] - a[1]) / (s1 - s0)

    # ---------- 2D 도면 ----------
    def section_items(self, sta):
        """횡단면도: 측점 sta 가 자르는 기구 (윤곽)"""
        items = []
        for e in self.elements:
            if not e.rect[0] - 1e-9 <= sta <= e.rect[1] + 1e-9:
                continue
            for p in (e.body, e.face):
                cut = PM.section_rect(self.cfg, p, sta)
                if cut:
                    t0, t1, zb = cut
                    items.append(ViewItem.rect(e.name, "SEC_FINISH", t0, t1, zb, zb + p.shape.height))
        return items

    def profile_items(self, t_cut=0.0):
        return [PM.profile_view(self.cfg, p, "PROF_FINISH") for e in self.elements if CommonHelper.cut_by_t(e.rect[2], e.rect[3], t_cut)
                for p in (e.body, e.face)]

    def plan_items(self, cut_h, floor=1):
        """평면도에는 그리지 않음 (절단 높이 위 — 천장 평면도는 다음 단계)"""
        return []
