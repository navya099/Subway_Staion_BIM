from config.master_config import StationProjectConfig
import math

from escalators.escalator_data import EscalatorBollardData, EscalatorData, EscalatorPartData, EscalatorStepData
from helper import prism_member as PM
from helper.strip_member import Strip
from escalators.escalator_package import EscalatorPackage
from escalators.escalator_type import EscalatorPartKind
from helper.geometry_helper import CommonHelper
from helper.strip_member import StripShape, part_faces, section_spans
from helper.view_item import ViewItem
from slabs.slab_engine import SlabEngine

_FAMILY = {EscalatorPartKind.TRUSS: "에스컬레이터-트러스", EscalatorPartKind.STEPS: "에스컬레이터-스텝",
           EscalatorPartKind.BALUSTRADE: "에스컬레이터-난간패널", EscalatorPartKind.HANDRAIL: "에스컬레이터-핸드레일",
           EscalatorPartKind.SKIRT: "에스컬레이터-스커트", EscalatorPartKind.INNER_DECK: "에스컬레이터-안쪽데크",
           EscalatorPartKind.OUTER_DECK: "에스컬레이터-바깥데크", EscalatorPartKind.FLOOR_PLATE: "에스컬레이터-승강구바닥판",
           EscalatorPartKind.COMB: "에스컬레이터-콤플레이트", EscalatorPartKind.OUTER_PLATE: "에스컬레이터-바깥덮개판",
           EscalatorPartKind.NEWEL_BASE: "에스컬레이터-뉴얼받침", EscalatorPartKind.CLAD_SIDE: "에스컬레이터-옆외장",
           EscalatorPartKind.CLAD_BOTTOM: "에스컬레이터-아래외장", EscalatorPartKind.NEWEL_END_IN: "에스컬레이터-데크끝",
           EscalatorPartKind.NEWEL_END_OUT: "에스컬레이터-데크끝"}
