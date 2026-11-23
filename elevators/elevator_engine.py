from config.master_config import StationProjectConfig
from elevators.elevator_data import ElevatorData, ElevatorElementData
from elevators.elevator_type import ElevatorPartKind as K
from helper.geometry_helper import CommonHelper
from helper.strip_member import part_faces, section_spans
from helper.view_item import ViewItem

_FAMILY = {K.HOIST_WALL: "콘크리트-승강로벽", K.PIT_SLAB: "콘크리트-엘리베이터피트슬래브", K.TOP_SLAB: "콘크리트-승강로천장슬래브",
           K.CAR_FLOOR: "엘리베이터-카바닥", K.CAR_WALL: "엘리베이터-카벽", K.CAR_ROOF: "엘리베이터-카천장",
           K.CAR_DOOR: "엘리베이터-카문", K.PIT_WALL: "콘크리트-엘리베이터피트벽", K.COLUMN: "강관-승강로기둥",
           K.GIRT: "강관-승강로가로재", K.GLASS: "강화유리-승강로", K.PANEL: "금속패널-승강로띠"}
_MATERIAL = {K.COLUMN: "EV_Steel_Pipe", K.GIRT: "EV_Steel_Pipe", K.GLASS: "EV_Glass", K.PANEL: "갈바륨 패널"}
_LAYER = {K.COLUMN: "STRUCT_ELEVATOR_FRAME", K.GIRT: "STRUCT_ELEVATOR_FRAME", K.PANEL: "STRUCT_ELEVATOR_FRAME",
          K.GLASS: "STRUCT_ELEVATOR_GLASS"}
CONCRETE_KINDS = (K.HOIST_WALL, K.PIT_SLAB, K.TOP_SLAB, K.PIT_WALL)


def tri_faces(faces) -> list:
    """3DFACE 는 꼭짓점 4개까지 — 그보다 많은 면은 첫 꼭짓점 기준 부채꼴 삼각형으로 (볼록 다각형)"""
    out = []
    for f in faces:
        if len(f) <= 4:
            out.append(f)
        else:
            out += [(f[0], f[i], f[i + 1]) for i in range(1, len(f) - 1)]
    return out


def ev_part_faces(cfg, p) -> list:
    """조각의 면 목록 (상자 띠 = strip 면, 기둥·가로재 = 조각 면)"""
    if p.solid is not None:
        return list(p.solid.faces())
    return [f for fs in part_faces(cfg, p) for f in fs]


