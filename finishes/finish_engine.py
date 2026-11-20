"""건축 마감 BIM 객체 (실별 바닥 마감·채움, 벽 마감, 기둥·승강로 둘레 마감, 천장판, 천장틀)를 만든다.

배치는 finish_layout.layout_room_finishes 결과. 사각 조각은 실·칸막이벽과 같은 선형 각기둥(RoomPiece), 원기둥 둘레는 BoxPiece.
3D DXF / 2D 도면 / IFC(IfcCovering + IfcMember, IfcRelCoversSpaces 로 실에 연결)의 단일 데이터 원천.
"""
import math
from dataclasses import dataclass, field

from bim_data.common_bim_data import CommonBIMData
from config.master_config import StationProjectConfig
from finishes.finish_layout import layout_room_finishes
from helper import prism_member as PM
from helper.geometry_helper import CommonHelper
from helper.view_item import ViewItem
from rooms.room_data import RoomBox, RoomPiece
from rooms.room_layout import resolve_room_names
from tactiles.tactile_layout import layout_tactile

# 부재 코드 → (IFC 엔티티, PredefinedType, 이름 꼬리, 레이어)
KINDS = {"FLOOR": ("IfcCovering", "FLOORING", "바닥 마감재", "FIN_FLOOR"),
         "FILL": ("IfcCovering", "FLOORING", "바닥 채움", "FIN_FLOOR"),
         "WALL": ("IfcCovering", "CLADDING", "벽 마감", "FIN_WALL"),
         "COLUMN": ("IfcCovering", "CLADDING", "기둥·승강로 마감", "FIN_WALL"),
         "CEILING": ("IfcCovering", "CEILING", "천장판", "FIN_CEILING"),
         "FRAME": ("IfcMember", "USERDEFINED", "천장틀", "FIN_FRAME")}


@dataclass
class FinishElementData(CommonBIMData):
    """마감 부재 1개 (실 하나의 한 종류). pieces = RoomPiece(선형 각기둥), boxes = BoxPiece(원기둥 둘레)"""
    code: str = ""
    room: str = ""
    pieces: list = field(default_factory=list)
    boxes: list = field(default_factory=list)

    @property
    def volume(self) -> float:
        return sum(p.shape.volume for p in self.pieces) + sum(b.volume for b in self.boxes)


@dataclass
class RoomFinishData(CommonBIMData):
    """실 하나의 마감 묶음. finish = FinishType, elements = FinishElementData (빈 종류는 없음)"""
    room: str = ""
    use: str = ""
    floor: int = 1
    finish: object = None
    ffl_rel: float = 0.0
    ceiling_rel: float = 0.0
    elements: list = field(default_factory=list)
    tactile: list = field(default_factory=list)      # 바닥 마감재를 대체한 점자블록 [(s0, s1, t0, t1, z0, z1, 종류)]

    def element(self, code: str):
        return next((e for e in self.elements if e.code == code), None)


def room_piece(cfg, name, s0, s1, t0, t1, z0, z1, trap=None) -> RoomPiece:
    """정거장 로컬 사각 조각 (s0..s1 × t0..t1, FL 기준 z0..z1) → 선형 각기둥 (하면이 종단을 따름).
    trap = (t0, t1 @ s0, t0, t1 @ s1) 이면 사다리꼴 조각 (구조물 확폭 전이부) — 폭·중심은 평균 (체적 정확)"""
    off = cfg.station.offset
    mid = (s0 + s1) / 2.0
    if trap is not None:
        lo, hi = (trap[0] + trap[2]) / 2.0, (trap[1] + trap[3]) / 2.0
    else:
        lo, hi = t0, t1
    return RoomPiece(name=name, pos_x=mid, pos_y=(lo + hi) / 2.0, pos_z=cfg.lv(mid) - off + z0, trap=trap,
                     shape=RoomBox(length=s1 - s0, width=hi - lo, height=z1 - z0, rise=cfg.lv(s1) - cfg.lv(s0),
                                   curve_factor=PM.curve_factor(cfg, s0, s1, (lo + hi) / 2.0)))


def column_footprints(cfg, column_engine) -> list:
    """기둥 평면 [(층, s, t, 반폭 s, 반폭 t, 반지름|None)] (마감·점자블록 배치가 기둥을 피할 때)"""
    if column_engine is None:
        return []
    sp = cfg.station
    floor_no = {sp.level_name(n): n for n in range(1, sp.floors + 1)}
    out = []
    for pk in column_engine.column_packages:
        for c in pk.columns:
            rad = getattr(c.shape, "radius", None)
            out.append((floor_no[pk.level], c.pos_x, c.pos_y, c.shape.half_s, c.shape.half_t, rad))
    return out


