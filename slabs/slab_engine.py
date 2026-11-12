from columns.circle_column import CircleColumn
from config.master_config import StationProjectConfig
from helper import prism_member as PM
from helper.view_item import ViewItem
from openings import decompose
from openings.opening_data import OpeningData
from openings.opening_spec import resolve_names
from slabs.rectangular_slab import RectangularSlab
from slabs.slab_data import SlabData
from slabs.slab_package import SlabPackage
from slabs.slab_piece import SlabPiece
from slabs.slab_shape_type import SlabKind, SlabShapeType


class SlabEngine:
    """바닥·중간·천장 슬래브 BIM 객체를 만들고, 3D DXF / IFC의 단일 데이터 원천이 된다.

    - 본체 바닥 슬래브는 최하층 외곽, 본체 천장 슬래브는 최상층 외곽과 같은 범위 (내공 + 양쪽 벽 두께)
    - 중간 슬래브: 내공 영역(L x W) 전체. 안쪽 면이 모든 층에서 같으므로 벽체와 체적이 겹치지 않음
    - 소속 층: 바닥 = 최하층, 중간 i = 그 위층(i+1), 천장 = 최상층
    - 오프닝(cfg.openings): 슬래브 번호 0 = 바닥, i = 중간 i, 층수 = 천장. 오프닝이 있는 슬래브는 직사각형 조각(SlabPiece)으로
      분해되어 3D / IFC 의 형상이 되고, 슬래브 1개는 그대로 1개의 BIM 객체로 남는다 (shape = 뚫기 전 전체 형상)
    """

    _FAMILY = {SlabKind.FLOOR: "콘크리트-바닥슬래브", SlabKind.MID: "콘크리트-중간슬래브", SlabKind.ROOF: "콘크리트-천장슬래브"}
    _CODE = {SlabKind.FLOOR: "FLOOR", SlabKind.MID: "MID", SlabKind.ROOF: "ROOF"}

    def __init__(self, config_params: StationProjectConfig):
        self.cfg = config_params
        self.sp = config_params.station
        self.slab_packages: list[SlabPackage] = []
        self._build_slab_bim_objects()

    # ---------- 공통 ----------
    def level_name(self, floor_n: int) -> str:
        """floor_n: 1 = 최하층"""
        p = self.sp
        return f"B{p.floors - floor_n + 1}F" if p.floors > 1 else f"{floor_n}F"

    def slab_corners(self, slab: SlabData) -> tuple[float, float, float, float, float, float]:
        """(s0, s1, t0, t1, z_bot(s0), z_bot(s1))"""
        return PM.corners(self.cfg, slab)

    def _slab_defs(self):
        """(용도, 소속 층 번호, 하단 높이(바닥 슬래브 상면 기준), 두께, s0, s1, t0, t1)"""
        p = self.sp
        hw, L = p.width / 2.0, p.length
        w1, wn = p.wall_t_at(1), p.wall_t_at(p.floors)
        defs = [(SlabKind.FLOOR, 1, -p.floor_t, p.floor_t, -w1, L + w1, -hw - w1, hw + w1)]          # 최하층 외곽
        for i in range(1, p.floors):              # 중간층 바닥 슬래브: 상면이 윗층 바닥 높이, 내공 영역 전체
            defs.append((SlabKind.MID, i + 1, p.floor_level(i + 1) - p.mid_t, p.mid_t, 0.0, L, -hw, hw))
        defs.append((SlabKind.ROOF, p.floors, p.height - p.roof_t, p.roof_t, -wn, L + wn, -hw - wn, hw + wn))   # 최상층 외곽
        return defs

    # ---------- 생성 ----------
    def _build_slab_bim_objects(self):
        p = self.sp
        if min(p.floor_t, p.mid_t, p.roof_t) <= 0:
            raise ValueError("슬래브 두께는 0보다 커야 합니다.")
        if any(p.clear_height(n) <= 0 for n in range(1, p.floors + 1)):
            raise ValueError("층 높이가 위쪽 슬래브 두께보다 작거나 같습니다.")

        names = resolve_names(self.cfg.openings)
        by_level: dict[str, SlabPackage] = {}
        for slab_no, (kind, floor_n, z_lo, thick, s0, s1, t0, t1) in enumerate(self._slab_defs()):
            level = self.level_name(floor_n)
            package = by_level.setdefault(level, SlabPackage(level=level, package_id=f"PKG_{level}_SLABS"))
            name = f"SLAB_{level}_{self._CODE[kind]}"
            type_name = f"{int(round(thick * 1000))}mm"
            pos_x, pos_y, pos_z, shape = self._member_dims(s0, s1, t0, t1, z_lo, thick)
            slab = SlabData(
                name=name, family_name=self._FAMILY[kind], type_name=type_name, level=level,
                pos_x=pos_x, pos_y=pos_y, pos_z=pos_z, rotation=0.0, material="Concrete_C24",
                kind=kind, shape_type=SlabShapeType.RECTANGLE, shape=shape, slab_no=slab_no)
            self._cut_openings(slab, names, (s0, s1, t0, t1), z_lo, thick)
            package.add_slab(slab)
        # 최하층(바닥) → 최상층(천장) 순서 유지
        self.slab_packages = sorted(by_level.values(), key=lambda k: -self._level_no(k.level))

    def _member_dims(self, s0, s1, t0, t1, z_lo, thick):
        """(s0~s1) x (t0~t1) 직사각 부재의 (pos_x, pos_y, pos_z, 형상). z_lo = 바닥 슬래브 상면 기준 하단 높이"""
        p = self.sp
        lv0, lv1 = self.cfg.lv(s0) - p.offset, self.cfg.lv(s1) - p.offset
        shape = RectangularSlab(length=s1 - s0, width=t1 - t0, thickness=thick, rise=lv1 - lv0,
                                curve_factor=PM.curve_factor(self.cfg, s0, s1, (t0 + t1) / 2.0))
        return ((s0 + s1) / 2.0, (t0 + t1) / 2.0, self.cfg.lv((s0 + s1) / 2.0) - p.offset + z_lo, shape)

    def _cut_openings(self, slab: SlabData, names: list, region: tuple, z_lo: float, thick: float):
        """이 슬래브를 뚫는 오프닝 BIM 객체를 만들고, 남은 부분을 직사각형 조각으로 분해"""
        specs = [(n, sp) for n, sp in zip(names, self.cfg.openings) if slab.slab_no in sp.slabs]
        if not specs:
            return
        holes = []
        for n, sp in specs:
            s0, s1, t0, t1 = sp.s_start, sp.s_end, sp.t_lo, sp.t_hi
            pos_x, pos_y, pos_z, shape = self._member_dims(s0, s1, t0, t1, z_lo, thick)
            slab.openings.append(OpeningData(
                name=f"OPEN_{n}_{slab.name}", family_name="슬래브 오프닝", type_name=sp.kind.label,
                level=slab.level, pos_x=pos_x, pos_y=pos_y, pos_z=pos_z, kind=sp.kind, slab_name=slab.name,
                shape=shape, s_range=(s0, s1), t_range=(t0, t1)))
            holes.append((s0, s1, t0, t1))
        for k, rect in enumerate(decompose.subtract_rects(region, holes), start=1):
            pos_x, pos_y, pos_z, shape = self._member_dims(*rect, z_lo, thick)
            slab.pieces.append(SlabPiece(name=f"{slab.name}_P{k}", pos_x=pos_x, pos_y=pos_y, pos_z=pos_z, shape=shape))

    @staticmethod
    def _rect_hits_column(rect, col, tol: float = 1e-6) -> bool:
        """직사각형 (s0, s1, t0, t1) 이 기둥 평면 단면과 겹치는가 (원기둥은 원, 사각기둥은 사각형으로 정확히 판정)"""
        s0, s1, t0, t1 = rect
        if isinstance(col.shape, CircleColumn):
            nx, ny = min(max(col.pos_x, s0), s1), min(max(col.pos_y, t0), t1)
            return ((col.pos_x - nx) ** 2 + (col.pos_y - ny) ** 2) ** 0.5 < col.shape.radius - tol
        hs, ht = col.shape.half_s, col.shape.half_t
        return min(s1, col.pos_x + hs) - max(s0, col.pos_x - hs) > tol and min(t1, col.pos_y + ht) - max(t0, col.pos_y - ht) > tol

    def check_columns(self, column_engine):
        """오프닝이 기둥을 관통하지 않는지 검사. 슬래브 번호 k 의 오프닝은 그 아래 k층과 위 k+1층 기둥과 만난다"""
        by_floor = {n: [c for pk in column_engine.column_packages if pk.level == self.level_name(n) for c in pk.columns]
                    for n in range(1, self.sp.floors + 1)}
        for package in self.slab_packages:
            for slab in package.slabs:
                for op in slab.openings:
                    rect = (*op.s_range, *op.t_range)
                    for floor_n in (slab.slab_no, slab.slab_no + 1):
                        for col in by_floor.get(floor_n, []):
                            if self._rect_hits_column(rect, col):
                                raise ValueError(f"{op.name}: 오프닝이 {self.level_name(floor_n)} 기둥 {col.name} 과(와) 겹칩니다 "
                                                 "(오프닝 위치 또는 기둥 배치를 확인하세요)")

    def _level_no(self, level: str) -> int:
        return next(n for n in range(1, self.sp.floors + 1) if self.level_name(n) == level)

    # ---------- 작도 ----------
    def add_slab_mesh(self, msp):
        """3D 절대 좌표계 메쉬 (직선: 각기둥, 곡선: 선형을 따르는 스윕). 한 번만 호출할 것"""
        for package in self.slab_packages:
            for slab in package.slabs:
                faces = [f for m in slab.members for f in PM.mesh_faces(self.cfg, m)]
                slab.source_element = [msp.add_3dface(f, dxfattribs={"layer": "STRUCT_SLAB"}) for f in faces]

    # ---------- 2D 도면 (BIM 객체에서 직접 생성) ----------
    def _holes_at_sta(self, slab: SlabData, sta: float):
        """측점 sta 의 횡단면이 자르는 오프닝의 t 구간"""
        tol = 1e-9
        return [op.t_range for op in slab.openings if op.s_range[0] - tol <= sta < op.s_range[1] - tol]

    def section_items(self, sta):
        """횡단면도: 측점 sta 의 절단면에 걸리는 슬래브 (오프닝이 잘리면 그 구간은 비움, 중간 슬래브는 층 이름 라벨 포함)"""
        items = []
        half_w = self.sp.width / 2.0 + self.sp.max_wall_t        # 라벨은 가장 바깥 벽 밖에
        for package in self.slab_packages:
            for sl in package.slabs:
                cut = PM.section_rect(self.cfg, sl, sta)
                if not cut:
                    continue
                t0, t1, zb = cut
                th = sl.shape.thickness
                spans = decompose.subtract_intervals(t0, t1, self._holes_at_sta(sl, sta))
                for k, (a, b) in enumerate(spans):
                    label = (f"{package.level} SLAB", half_w + 1.0, zb + th / 2.0, 0.4, "SEC_TEXT") \
                        if sl.kind == SlabKind.MID and k == 0 else None
                    items.append(ViewItem.rect(sl.name, "SEC_CONCRETE", a, b, zb, zb + th,
                                               hatch_layer="SEC_HATCH", label=label))
        return items

    def profile_items(self):
        """종단면도(선형 중심 t=0 절단): 중심선을 자르는 슬래브 (중심선이 오프닝을 지나면 그 s 구간은 비움)"""
        items = []
        for package in self.slab_packages:
            for sl in package.slabs:
                if not PM.cut_by_centerline(sl):
                    continue
                holes = [op.s_range for op in sl.openings if op.t_range[0] - 1e-9 <= 0.0 < op.t_range[1] - 1e-9]
                if not holes:
                    items.append(PM.profile_view(self.cfg, sl, "PROF_CONCRETE", hatch_layer="PROF_HATCH"))
                    continue
                s0, s1 = PM.s_range(sl)
                for a, b in decompose.subtract_intervals(s0, s1, holes):
                    mid = (a + b) / 2.0
                    part = SlabPiece(name=sl.name, pos_x=mid, pos_y=sl.pos_y,
                                     pos_z=self.cfg.lv(mid) - self.sp.offset + PM.z_off(self.cfg, sl),
                                     shape=RectangularSlab(length=b - a, width=sl.shape.width, thickness=sl.shape.thickness))
                    items.append(PM.profile_view(self.cfg, part, "PROF_CONCRETE", hatch_layer="PROF_HATCH"))
        return items
