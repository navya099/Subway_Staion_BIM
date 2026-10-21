from config.master_config import StationProjectConfig
from helper.geometry_helper import CommonHelper
from helper.view_item import ViewItem
from slabs.rectangular_slab import RectangularSlab
from slabs.slab_data import SlabData
from slabs.slab_package import SlabPackage
from slabs.slab_shape_type import SlabKind, SlabShapeType


class SlabEngine:
    """바닥·중간·천장 슬래브 BIM 객체를 만들고, 3D DXF / IFC의 단일 데이터 원천이 된다.

    - 바닥/천장 슬래브: 정거장 전체 평면(L x W)
    - 중간 슬래브: 외벽·마감벽 안쪽 면 사이만 차지 (벽체와 체적이 겹치지 않음)
    - 소속 층: 바닥 = 최하층, 중간 i = 그 위층(i+1), 천장 = 최상층
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
        sh = slab.shape
        return CommonHelper.prism_corners(slab.pos_x, slab.pos_y, slab.pos_z, sh.length, sh.width, sh.rise)

    def _slab_defs(self):
        """(용도, 소속 층 번호, 하단 높이(바닥 슬래브 상면 기준), 두께, s0, s1, t0, t1)"""
        p = self.sp
        hw, wt = p.width / 2.0, p.wall_t
        story_h = p.height / p.floors
        defs = [(SlabKind.FLOOR, 1, -p.floor_t, p.floor_t, 0.0, p.length, -hw, hw)]
        for i in range(1, p.floors):
            defs.append((SlabKind.MID, i + 1, i * story_h - p.slab_t / 2, p.slab_t,
                         wt, p.length - wt, -hw + wt, hw - wt))
        defs.append((SlabKind.ROOF, p.floors, p.height - p.slab_t, p.slab_t, 0.0, p.length, -hw, hw))
        return defs

    # ---------- 생성 ----------
    def _build_slab_bim_objects(self):
        p = self.sp
        if min(p.floor_t, p.slab_t) <= 0:
            raise ValueError("슬래브 두께는 0보다 커야 합니다.")
        if p.height / p.floors <= p.slab_t:
            raise ValueError("층 높이가 슬래브 두께보다 작거나 같습니다.")

        by_level: dict[str, SlabPackage] = {}
        for kind, floor_n, z_lo, thick, s0, s1, t0, t1 in self._slab_defs():
            level = self.level_name(floor_n)
            package = by_level.setdefault(level, SlabPackage(level=level, package_id=f"PKG_{level}_SLABS"))
            lv0, lv1 = self.cfg.lv(s0) - p.offset, self.cfg.lv(s1) - p.offset
            package.add_slab(SlabData(
                name=f"SLAB_{level}_{self._CODE[kind]}",
                family_name=self._FAMILY[kind],
                type_name=f"{int(round(thick * 1000))}mm",
                level=level,
                pos_x=(s0 + s1) / 2.0,
                pos_y=(t0 + t1) / 2.0,
                pos_z=(lv0 + lv1) / 2.0 + z_lo,
                rotation=0.0,
                material="Concrete_C24",
                kind=kind,
                shape_type=SlabShapeType.RECTANGLE,
                shape=RectangularSlab(length=s1 - s0, width=t1 - t0, thickness=thick, rise=lv1 - lv0),
            ))
        # 최하층(바닥) → 최상층(천장) 순서 유지
        self.slab_packages = sorted(by_level.values(), key=lambda k: -self._level_no(k.level))

    def _level_no(self, level: str) -> int:
        return next(n for n in range(1, self.sp.floors + 1) if self.level_name(n) == level)

    # ---------- 작도 ----------
    def add_slab_mesh(self, msp, world):
        """3D 절대 좌표계 메쉬. world = StationProjectConfig.to_world ((s, t) → WCS x, y). 한 번만 호출할 것"""
        for package in self.slab_packages:
            for slab in package.slabs:
                s0, s1, t0, t1, z0, z1 = self.slab_corners(slab)
                th = slab.shape.thickness
                faces = CommonHelper.create_sloped_box_faces_global(
                    s0, s1, t0, t1, z0, z1, z0 + th, z1 + th, world)
                slab.source_element = [msp.add_3dface(f, dxfattribs={"layer": "STRUCT_SLAB"}) for f in faces]

    # ---------- 2D 도면 (BIM 객체에서 직접 생성) ----------
    def section_items(self, sta):
        """횡단면도: 측점 sta 의 절단면에 걸리는 슬래브 (중간 슬래브는 층 이름 라벨 포함)"""
        items = []
        half_w = self.sp.width / 2.0
        for package in self.slab_packages:
            for sl in package.slabs:
                s0, s1, t0, t1, z0, z1 = self.slab_corners(sl)
                if CommonHelper.cut_by_s(sta, s0, s1, self.sp.length):
                    zb = z0 + (sta - s0) / (s1 - s0) * (z1 - z0)
                    th = sl.shape.thickness
                    label = (f"{package.level} SLAB", half_w + 1.0, zb + th / 2.0, 0.4, "SEC_TEXT") \
                        if sl.kind == SlabKind.MID else None
                    items.append(ViewItem.rect(sl.name, "SEC_CONCRETE", t0, t1, zb, zb + th,
                                               hatch_layer="SEC_HATCH", label=label))
        return items

    def profile_items(self):
        """종단면도(선형 중심 t=0 절단): 중심선을 자르는 슬래브"""
        items = []
        for package in self.slab_packages:
            for sl in package.slabs:
                s0, s1, t0, t1, z0, z1 = self.slab_corners(sl)
                if CommonHelper.cut_by_t(t0, t1):
                    items.append(ViewItem.sloped(sl.name, "PROF_CONCRETE", s0, s1, z0, z1, sl.shape.thickness,
                                                 hatch_layer="PROF_HATCH"))
        return items
