import math

from config.master_config import StationProjectConfig
from entrances.entrance_data import EntranceData, EntranceElementData
from escalators.escalator_data import EscalatorData, EscalatorPartData
from escalators.escalator_engine import _FAMILY as ESC_FAMILY, _MATERIAL as ESC_MATERIAL, _SIDE as ESC_SIDE
from helper.box_piece import cut_faces_by_plane
from helper.strip_member import StripShape, part_faces, strip_faces
from helper.view_item import ViewItem
from stairs.stair_data import StairData, StairPartData
from stairs.stair_type import StairPartKind

_FAMILY = {"FLOOR": "콘크리트-출입구바닥슬래브", "ROOF": "콘크리트-출입구천장슬래브", "WALL": "콘크리트-출입구벽체"}


class EntranceEngine:
    """출입구 BIM 객체(박스 부재 + 계단 + 에스컬레이터)를 만들고, 3D DXF / 2D 도면 / IFC 의 단일 데이터 원천이 된다.

    - 배치는 cfg.entrance_layouts() 결과를 그대로 쓴다 (모든 부재는 출입구 좌표의 띠, 헌치는 세계 좌표 곧은 조각)
    - 출입구 좌표는 세계 평면에서 곧으므로 3D·IFC 는 곡선 선형에서도 정확하다
    - 횡단면도: 측점 sta 의 연직면으로 각 띠를 정확히 자른 다각형, 평면도: 최하층 통로에 붙은 출입구의 외곽
    """

    def __init__(self, config: StationProjectConfig):
        self.cfg = config
        self.sp = config.station
        self.entrances: list[EntranceData] = []
        self._build()

    def _build(self):
        floors = {p.name: p.floor for p in self.cfg.passage_layouts()}
        for lay in self.cfg.entrance_layouts():
            spec = lay.spec
            floor = floors[lay.passage]
            level = self.sp.level_name(floor)
            elements = []
            for p in lay.box_parts:
                t0, t1 = p.t_range
                elements.append(EntranceElementData(
                    name=f"{lay.name}_{p.code}", family_name=_FAMILY[p.kind], type_name=f"{int(round(spec.wall_t * 1000))}mm",
                    level=level, pos_z=min(min(s.zb0, s.zb1) for s in p.strips), material="Concrete_C24",
                    kind=p.kind, code=p.code, t_range=p.t_range, shape=StripShape(strips=p.strips, width=t1 - t0),
                    pieces=list(lay.haunches) if p.kind == "ROOF" else []))
            stair = self._stair(lay, level)
            escalator = self._escalator(lay, level) if lay.escalator else None
            self.entrances.append(EntranceData(
                name=lay.name, family_name="출입구", type_name=f"W{spec.inner_width:g}" + (" ESC" if spec.escalator else ""),
                level=level, pos_x=lay.frame.px, pos_y=lay.frame.py, pos_z=lay.z_floor, passage=lay.passage, floor=floor,
                frame=lay.frame, layout=lay, elements=elements, stair=stair, escalator=escalator))

    @staticmethod
    def _stair(lay, level) -> StairData:
        sp = lay.spec.stair_spec()
        t_rng = (sp.t_lo, sp.t_hi)
        parts, count = [], {StairPartKind.FLIGHT: 0, StairPartKind.LANDING: 0}
        for p in lay.stair.parts:
            count[p.kind] += 1
            flight = p.kind == StairPartKind.FLIGHT
            surfaces = [(lay.stair.start + ua, lay.stair.start + ub, zt) for ua, ub, zt in p.surfaces]
            parts.append(StairPartData(
                name=f"{lay.name}_STAIR_{p.kind.value}{count[p.kind]}",
                family_name="콘크리트-계단" if flight else "콘크리트-계단참",
                type_name=f"{p.n_risers}단" if flight else f"{int(round(sp.waist_t * 1000))}mm", level=level,
                pos_z=min(z for _, _, z in surfaces) if surfaces else lay.z_floor, material="Concrete_C24", kind=p.kind,
                n_risers=p.n_risers, n_treads=len(surfaces) if flight else 0, t_range=t_rng, surfaces=surfaces,
                shape=StripShape(strips=p.strips, width=t_rng[1] - t_rng[0])))
        s0 = parts[0].shape.strips[0].s0
        s1 = parts[-1].shape.strips[-1].s1
        return StairData(name=f"{lay.name}_STAIR", family_name="콘크리트-직선계단",
                         type_name=f"{lay.stair.n_risers}단 R{lay.stair.riser * 1000:.0f} T{sp.tread * 1000:.0f}",
                         level=level, pos_z=lay.z_floor, material="Concrete_C24", lower_floor=0, direction=1,
                         n_risers=lay.stair.n_risers, riser=lay.stair.riser, tread=sp.tread, s_range=(s0, s1),
                         t_range=t_rng, parts=parts)

    @staticmethod
    def _escalator(lay, level) -> EscalatorData:
        esp = lay.escalator.spec
        parts = []
        for p in lay.escalator.parts:
            t0, t1 = p.t_range
            parts.append(EscalatorPartData(
                name=f"{lay.name}_ESC_{p.kind.value}{ESC_SIDE[p.side]}", family_name=ESC_FAMILY[p.kind],
                type_name=f"S{int(round(esp.step_width * 1000))} {esp.angle_deg:g}°", level=level,
                pos_z=min(min(s.zb0, s.zb1) for s in p.strips), material=ESC_MATERIAL[p.kind], kind=p.kind,
                side=p.side, t_range=p.t_range, shape=StripShape(strips=p.strips, width=t1 - t0)))
        u = lay.u
        return EscalatorData(name=f"{lay.name}_ESC", family_name="에스컬레이터",
                             type_name=f"S{int(round(esp.step_width * 1000))} {esp.angle_deg:g}°", level=level,
                             pos_z=lay.z_floor, lower_floor=0, direction=1, angle_deg=esp.angle_deg,
                             rise=lay.escalator.rise, run=lay.escalator.run, s_wp=(u["wp_lo"], u["wp_hi"]),
                             s_range=(u["truss_lo"], u["truss_hi"]), t_range=(esp.t_lo, esp.t_hi), parts=parts)

    # ---------- 부재 모음 ----------
    def strip_members(self, ent: EntranceData) -> list:
        """(부재 이름, 띠 부재) — 박스 부재·계단 런/계단참·에스컬레이터 부재 (모두 출입구 좌표의 띠)"""
        out = [(e.name, e) for e in ent.elements]
        out += [(p.name, p) for p in ent.stair.parts]
        if ent.escalator:
            out += [(p.name, p) for p in ent.escalator.parts]
        return out

    # ---------- 작도 ----------
    def add_entrance_mesh(self, msp):
        """3D 절대 좌표계 메쉬 (출입구 좌표의 곧은 띠 + 헌치 조각). 한 번만 호출할 것"""
        for ent in self.entrances:
            for _, m in self.strip_members(ent):
                faces = [f for quads in part_faces(ent.frame, m) for f in quads]
                faces += [f for p in getattr(m, "pieces", []) for f in p.faces()]
                m.source_element = [msp.add_3dface(f, dxfattribs={"layer": "STRUCT_ENTRANCE"}) for f in faces]

    def section_items(self, sta):
        """횡단면도: 측점 sta 의 연직면으로 자른 출입구 부재 단면 (콘크리트는 해치, 설비는 윤곽만)"""
        cx, cy = self.cfg.to_world(sta, 0.0)
        th = self.cfg.theta_at(sta)
        nx, ny = math.cos(th), math.sin(th)
        items = []
        for ent in self.entrances:
            labeled = False
            for name, m in self.strip_members(ent):
                concrete = not isinstance(m, EscalatorPartData)
                t0, t1 = m.t_range
                polys = [cut_faces_by_plane(strip_faces(ent.frame, st, t0, t1), cx, cy, nx, ny) for st in m.shape.strips]
                polys += [p.cut_by_plane(cx, cy, nx, ny) for p in getattr(m, "pieces", [])]
                for poly in polys:
                    if poly is None:
                        continue
                    label = None
                    if not labeled:
                        label = (ent.name, min(w for w, _ in poly), max(z for _, z in poly) + 0.5, 0.4, "SEC_TEXT")
                        labeled = True
                    items.append(ViewItem(name, "SEC_CONCRETE" if concrete else "SEC_ESCALATOR",
                                          u0=min(w for w, _ in poly), u1=max(w for w, _ in poly), pts=poly,
                                          hatch_layer="SEC_HATCH" if concrete else None, label=label))
        return items

    def plan_items(self, cut_h, floor=1):
        """평면도(floor 층 절단): 그 층 통로에 붙은 출입구의 외곽 (정거장 로컬 (s, t) 다각형)"""
        items = []
        for ent in self.entrances:
            if ent.floor != floor:
                continue
            u_end = ent.layout.u["end"]
            b = ent.layout.spec.inner_width / 2.0 + ent.layout.spec.wall_t
            pts = [self.cfg.to_station(*ent.frame.to_world(u, t)) for u, t in ((0.0, -b), (u_end, -b), (u_end, b), (0.0, b))]
            s_lab, t_lab = self.cfg.to_station(*ent.frame.to_world(u_end / 2.0, 0.0))
            items.append(ViewItem(ent.name, "PLAN_PASSAGE", u0=min(p[0] for p in pts), u1=max(p[0] for p in pts), pts=pts,
                                  label=(f"{ent.name} ENTRANCE", s_lab, t_lab, 0.5, "PLAN_TEXT")))
        return items
