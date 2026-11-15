from config.master_config import StationProjectConfig
from helper import prism_member as PM
from helper.geometry_helper import CommonHelper
from helper.view_item import ViewItem
from rooms.room_data import PartitionData, RoomBox, RoomData, RoomPiece
from rooms.room_layout import ceiling_rel


class RoomEngine:
    """실(IfcSpace)과 실 경계 칸막이벽(IfcWall PARTITIONING)을 만들고 3D DXF / 2D 도면 / IFC 의 단일 데이터 원천이 된다.

    - 배치는 cfg.room_layouts() 결과를 그대로 쓴다 (층별 입력 실 + 기본 실, 칸막이벽 조각)
    - 조각은 벽체·슬래브와 같은 선형 각기둥(helper.prism_member): 하면이 종단을 따르고 곡선에서는 스윕
    - 3D DXF 에는 칸막이벽만 그린다 (공간은 IFC·평면도 표기용)
    """

    def __init__(self, config: StationProjectConfig):
        self.cfg = config
        self.sp = config.station
        self.rooms: list[RoomData] = []
        self.partitions: list[PartitionData] = []
        self._build()

    def _piece(self, name, s0, s1, t0, t1, z0, z1) -> RoomPiece:
        cfg, off = self.cfg, self.sp.offset
        mid = (s0 + s1) / 2.0
        return RoomPiece(name=name, pos_x=mid, pos_y=(t0 + t1) / 2.0, pos_z=cfg.lv(mid) - off + z0,
                         shape=RoomBox(length=s1 - s0, width=t1 - t0, height=z1 - z0, rise=cfg.lv(s1) - cfg.lv(s0),
                                       curve_factor=PM.curve_factor(cfg, s0, s1, (t0 + t1) / 2.0)))

    def _build(self):
        for fl in self.cfg.room_layouts():
            level = self.sp.level_name(fl.floor)
            z0, z1 = self.sp.floor_level(fl.floor), ceiling_rel(self.sp, fl.floor)
            for r in fl.rooms:
                pieces = [self._piece(f"{r.name}_P{k}", *rect, z0, z1) for k, rect in enumerate(r.rects, start=1)]
                self.rooms.append(RoomData(name=r.name, family_name="실", type_name=r.use, level=level,
                                           pos_x=pieces[0].pos_x, pos_y=pieces[0].pos_y, pos_z=pieces[0].pos_z,
                                           use=r.use, floor=fl.floor, is_default=r.is_default, pieces=pieces))
            pt = self.cfg.room_settings.partition_t
            for pw in fl.partitions:
                pieces = [self._piece(f"{pw.name}_P{k}", *p) for k, p in enumerate(pw.pieces, start=1)]
                self.partitions.append(PartitionData(
                    name=pw.name, family_name="칸막이벽", type_name=f"{int(round(pt * 1000))}mm", level=level,
                    pos_x=pieces[0].pos_x, pos_y=pieces[0].pos_y, pos_z=pieces[0].pos_z,
                    material=self.cfg.room_settings.partition_material, floor=fl.floor, axis=pw.axis, pieces=pieces))

    def rooms_on(self, floor: int) -> list[RoomData]:
        return [r for r in self.rooms if r.floor == floor]

    # ---------- 작도 ----------
    def add_partition_mesh(self, msp):
        """3D 메쉬 (칸막이벽 = STRUCT_PARTITION). 한 번만 호출할 것"""
        for pw in self.partitions:
            faces = [f for p in pw.pieces for f in PM.mesh_faces(self.cfg, p)]
            pw.source_element = [msp.add_3dface(f, dxfattribs={"layer": "STRUCT_PARTITION"}) for f in faces]

    # ---------- 2D 도면 ----------
    def section_items(self, sta):
        """횡단면도: 측점 sta 가 자르는 칸막이벽 (해치)"""
        items = []
        for pw in self.partitions:
            for p in pw.pieces:
                cut = PM.section_rect(self.cfg, p, sta)
                if cut:
                    t0, t1, zb = cut
                    items.append(ViewItem.rect(pw.name, "SEC_PARTITION", t0, t1, zb, zb + p.shape.height,
                                               hatch_layer="SEC_HATCH"))
        return items

    def profile_items(self, t_cut=0.0):
        """종단면도(t = t_cut 절단): 절단면을 지나는 칸막이벽 (해치)"""
        items = []
        for pw in self.partitions:
            for p in pw.pieces:
                if CommonHelper.cut_by_t(*PM.t_range(p), t_cut):
                    items.append(PM.profile_view(self.cfg, p, "PROF_PARTITION", hatch_layer="PROF_HATCH"))
        return items

    def plan_items(self, cut_h, floor=1):
        """평면도(floor 층): 칸막이벽 윤곽 + 실 이름·면적 글자(PLAN_ROOM, 실 조각 중 가장 큰 것의 중심, 윤곽선 없음)"""
        items = []
        for pw in self.partitions:
            if pw.floor == floor:
                for p in pw.pieces:
                    s0, s1 = PM.s_range(p)
                    items.append(ViewItem.rect(pw.name, "PLAN_PARTITION", s0, s1, *PM.t_range(p)))
        for r in self.rooms_on(floor):
            big = max(r.pieces, key=lambda p: p.shape.length * p.shape.width)
            text = f"{r.use if r.is_default else r.name} ({r.area:.1f}m2)"
            items.append(ViewItem(r.name, "PLAN_ROOM", u0=big.pos_x, u1=big.pos_x, pts=[],
                                  label=(text, big.pos_x - 0.15 * len(text), big.pos_y, 0.6, "PLAN_ROOM")))
        return items
