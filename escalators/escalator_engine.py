from config.master_config import StationProjectConfig
from escalators.escalator_data import EscalatorData, EscalatorPartData
from escalators.escalator_package import EscalatorPackage
from escalators.escalator_type import EscalatorPartKind
from helper.geometry_helper import CommonHelper
from helper.strip_member import StripShape, part_faces, section_spans
from helper.view_item import ViewItem
from slabs.slab_engine import SlabEngine

_FAMILY = {EscalatorPartKind.TRUSS: "에스컬레이터-트러스", EscalatorPartKind.STEPS: "에스컬레이터-스텝",
           EscalatorPartKind.BALUSTRADE: "에스컬레이터-난간패널", EscalatorPartKind.HANDRAIL: "에스컬레이터-핸드레일"}
_MATERIAL = {EscalatorPartKind.TRUSS: "Steel_Truss", EscalatorPartKind.STEPS: "Aluminium_Step",
             EscalatorPartKind.BALUSTRADE: "Glass_Balustrade", EscalatorPartKind.HANDRAIL: "Rubber_Handrail"}
_SIDE = {0: "", 1: "_L", -1: "_R"}          # L = t 큰 쪽 (진행방향 왼쪽 +)


class EscalatorEngine:
    """에스컬레이터 BIM 객체(트러스·스텝·난간 패널·핸드레일)를 만들고, 3D DXF / 2D 도면 / IFC 의 단일 데이터 원천이 된다.

    - 배치(WP·부재 띠·위층 오프닝·하부 피트)는 cfg.escalator_layouts() 결과를 그대로 쓴다 (슬래브·승강장 엔진과 같은 계산)
    - 에스컬레이터는 시작 층의 BIM 객체 (IFC: IfcTransportElement ESCALATOR 가 구성 부재를 묶음)
    """

    def __init__(self, config: StationProjectConfig):
        self.cfg = config
        self.sp = config.station
        self.escalator_packages: list[EscalatorPackage] = []
        self._build()

    def _build(self):
        by_level: dict[str, EscalatorPackage] = {}
        for lay in self.cfg.escalator_layouts():
            spec = lay.spec
            level = self.sp.level_name(lay.lower_floor)
            package = by_level.setdefault(level, EscalatorPackage(level=level, package_id=f"PKG_{level}_ESCALATORS"))
            parts = []
            for p in lay.parts:
                t0, t1 = p.t_range
                s_lo, s_hi = p.strips[0].s0, p.strips[-1].s1
                parts.append(EscalatorPartData(
                    name=f"{lay.name}_{p.kind.value}{_SIDE[p.side]}", family_name=_FAMILY[p.kind],
                    type_name=f"S{int(round(spec.step_width * 1000))} {spec.angle_deg:g}°", level=level,
                    pos_x=(s_lo + s_hi) / 2.0, pos_y=(t0 + t1) / 2.0, pos_z=min(min(st.zb0, st.zb1) for st in p.strips),
                    material=_MATERIAL[p.kind], kind=p.kind, side=p.side, t_range=p.t_range,
                    shape=StripShape(strips=p.strips, width=t1 - t0)))
            s0, s1 = lay.s_range
            t0, t1 = lay.t_range
            names = [lay.opening.name] + ([lay.pit_opening.name] if lay.pit_opening else []) + \
                    ([lay.platform_hole[0]] if lay.platform_hole else [])
            package.add_escalator(EscalatorData(
                name=lay.name, family_name="에스컬레이터", type_name=f"S{int(round(spec.step_width * 1000))} {spec.angle_deg:g}°",
                level=level, pos_x=(s0 + s1) / 2.0, pos_y=(t0 + t1) / 2.0,
                pos_z=self.cfg.lv(lay.s_at(0.0)) - self.sp.offset + lay.base_level,      # 하부 WP 표고
                lower_floor=lay.lower_floor, direction=spec.direction, on_platform=lay.on_platform,
                angle_deg=spec.angle_deg, rise=lay.rise, run=lay.run, s_wp=lay.s_wp, s_range=lay.s_range,
                t_range=lay.t_range, opening_names=names, parts=parts))
        floor_no = {self.sp.level_name(n): n for n in range(1, self.sp.floors + 1)}
        self.escalator_packages = sorted(by_level.values(), key=lambda pk: floor_no[pk.level])

    def all_escalators(self) -> list[EscalatorData]:
        return [e for pk in self.escalator_packages for e in pk.escalators]

    # ---------- 검사 ----------
    def check_columns(self, column_engine):
        """트러스 평면이 시작 층 기둥과 겹치지 않는지 검사 (위층·피트 쪽 기둥은 자동 오프닝의 기둥 검사에서 걸러짐)"""
        for esc in self.all_escalators():
            rect = (*esc.s_range, *esc.t_range)
            for pk in column_engine.column_packages:
                if pk.level != esc.level:
                    continue
                for col in pk.columns:
                    if SlabEngine._rect_hits_column(rect, col):
                        raise ValueError(f"에스컬레이터 {esc.name}: {esc.level} 기둥 {col.name} 과(와) 겹칩니다 "
                                         "(에스컬레이터 위치 또는 기둥 배치를 확인하세요)")

    # ---------- 작도 ----------
    def add_escalator_mesh(self, msp):
        """3D 절대 좌표계 메쉬 (부재마다 띠 각기둥, 곡선이면 선형을 따라 휨). 한 번만 호출할 것"""
        for esc in self.all_escalators():
            for part in esc.parts:
                faces = [f for quads in part_faces(self.cfg, part) for f in quads]
                part.source_element = [msp.add_3dface(f, dxfattribs={"layer": "STRUCT_ESCALATOR"}) for f in faces]

    # ---------- 2D 도면 ----------
    def section_items(self, sta):
        """횡단면도: 측점 sta 에 걸리는 부재 절단면 (설비라 해치 없음, 에스컬레이터마다 이름 라벨 1개)"""
        items = []
        for esc in self.all_escalators():
            labeled = False
            for part in esc.parts:
                for t0, t1, zb, zt in section_spans(part, sta):
                    label = None
                    if not labeled and part.kind == EscalatorPartKind.TRUSS:
                        label = (esc.name, t0 + 0.1, zt + 1.3, 0.4, "SEC_TEXT")
                        labeled = True
                    items.append(ViewItem.rect(part.name, "SEC_ESCALATOR", t0, t1, zb, zt, label=label))
        return items

    def profile_items(self):
        """종단면도: 트러스·스텝·한쪽 난간/핸드레일 윤곽 (중심선이 지나면 절단, 아니면 측면에 보이는 윤곽)"""
        items = []
        for esc in self.all_escalators():
            for part in esc.parts:
                if part.side < 0:                                # 측면에서 보면 좌/우가 겹침 → 한쪽만
                    continue
                cut = CommonHelper.cut_by_t(*part.t_range)
                pts = part.shape.profile_points()
                label = None
                if part.kind == EscalatorPartKind.TRUSS:
                    s_wp = esc.s_wp[0]
                    label = (f"{esc.name} ESCALATOR {esc.angle_deg:g}°", s_wp, esc.pos_z + 1.5, 0.6, "PROF_TEXT")
                items.append(ViewItem(part.name, "PROF_ESCALATOR" if cut else "PROF_BEYOND",
                                      u0=min(p[0] for p in pts), u1=max(p[0] for p in pts), pts=pts, label=label))
        return items

    def plan_items(self, cut_h):
        """평면도(최하층 절단): 최하층에서 오르는 에스컬레이터의 트러스 외곽, 스텝 폭, 난간, 이름(오르는 방향)"""
        items = []
        for esc in self.all_escalators():
            if esc.lower_floor != 1:
                continue
            s0, s1 = esc.s_range
            t0, t1 = esc.t_range
            arrow = "UP >" if esc.direction > 0 else "< UP"
            items.append(ViewItem.rect(esc.name, "PLAN_ESCALATOR", s0, s1, t0, t1,
                                       label=(f"{esc.name} ESC {arrow}", s0 + 0.3, t1 + 0.3, 0.5, "PLAN_TEXT")))
            for part in esc.parts:
                if part.kind in (EscalatorPartKind.STEPS, EscalatorPartKind.BALUSTRADE):
                    a, b = part.shape.strips[0].s0, part.shape.strips[-1].s1
                    items.append(ViewItem.rect(part.name, "PLAN_ESCALATOR", a, b, *part.t_range))
        return items