class FinishEngine:
    def __init__(self, config: StationProjectConfig, column_engine=None):
        self.cfg = config
        self.sp = config.station
        self.rooms: list[RoomFinishData] = []
        self._build(column_engine)

    def _columns(self, column_engine) -> list:
        return column_footprints(self.cfg, column_engine)

    def _piece(self, name, s0, s1, t0, t1, z0, z1, trap=None) -> RoomPiece:
        return room_piece(self.cfg, name, s0, s1, t0, t1, z0, z1, trap)

    def _build(self, column_engine):
        cfg = self.cfg
        if not cfg.finish_settings.enabled:
            return
        specs = dict(zip(resolve_room_names(cfg, cfg.rooms), cfg.rooms))
        columns = self._columns(column_engine)
        layouts = layout_room_finishes(cfg, cfg.finish_settings, cfg.room_layouts(), specs, columns,
                                       cfg.all_openings(), cfg.stair_layouts(), cfg.escalator_layouts(),
                                       cfg.elevator_layouts(), layout_tactile(cfg, columns))
        for rf in layouts:
            level = self.sp.level_name(rf.floor)
            ft = rf.finish
            groups = (("FLOOR", rf.floor_top, [], ft.floor_material, ft.floor_t),
                      ("FILL", rf.floor_fill, [], "몰탈", ft.ffl - ft.floor_t),
                      ("WALL", rf.walls, [], ft.wall_material, ft.wall_t),
                      ("COLUMN", rf.columns, rf.rings, ft.wall_material, ft.wall_t),
                      ("CEILING", rf.ceiling, [], ft.ceiling_material, ft.board_t),
                      ("FRAME", rf.bars + rf.carriers, [], f"{ft.frame}바 천장틀", ft.frame_depth))
            elements = []
            for code, rects, boxes, material, thick in groups:
                if not rects and not boxes:
                    continue
                name = f"FIN_{rf.room}_{code}"
                pieces = [self._piece(f"{name}_P{k}", *r) for k, r in enumerate(rects, start=1)]
                elements.append(FinishElementData(
                    name=name, family_name=KINDS[code][2], type_name=f"{material} {int(round(thick * 1000))}mm", level=level,
                    material=material, code=code, room=rf.room, pieces=pieces, boxes=list(boxes)))
            self.rooms.append(RoomFinishData(name=f"FIN_{rf.room}", family_name="실 마감", type_name=ft.name, level=level,
                                             room=rf.room, use=rf.use, floor=rf.floor, finish=ft, ffl_rel=rf.ffl_rel,
                                             ceiling_rel=rf.ceiling_rel, elements=elements, tactile=list(rf.tactile)))

    def all_elements(self) -> list:
        return [e for r in self.rooms for e in r.elements]

    # ---------- 작도 ----------
    def add_finish_mesh(self, msp):
        """3D 메쉬 (FIN_FLOOR / FIN_WALL / FIN_CEILING / FIN_FRAME). 한 번만 호출할 것"""
        for e in self.all_elements():
            layer = KINDS[e.code][3]
            faces = [f for p in e.pieces for f in PM.mesh_faces(self.cfg, p)] + [f for b in e.boxes for f in b.faces()]
            e.source_element = [msp.add_3dface(f, dxfattribs={"layer": layer}) for f in faces]

    # ---------- 2D 도면 ----------
    def section_items(self, sta):
        """횡단면도: 측점 sta 가 자르는 마감 (윤곽, 해치 없음)"""
        items = []
        th = self.cfg.theta_at(sta)
        cx, cy = self.cfg.to_world(sta, 0.0)
        nx, ny = math.cos(th), math.sin(th)
        for e in self.all_elements():
            for p in e.pieces:
                cut = PM.section_rect(self.cfg, p, sta)
                if cut:
                    t0, t1, zb = cut
                    items.append(ViewItem.rect(e.name, "SEC_FINISH", t0, t1, zb, zb + p.shape.height))
            for b in e.boxes:
                poly = b.cut_by_plane(cx, cy, nx, ny)
                if poly:
                    items.append(ViewItem(e.name, "SEC_FINISH", u0=min(w for w, _ in poly), u1=max(w for w, _ in poly), pts=poly))
        return items

    def profile_items(self, t_cut=0.0):
        """종단면도(t = t_cut 절단): 절단면을 지나는 마감 (윤곽)"""
        items = []
        for e in self.all_elements():
            for p in e.pieces:
                if CommonHelper.cut_by_t(*PM.t_range(p), t_cut):
                    items.append(PM.profile_view(self.cfg, p, "PROF_FINISH"))
        return items

    def plan_items(self, cut_h, floor=1):
        """평면도(floor 층): 절단 높이를 지나는 벽·기둥·승강로 마감 윤곽 (원기둥 둘레는 다각형)"""
        items = []
        for r in self.rooms:
            if r.floor != floor:
                continue
            for e in r.elements:
                if e.code not in ("WALL", "COLUMN"):
                    continue
                for p in e.pieces:
                    z0 = PM.z_off(self.cfg, p)
                    if z0 - 1e-9 <= cut_h < z0 + p.shape.height - 1e-9:
                        items.append(PM.plan_item(e.name, "PLAN_FINISH", p))
                for b in e.boxes:                           # 원기둥 둘레: 기둥 중심 기준으로 회전만 되돌림 (to_station 반복 계산 피함)
                    s, t, cx, cy, th = b.local["center"]
                    c, sn = math.cos(th), math.sin(th)
                    pts = [(s + (x - cx) * c + (y - cy) * sn, t - (x - cx) * sn + (y - cy) * c) for x, y in b.footprint()]
                    items.append(ViewItem(e.name, "PLAN_FINISH", u0=min(u for u, _ in pts), u1=max(u for u, _ in pts), pts=pts))
        return items
