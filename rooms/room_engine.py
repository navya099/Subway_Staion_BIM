import math

from config.master_config import StationProjectConfig
from helper import prism_member as PM
from helper.geometry_helper import CommonHelper
from helper.view_item import ViewItem
from rooms.room_data import DoorData, PartitionData, RoomBox, RoomData, RoomPiece, SeparationLineData
from rooms.room_layout import ceiling_rel
from rooms.room_spec import DOOR_KINDS, PARTITION


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
        self.partitions: list[PartitionData] = []        # 칸막이벽 + 구획분리 벽(두께 > 0)
        self.separations: list[SeparationLineData] = []  # 두께 없는 구획분리 경계선
        self.doors: list[DoorData] = []
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
            rs = self.cfg.room_settings
            for pw in fl.partitions:
                pieces = [self._piece(f"{pw.name}_P{k}", *p) for k, p in enumerate(pw.pieces, start=1)]
                part = pw.kind == PARTITION
                self.partitions.append(PartitionData(
                    name=pw.name, family_name="칸막이벽" if part else "구획분리벽",
                    type_name=f"{int(round(pw.thickness * 1000))}mm", level=level,
                    pos_x=pieces[0].pos_x, pos_y=pieces[0].pos_y, pos_z=pieces[0].pos_z,
                    material=rs.partition_material if part else rs.separation_material, floor=fl.floor, axis=pw.axis,
                    kind=pw.kind, thickness=pw.thickness, pieces=pieces))
            walls = {pw.name: pw for pw in fl.partitions}
            for d in fl.doors:
                o, lf = d.opening, d.leaf
                wall_t = (o[1] - o[0]) if d.side in ("+s", "-s") else (o[3] - o[2])
                self.doors.append(DoorData(
                    name=d.name, family_name="문", type_name=f"{d.kind} {d.width:g}x{d.height:g}", level=level,
                    pos_x=(lf[0] + lf[1]) / 2.0, pos_y=(lf[2] + lf[3]) / 2.0,
                    pos_z=self.cfg.lv((lf[0] + lf[1]) / 2.0) - self.sp.offset + lf[4],
                    material="Steel" if d.kind == "방화문" else "Door_Panel", room=d.room, wall=d.wall, floor=fl.floor,
                    side=d.side, kind=d.kind, operation=DOOR_KINDS[d.kind], width=d.width, height=d.height,
                    wall_t=wall_t if d.wall in walls else 0.0,
                    opening=self._piece(f"OPEN_{d.name}", *o), leaf=self._piece(f"{d.name}_LEAF", *lf)))
            for sl in fl.separations:
                s0, s1, t0, t1 = sl.rect
                self.separations.append(SeparationLineData(
                    name=sl.name, family_name="구획분리선", type_name="가상 경계", level=level, pos_x=(s0 + s1) / 2.0,
                    pos_y=(t0 + t1) / 2.0, pos_z=self.cfg.lv((s0 + s1) / 2.0) - self.sp.offset + sl.z_rel,
                    floor=fl.floor, axis=sl.axis, rect=sl.rect, z_rel=sl.z_rel))

    def rooms_on(self, floor: int) -> list[RoomData]:
        return [r for r in self.rooms if r.floor == floor]

    # ---------- 작도 ----------
    def add_partition_mesh(self, msp):
        """3D 메쉬 (칸막이벽 = STRUCT_PARTITION). 한 번만 호출할 것"""
        for pw in self.partitions:
            layer = "STRUCT_PARTITION" if pw.kind == PARTITION else "STRUCT_SEPARATION"
            faces = [f for p in pw.pieces for f in PM.mesh_faces(self.cfg, p)]
            pw.source_element = [msp.add_3dface(f, dxfattribs={"layer": layer}) for f in faces]
        for d in self.doors:
            d.source_element = [msp.add_3dface(f, dxfattribs={"layer": "STRUCT_DOOR"}) for f in PM.mesh_faces(self.cfg, d.leaf)]

    # ---------- 2D 도면 ----------
    def section_items(self, sta):
        """횡단면도: 측점 sta 가 자르는 칸막이벽 (해치) + 문짝 (윤곽)"""
        items = []
        for pw in self.partitions:
            for p in pw.pieces:
                cut = PM.section_rect(self.cfg, p, sta)
                if cut:
                    t0, t1, zb = cut
                    items.append(ViewItem.rect(pw.name, "SEC_PARTITION", t0, t1, zb, zb + p.shape.height,
                                               hatch_layer="SEC_HATCH"))
        for d in self.doors:
            cut = PM.section_rect(self.cfg, d.leaf, sta)
            if cut:
                t0, t1, zb = cut
                items.append(ViewItem.rect(d.name, "SEC_DOOR", t0, t1, zb, zb + d.leaf.shape.height))
        return items

    def profile_items(self, t_cut=0.0):
        """종단면도(t = t_cut 절단): 절단면을 지나는 칸막이벽 (해치) + 문짝 (윤곽)"""
        items = []
        for pw in self.partitions:
            for p in pw.pieces:
                if CommonHelper.cut_by_t(*PM.t_range(p), t_cut):
                    items.append(PM.profile_view(self.cfg, p, "PROF_PARTITION", hatch_layer="PROF_HATCH"))
        for d in self.doors:
            if CommonHelper.cut_by_t(*PM.t_range(d.leaf), t_cut):
                items.append(PM.profile_view(self.cfg, d.leaf, "PROF_DOOR"))
        return items

    @staticmethod
    def _door_symbol(d: DoorData) -> list:
        """평면 문 기호: 여닫이 = 실 안쪽으로 90° 연 문짝 + 호 (부채꼴), 양개 = 반폭 둘, 미닫이 = 실 안쪽 벽면에 붙은 문짝"""
        lf = d.leaf
        s0, s1 = PM.s_range(lf)
        t0, t1 = PM.t_range(lf)
        along_s = d.side in ("+t", "-t")                       # 문이 s 방향으로 놓임 (t 일정한 벽)
        sign = -1.0 if d.side in ("+s", "+t") else 1.0          # 실 안쪽 방향
        line = (t0 + t1) / 2.0 if along_s else (s0 + s1) / 2.0
        a, b = (s0, s1) if along_s else (t0, t1)
        face = line + sign * d.wall_t / 2.0                     # 실 쪽 벽면

        def pt(u, off):
            return (u, face + sign * off) if along_s else (face + sign * off, u)
        if d.operation.startswith("SLIDING"):
            return [ViewItem(d.name, "PLAN_DOOR", u0=min(a, b), u1=max(a, b),
                             pts=[pt(a, 0.0), pt(b, 0.0), pt(b, 0.05), pt(a, 0.05)])]
        leaves = [(a, b - a, 1.0)] if not d.operation.startswith("DOUBLE") else [(a, (b - a) / 2.0, 1.0), (b, (b - a) / 2.0, -1.0)]
        out = []
        for hinge, w, direc in leaves:
            arc = [pt(hinge + direc * w * math.cos(math.radians(k * 15)), w * math.sin(math.radians(k * 15))) for k in range(7)]
            pts = [pt(hinge, 0.0)] + arc
            out.append(ViewItem(d.name, "PLAN_DOOR", u0=min(p[0] for p in pts), u1=max(p[0] for p in pts), pts=pts))
        return out

    def plan_items(self, cut_h, floor=1):
        """평면도(floor 층): 칸막이벽·구획분리 벽 윤곽 + 가상 경계선 + 실 이름·면적 글자(PLAN_ROOM, 실 조각 중 가장 큰 것의 중심, 윤곽선 없음)"""
        items = []
        for pw in self.partitions:
            if pw.floor == floor:
                layer = "PLAN_PARTITION" if pw.kind == PARTITION else "PLAN_SEPARATION"
                for p in pw.pieces:
                    z0 = PM.z_off(self.cfg, p)                     # 절단 높이를 지나는 조각만 (문 위 인방은 안 보임)
                    if not z0 - 1e-9 <= cut_h < z0 + p.shape.height - 1e-9:
                        continue
                    s0, s1 = PM.s_range(p)
                    items.append(ViewItem.rect(pw.name, layer, s0, s1, *PM.t_range(p)))
        for d in self.doors:
            if d.floor == floor:
                items += self._door_symbol(d)
        for sl in self.separations:                       # 가상 경계선 = 선 하나
            if sl.floor == floor:
                s0, s1, t0, t1 = sl.rect
                items.append(ViewItem(sl.name, "PLAN_SEPARATION", u0=s0, u1=s1, pts=[(s0, t0), (s1, t1)]))
        for r in self.rooms_on(floor):
            big = max(r.pieces, key=lambda p: p.shape.length * p.shape.width)
            text = f"{r.use if r.is_default else r.name} ({r.area:.1f}m2)"
            items.append(ViewItem(r.name, "PLAN_ROOM", u0=big.pos_x, u1=big.pos_x, pts=[],
                                  label=(text, big.pos_x - 0.15 * len(text), big.pos_y, 0.6, "PLAN_ROOM")))
        return items