_MATERIAL = {EscalatorPartKind.TRUSS: "Steel_Truss", EscalatorPartKind.STEPS: "Aluminium_Step",
             EscalatorPartKind.BALUSTRADE: "Glass_Balustrade", EscalatorPartKind.HANDRAIL: "Rubber_Handrail",
             EscalatorPartKind.SKIRT: "Stainless_Skirt", EscalatorPartKind.INNER_DECK: "Stainless_Deck",
             EscalatorPartKind.OUTER_DECK: "Stainless_Deck", EscalatorPartKind.FLOOR_PLATE: "Aluminium_FloorPlate",
             EscalatorPartKind.COMB: "Aluminium_Comb", EscalatorPartKind.OUTER_PLATE: "Aluminium_FloorPlate",
             EscalatorPartKind.NEWEL_BASE: "Steel_NewelBase", EscalatorPartKind.CLAD_SIDE: "Stainless_Cladding",
             EscalatorPartKind.CLAD_BOTTOM: "Stainless_Cladding", EscalatorPartKind.NEWEL_END_IN: "Stainless_Deck",
             EscalatorPartKind.NEWEL_END_OUT: "Stainless_Deck"}
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
        self._layouts: dict = {}                         # 이름 → EscalatorLayout (스텝 텍스처 틀)
        self._build()

    def _build(self):
        by_level: dict[str, EscalatorPackage] = {}
        for lay in self.cfg.escalator_layouts():
            self._layouts[lay.name] = lay
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
            st0, st1 = spec.t_center - spec.step_width / 2.0, spec.t_center + spec.step_width / 2.0
            steps = []
            for stp in lay.steps:                          # 개별 스텝 (위 운행로)
                strips = []
                for ua, ub, zb, zt in stp.pieces:
                    sa, sb = sorted((lay.s_at(ua), lay.s_at(ub)))
                    strips.append(Strip(sa, sb, zb, zb, zt, curve_factor=PM.curve_factor(self.cfg, sa, sb, spec.t_center)))
                strips.sort(key=lambda x: x.s0)
                steps.append(EscalatorStepData(
                    name=f"{lay.name}_STEP{stp.index + 1:03d}", family_name="에스컬레이터-스텝",
                    type_name=f"S{int(round(spec.step_width * 1000))} 스텝", level=level,
                    pos_x=lay.s_at(stp.u), pos_y=spec.t_center, pos_z=min(x.zb0 for x in strips),
                    material=_MATERIAL[EscalatorPartKind.STEPS], index=stp.index, chain_u=stp.u, t_range=(st0, st1),
                    shape=StripShape(strips=strips, width=st1 - st0)))
            bollards = [self._bollard(lay, b) for b in lay.bollards]
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
                t_range=lay.t_range, opening_names=names, parts=parts, steps=steps, bollards=bollards))
        floor_no = {self.sp.level_name(n): n for n in range(1, self.sp.floors + 1)}
        self.escalator_packages = sorted(by_level.values(), key=lambda pk: floor_no[pk.level])

    BOLLARD_SIDES = 16                                   # 볼라드 단면 다각형 변 수

    def _bollard(self, lay, b) -> EscalatorBollardData:
        """볼라드 = 16각 기둥 (꼭짓점이 반지름 위, ±s 끝이 꼭짓점) → s 방향 사다리꼴 조각 8개 (양끝은 폭 0 인 삼각)"""
        from finishes.finish_engine import room_piece
        spec, r = lay.spec, lay.spec.bollard_d / 2.0
        name = f"{lay.name}_BOLLARD_{b.end}{b.index}"
        half = self.BOLLARD_SIDES // 2
        vs = sorted((r * math.cos(math.pi * j / half), r * math.sin(math.pi * j / half)) for j in range(half + 1))
        pieces = []
        for k, ((da, ha), (db, hb)) in enumerate(zip(vs, vs[1:]), start=1):
            trap = (b.t - ha, b.t + ha, b.t - hb, b.t + hb)
            pieces.append(room_piece(self.cfg, f"{name}_{k}", b.s + da, b.s + db, b.t - max(ha, hb), b.t + max(ha, hb),
                                     b.z0, b.z0 + spec.bollard_h, trap=trap))
        return EscalatorBollardData(name=name, family_name="볼라드", type_name=f"D{int(round(spec.bollard_d * 1000))} 볼라드",
                                    level=self.cfg.station.level_name(b.floor), material="Stainless_Bollard", end=b.end,
                                    floor=b.floor, center=(b.s, b.t), radius=r, pieces=pieces)

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
            for part in list(esc.parts) + list(esc.steps):
                faces = [f for quads in part_faces(self.cfg, part) for f in quads]
                glass = getattr(part, "kind", None) == EscalatorPartKind.BALUSTRADE and part.material == "Glass_Balustrade" \
                    and esc.steps                               # 상세 형상의 유리 난간은 반투명 레이어
                layer = "STRUCT_ESC_GLASS" if glass else "STRUCT_ESCALATOR"
                part.source_element = [msp.add_3dface(f, dxfattribs={"layer": layer}) for f in faces]
            self._step_frames(esc, msp)
            for b in esc.bollards:
                b.source_element = [msp.add_3dface(f, dxfattribs={"layer": "STRUCT_ESCALATOR"}) for p in b.pieces
                                    for f in PM.mesh_faces(self.cfg, p)]

    def _step_frames(self, esc, msp):
        """스텝마다 디딤판 윗면에 텍스처 이미지 한 장: (원점 = 앞 코·오른쪽(−t) 끝, u = +t, v = 앞 코 → 안쪽, 스텝 폭, 스텝 깊이)
        — 이미지 아래쪽 = 앞 코 (계단석과 같은 틀, DAE·웹 뷰어 apply_tread_uv). 앞 코 위치의 접선 기준 (곡선은 근사)"""
        cfg = self.cfg
        lay = self._layouts.get(esc.name)
        if lay is None:
            return

        def unit(a, b):
            v = (b[0] - a[0], b[1] - a[1], 0.0)
            n = math.hypot(v[0], v[1]) or 1.0
            return (v[0] / n, v[1] / n, 0.0)
        dep = lay.spec.step_depth
        for stp in esc.steps:
            t0, t1 = stp.t_range
            nose = lay.s_at(stp.chain_u)
            o = cfg.to_world(nose, t0)
            fr = ((o[0], o[1], 0.0), unit(o, cfg.to_world(nose, t0 + 1.0)),
                  unit(o, cfg.to_world(nose + lay.spec.direction * 0.5, t0)), t1 - t0, dep)
            n_faces = [len(q) for q in part_faces(cfg, stp)]
            tread = max(range(len(stp.shape.strips)), key=lambda i: stp.shape.strips[i].s1 - stp.shape.strips[i].s0)
            a = sum(n_faces[:tread])
            stp.face_frames = {e.dxf.handle: fr for e in stp.source_element[a:a + n_faces[tread]]}

    # ---------- 2D 도면 ----------
    def section_items(self, sta):
        """횡단면도: 측점 sta 에 걸리는 부재 절단면 (설비라 해치 없음, 에스컬레이터마다 이름 라벨 1개)"""
        items = []
        for esc in self.all_escalators():
            labeled = False
            for part in list(esc.parts) + list(esc.steps):
                for t0, t1, zb, zt in section_spans(part, sta):
                    label = None
                    if not labeled and getattr(part, "kind", None) == EscalatorPartKind.TRUSS:
                        label = (esc.name, t0 + 0.1, zt + 1.3, 0.4, "SEC_TEXT")
                        labeled = True
                    items.append(ViewItem.rect(part.name, "SEC_ESCALATOR", t0, t1, zb, zt, label=label))
            for b in esc.bollards:
                for p in b.pieces:
                    cut = PM.section_rect(self.cfg, p, sta)
                    if cut:
                        items.append(ViewItem.rect(b.name, "SEC_ESCALATOR", cut[0], cut[1], cut[2], cut[2] + p.shape.height))
        return items

    def profile_items(self, t_cut=0.0):
        """종단면도(t = t_cut 절단): 트러스·스텝·한쪽 난간/핸드레일 윤곽 (절단면이 지나면 절단, 아니면 측면에 보이는 윤곽)"""
        items = []
        for esc in self.all_escalators():
            for part in esc.parts:
                cut = CommonHelper.cut_by_t(*part.t_range, t_cut)
                if part.side < 0 and not cut:                    # 측면에서 보면 좌/우가 겹침 → 보이는 것은 한쪽만
                    continue
                ss = part.shape.strips
                gapped = any(abs(b.s0 - a.s1) > 1e-9 for a, b in zip(ss, ss[1:]))
                if (part.kind == EscalatorPartKind.HANDRAIL and esc.steps) or gapped:   # 겹치거나 떨어진 띠 → 띠마다
                    for x in part.shape.strips:
                        q = [(x.s0, x.zb0), (x.s1, x.zb1), (x.s1, x.zt_end), (x.s0, x.zt)]
                        items.append(ViewItem(part.name, "PROF_ESCALATOR" if cut else "PROF_BEYOND", u0=x.s0, u1=x.s1, pts=q))
                    continue
                pts = part.shape.profile_points()
                label = None
                if part.kind == EscalatorPartKind.TRUSS:
                    s_wp = esc.s_wp[0]
                    label = (f"{esc.name} ESCALATOR {esc.angle_deg:g}°", s_wp, esc.pos_z + 1.5, 0.6, "PROF_TEXT")
                items.append(ViewItem(part.name, "PROF_ESCALATOR" if cut else "PROF_BEYOND",
                                      u0=min(p[0] for p in pts), u1=max(p[0] for p in pts), pts=pts, label=label))
            for stp in esc.steps:                                # 스텝마다 디딤판·챌판 윤곽
                cut = CommonHelper.cut_by_t(*stp.t_range, t_cut)
                for x in stp.shape.strips:
                    pts = [(x.s0, x.zb0), (x.s1, x.zb1), (x.s1, x.zt_end), (x.s0, x.zt)]
                    items.append(ViewItem(stp.name, "PROF_ESCALATOR" if cut else "PROF_BEYOND", u0=x.s0, u1=x.s1, pts=pts))
        return items

    def plan_items(self, cut_h, floor=1):
        """평면도(floor 층 절단): 그 층에서 오르는 에스컬레이터의 트러스 외곽, 스텝 폭, 난간, 이름(오르는 방향)"""
        items = []
        for esc in self.all_escalators():
            if esc.lower_floor != floor:
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
            if esc.steps:                                        # 스텝 범위 (개별 스텝)
                a = min(x.s0 for st in esc.steps for x in st.shape.strips)
                b = max(x.s1 for st in esc.steps for x in st.shape.strips)
                items.append(ViewItem.rect(f"{esc.name}_STEPS", "PLAN_ESCALATOR", a, b, *esc.steps[0].t_range))
        for esc in self.all_escalators():                       # 볼라드 (서는 층, 절단 높이 무관)
            for b in esc.bollards:
                if b.floor == floor:
                    items.append(ViewItem(b.name, "PLAN_ESCALATOR", circle=(*b.center, b.radius)))
        return items
