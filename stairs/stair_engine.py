from config.master_config import StationProjectConfig
from helper.strip_member import part_faces, section_spans
from helper.geometry_helper import CommonHelper
from helper.view_item import ViewItem
from slabs.slab_engine import SlabEngine
from stairs.stair_data import StairData, StairPartData
from stairs.stair_package import StairPackage
from stairs.stair_shape import StairPartShape
from stairs.stair_type import StairPartKind


def part_quads(cfg, part: StairPartData) -> list[list[tuple]]:
    """부재(런/계단참)의 띠마다 닫힌 면 집합 (helper.strip_member.part_faces)"""
    return part_faces(cfg, part)


class StairEngine:
    """직선 계단(런 + 중간 계단참) BIM 객체를 만들고, 3D DXF / 2D 도면 / IFC 의 단일 데이터 원천이 된다.

    - 배치(단수·단높이·런 분할·자동 오프닝)는 cfg.stair_layouts() 결과를 그대로 쓴다 (슬래브 엔진의 자동 오프닝과 같은 계산)
    - 계단은 시작 층의 BIM 객체 (IFC: IfcStair 가 IfcStairFlight / IfcSlab(LANDING) 을 묶음)
    - 형상: s 방향 띠(StairStrip)의 연속. 디딤판·계단참 상면은 수평, 허리 하면은 경사, 첫 런은 시작면(바닥/승강장)에서 잘림
    """

    def __init__(self, config: StationProjectConfig):
        self.cfg = config
        self.sp = config.station
        self.stair_packages: list[StairPackage] = []
        self._build_stair_bim_objects()

    # ---------- 생성 ----------
    def _build_stair_bim_objects(self):
        by_level: dict[str, StairPackage] = {}
        for lay in self.cfg.stair_layouts():
            spec = lay.spec
            level = self.sp.level_name(lay.lower_floor)
            package = by_level.setdefault(level, StairPackage(level=level, package_id=f"PKG_{level}_STAIRS"))
            t0, t1 = lay.t_range
            parts, count = [], {StairPartKind.FLIGHT: 0, StairPartKind.LANDING: 0}
            for p in lay.parts:
                count[p.kind] += 1
                flight = p.kind == StairPartKind.FLIGHT
                surfaces = sorted(tuple(sorted((lay.s_at(ua), lay.s_at(ub)))) + (zt,) for ua, ub, zt in p.surfaces)
                s_lo, s_hi = p.strips[0].s0, p.strips[-1].s1
                parts.append(StairPartData(
                    name=f"{lay.name}_{p.kind.value}{count[p.kind]}",
                    family_name="콘크리트-계단" if flight else "콘크리트-계단참",
                    type_name=f"{p.n_risers}단" if flight else f"{int(round(spec.waist_t * 1000))}mm",
                    level=level, pos_x=(s_lo + s_hi) / 2.0, pos_y=(t0 + t1) / 2.0,
                    pos_z=min(z for _, _, z in surfaces), material="Concrete_C24",
                    kind=p.kind, n_risers=p.n_risers, n_treads=len(surfaces) if flight else 0,
                    t_range=(t0, t1), surfaces=surfaces,
                    shape=StairPartShape(strips=p.strips, width=t1 - t0)))
            s0, s1 = lay.s_range
            package.add_stair(StairData(
                name=lay.name, family_name="콘크리트-직선계단",
                type_name=f"{lay.n_risers}단 R{lay.riser * 1000:.0f} T{spec.tread * 1000:.0f}",
                level=level, pos_x=(s0 + s1) / 2.0, pos_y=(t0 + t1) / 2.0,
                pos_z=self.cfg.lv(lay.s_at(0.0)) - self.sp.offset + lay.base_level,     # 첫 챌판 아래 시작면 표고
                material="Concrete_C24", lower_floor=lay.lower_floor, direction=spec.direction,
                on_platform=lay.on_platform, n_risers=lay.n_risers, riser=lay.riser, tread=spec.tread,
                s_range=lay.s_range, t_range=lay.t_range, opening_name=lay.opening.name, parts=parts))
        floor_no = {self.sp.level_name(n): n for n in range(1, self.sp.floors + 1)}
        self.stair_packages = sorted(by_level.values(), key=lambda pk: floor_no[pk.level])     # 최하층부터

    def all_stairs(self) -> list[StairData]:
        return [s for pk in self.stair_packages for s in pk.stairs]

    # ---------- 검사 ----------
    def check_columns(self, column_engine):
        """계단 평면이 시작 층 기둥과 겹치지 않는지 검사 (위층 기둥은 자동 오프닝의 기둥 검사에서 걸러짐)"""
        for stair in self.all_stairs():
            rect = (*stair.s_range, *stair.t_range)
            for pk in column_engine.column_packages:
                if pk.level != stair.level:
                    continue
                for col in pk.columns:
                    if SlabEngine._rect_hits_column(rect, col):
                        raise ValueError(f"계단 {stair.name}: {stair.level} 기둥 {col.name} 과(와) 겹칩니다 "
                                         "(계단 위치 또는 기둥 배치를 확인하세요)")

    # ---------- 작도 ----------
    def add_stair_mesh(self, msp):
        """3D 절대 좌표계 메쉬 (띠마다 닫힌 각기둥, 곡선이면 선형을 따라 휨). 한 번만 호출할 것"""
        for stair in self.all_stairs():
            for part in stair.parts:
                faces = [f for quads in part_quads(self.cfg, part) for f in quads]
                part.source_element = [msp.add_3dface(f, dxfattribs={"layer": "STRUCT_STAIR"}) for f in faces]

    # ---------- 2D 도면 (BIM 객체에서 직접 생성) ----------
    def section_items(self, sta):
        """횡단면도: 측점 sta 에 걸리는 계단 띠의 절단면 (계단마다 이름 라벨 1개)"""
        items = []
        for stair in self.all_stairs():
            labeled = False
            for part in stair.parts:
                for t0, t1, zb, zt in section_spans(part, sta):
                    label = None if labeled else (stair.name, t0 + 0.2, zt + 0.3, 0.4, "SEC_TEXT")
                    labeled = True
                    items.append(ViewItem.rect(part.name, "SEC_CONCRETE", t0, t1, zb, zt,
                                               hatch_layer="SEC_HATCH", label=label))
        return items

    def profile_items(self, t_cut=0.0):
        """종단면도(t = t_cut 절단): 절단면이 계단을 지나면 단면(해치), 아니면 측면에 보이는 윤곽"""
        items = []
        for stair in self.all_stairs():
            for i, part in enumerate(stair.parts):
                cut = CommonHelper.cut_by_t(*part.t_range, t_cut)
                pts = part.shape.profile_points()
                label = None
                if i == 0:
                    first = part.surfaces[0] if stair.direction > 0 else part.surfaces[-1]
                    label = (stair.name, first[0], first[2] + 0.6, 0.6, "PROF_TEXT")
                items.append(ViewItem(part.name, "PROF_CONCRETE" if cut else "PROF_BEYOND",
                                      u0=min(p[0] for p in pts), u1=max(p[0] for p in pts), pts=pts,
                                      hatch_layer="PROF_HATCH" if cut else None, label=label))
        return items

    def plan_items(self, cut_h, floor=1):
        """평면도(floor 층 절단): 그 층에서 오르는 계단의 디딤판·계단참 윤곽과 이름(오르는 방향 표시)"""
        items = []
        for stair in self.all_stairs():
            if stair.lower_floor != floor:
                continue
            t0, t1 = stair.t_range
            s0, s1 = stair.s_range
            for part in stair.parts:
                for sa, sb, _ in part.surfaces:
                    items.append(ViewItem.rect(part.name, "PLAN_STAIR", sa, sb, t0, t1))
            arrow = "UP >" if stair.direction > 0 else "< UP"
            items.append(ViewItem.rect(stair.name, "PLAN_STAIR", s0, s1, t0, t1,
                                       label=(f"{stair.name} {arrow}", s0 + 0.3, (t0 + t1) / 2.0, 0.5, "PLAN_TEXT")))
        return items