class ElevatorEngine:
    """엘리베이터 BIM 객체(승강로 벽·피트·천장 슬래브, 카 바닥·벽·천장·문)를 만들고 3D DXF / 2D 도면 / IFC 의 단일 데이터 원천이 된다.

    - 배치(정지 바닥, 출입구, 슬래브 자동 오프닝)는 cfg.elevator_layouts() 결과를 그대로 쓴다 (슬래브·승강장 엔진과 같은 계산)
    - 모든 부재는 정거장 로컬 상자 띠(helper.strip_member) → 3D 는 strip 면, 2D 는 section_spans / 상자 윤곽
    """

    def __init__(self, config: StationProjectConfig):
        self.cfg = config
        self.sp = config.station
        self.elevators: list[ElevatorData] = []
        self._build()

    def _build(self):
        for lay in self.cfg.elevator_layouts():
            spec = lay.spec
            level = self.sp.level_name(lay.lower_floor)
            groups: dict = {}
            for p in lay.parts:
                groups.setdefault(p.code, []).append(p)
            elements = []
            for code, parts in groups.items():
                kind = parts[0].kind
                car = kind.is_car
                thick = {K.HOIST_WALL: spec.wall_t, K.PIT_SLAB: spec.pit_slab_t, K.TOP_SLAB: spec.top_slab_t,
                         K.CAR_FLOOR: spec.car_floor_t, K.CAR_WALL: spec.car_wall_t, K.CAR_ROOF: spec.car_roof_t,
                         K.CAR_DOOR: spec.car_wall_t, K.PIT_WALL: spec.wall_t, K.COLUMN: spec.col_d,
                         K.GIRT: spec.girt_d, K.GLASS: spec.glass_t, K.PANEL: spec.panel_t}[kind]
                elements.append(ElevatorElementData(
                    name=f"{lay.name}_{code}", family_name=_FAMILY[kind], type_name=f"{int(round(thick * 1000))}mm",
                    level=level, pos_z=min(p.z_range[0] for p in parts),
                    material="Steel" if car else _MATERIAL.get(kind, "Concrete_C24"),
                    kind=kind, code=code, parts=parts))
            self.elevators.append(ElevatorData(
                name=lay.name, family_name="엘리베이터",
                type_name=("투시형 " if spec.shaft == "glass" else "") + f"승강로 {spec.inner_s:g}x{spec.inner_t:g}",
                level=level, pos_x=spec.s_center, pos_y=spec.t_center, pos_z=lay.z_range[0],
                lower_floor=lay.lower_floor, upper_floor=lay.upper_floor, car_floor=spec.stop_car,
                on_platform=lay.on_platform, stops=lay.stops, outer=spec.outer_rect(), inner=spec.inner_rect(),
                door_openings=lay.door_openings, elements=elements))

    def all_elevators(self) -> list[ElevatorData]:
        return list(self.elevators)

    def members(self, ev: ElevatorData) -> list:
        """(부재, 조각) 목록 — 체적·면 계산용 (면 = ev_part_faces)"""
        return [(e, p) for e in ev.elements for p in e.parts]

    # ---------- 작도 ----------
    def add_elevator_mesh(self, msp):
        """3D 메쉬 (RC 승강로·피트 = STRUCT_ELEVATOR, 카 = STRUCT_ELEVATOR_CAR, 투시형 강관·금속 패널 = STRUCT_ELEVATOR_FRAME,
        유리 = STRUCT_ELEVATOR_GLASS). 한 번만 호출할 것"""
        for ev in self.elevators:
            for e in ev.elements:
                layer = "STRUCT_ELEVATOR_CAR" if e.kind.is_car else _LAYER.get(e.kind, "STRUCT_ELEVATOR")
                faces = tri_faces([f for p in e.parts for f in ev_part_faces(self.cfg, p)])
                e.source_element = [msp.add_3dface(f, dxfattribs={"layer": layer}) for f in faces]

    # ---------- 2D 도면 ----------
    def section_items(self, sta):
        """횡단면도: 측점 sta 가 지나는 승강로(RC 해치)·카·투시형 부재(윤곽) 단면"""
        import math
        items = []
        cx, cy = self.cfg.to_world(sta, 0.0)
        th = self.cfg.theta_at(sta)
        nx, ny = math.cos(th), math.sin(th)
        for ev in self.elevators:
            labeled = False
            for e in ev.elements:
                for p in e.parts:
                    if p.solid is not None:                     # 기둥·가로재: 연직면으로 자른 다각형
                        if not p.s_range[0] - 1e-9 <= sta <= p.s_range[1] + 1e-9:
                            continue
                        poly = p.solid.cut_by_plane(cx, cy, nx, ny)
                        if poly:
                            items.append(ViewItem(e.name, "SEC_ELEVATOR", u0=min(w for w, _ in poly), u1=max(w for w, _ in poly),
                                                  pts=poly))
                        continue
                    for t0, t1, zb, zt in section_spans(p, sta):
                        label = None
                        if not labeled and not e.kind.is_car:
                            label = (ev.name, ev.outer[3] + 0.3, ev.stops[ev.lower_floor] + 0.5, 0.4, "SEC_TEXT")
                            labeled = True
                        if e.kind not in CONCRETE_KINDS:
                            items.append(ViewItem.rect(e.name, "SEC_ELEVATOR", t0, t1, zb, zt))
                        else:
                            items.append(ViewItem.rect(e.name, "SEC_CONCRETE", t0, t1, zb, zt, hatch_layer="SEC_HATCH",
                                                       merge=True, label=label))
        return items

    def profile_items(self, t_cut=0.0):
        """종단면도(t = t_cut 절단): 절단면을 지나는 승강로(해치)·카(윤곽) 상자, 아니면 측면에 보이는 승강로 외곽 1개"""
        items = []
        for ev in self.elevators:
            S0, S1, T0, T1 = ev.outer
            if not CommonHelper.cut_by_t(T0, T1, t_cut):
                z0 = min(p.z_range[0] for e in ev.hoistway for p in e.parts)
                z1 = max(p.z_range[1] for e in ev.hoistway for p in e.parts)
                items.append(ViewItem.rect(ev.name, "PROF_BEYOND", S0, S1, z0, z1,
                                           label=(f"{ev.name} EV", S0, z1 + 0.5, 0.6, "PROF_TEXT")))
                continue
            for e in ev.elements:
                for p in e.parts:
                    if not CommonHelper.cut_by_t(*p.t_range, t_cut):
                        continue
                    (s0, s1), (zb, zt) = p.s_range, p.z_range
                    if e.kind not in CONCRETE_KINDS:
                        items.append(ViewItem.rect(e.name, "PROF_ESCALATOR", s0, s1, zb, zt))
                    else:
                        items.append(ViewItem.rect(e.name, "PROF_CONCRETE", s0, s1, zb, zt, hatch_layer="PROF_HATCH",
                                                   merge=True))
        return items

    def plan_items(self, cut_h, floor=1):
        """평면도(floor 층): 그 층에 정지하는 승강로의 외곽·내공 + 엘리베이터 기호(X) + 그 층에 서 있는 카 외곽 + 이름"""
        items = []
        for ev in self.elevators:
            if not ev.lower_floor <= floor <= ev.upper_floor:
                continue
            S0, S1, T0, T1 = ev.outer
            s0, s1, t0, t1 = ev.inner
            items.append(ViewItem.rect(f"{ev.name}_OUTER", "PLAN_ELEVATOR", S0, S1, T0, T1,
                                       label=(f"{ev.name} EV", S0, T1 + 0.3, 0.5, "PLAN_TEXT")))
            items.append(ViewItem.rect(f"{ev.name}_INNER", "PLAN_ELEVATOR", s0, s1, t0, t1))
            for e in ev.elements:                                    # 투시형 모서리 기둥 (원)
                if e.kind == K.COLUMN:
                    p = e.parts[0]
                    (a, b), (c, d) = p.s_range, p.t_range
                    import math as _m
                    r, cs_, ct_ = (b - a) / 2.0, (a + b) / 2.0, (c + d) / 2.0
                    pts = [(cs_ + r * _m.cos(2 * _m.pi * k / 16), ct_ + r * _m.sin(2 * _m.pi * k / 16)) for k in range(17)]
                    items.append(ViewItem(e.name, "PLAN_ELEVATOR", u0=a, u1=b, pts=pts))
            items.append(ViewItem(f"{ev.name}_X1", "PLAN_ELEVATOR", u0=s0, u1=s1, pts=[(s0, t0), (s1, t1)]))
            items.append(ViewItem(f"{ev.name}_X2", "PLAN_ELEVATOR", u0=s0, u1=s1, pts=[(s0, t1), (s1, t0)]))
            if floor == ev.car_floor:
                fl = ev.element("CAR_FLOOR").parts[0]
                (a, b), (c, d) = fl.s_range, fl.t_range
                items.append(ViewItem.rect(f"{ev.name}_CAR", "PLAN_ELEVATOR", a, b, c, d))
        return items
