from config.master_config import StationProjectConfig
from helper.box_helper import CommonHelper
from columns.circle_column import CircleColumn
from columns.column_data import ColumnData
from columns.column_package import ColumnPackage
from columns.column_params import ColumnSpec
from columns.column_shape_type import ColumnShapeType
from columns.rectangular_column import RectangularColumn


class ColumnEngine:
    """층별·열별 기둥 BIM 객체를 만들고, DXF 3D/평면/단면/종단 작도의 단일 데이터 원천이 된다."""

    def __init__(self, config_params: StationProjectConfig):
        self.cfg = config_params
        self.sp = config_params.station
        self.pf = config_params.platform
        self.cp = config_params.column

        self.column_packages: list[ColumnPackage] = []
        self._build_column_bim_objects()

    # ---------- 공통 ----------
    def level_name(self, floor_n: int) -> str:
        """floor_n: 1 = 최하층"""
        p = self.sp
        return f"B{p.floors - floor_n + 1}F" if p.floors > 1 else f"{floor_n}F"

    def platform_overlap(self, t_lo: float, t_hi: float) -> str:
        """직교방향 구간 [t_lo, t_hi] 와 승강장(좌/우)의 관계: 'none' | 'over'(완전히 위) | 'straddle'(걸침)"""
        pf, p = self.pf, self.sp
        if pf.plat_thick <= 0:
            return "none"
        edge = pf.track_spacing / 2.0 + pf.plat_offset
        inner = p.width / 2.0 - p.wall_t
        eps = 1e-9
        result = "none"
        for lo, hi in ((-inner, -edge), (edge, inner)):
            if min(t_hi, hi) - max(t_lo, lo) > eps:
                result = "over" if (t_lo >= lo - eps and t_hi <= hi + eps) else "straddle"
        return result

    def z_range(self, floor_n: int, s: float, t_lo: float = 0.0, t_hi: float = 0.0) -> tuple[float, float]:
        """층 floor_n 기둥의 하단/상단 표고 (정거장 로컬 거리 s, 직교방향 구간 t_lo~t_hi 위치)"""
        p, pf, cp = self.sp, self.pf, self.cp
        story_h = p.height / p.floors
        floor_top_z = self.cfg.lv(s) - p.offset
        # 하단: 최하층 = 바닥 슬래브 상면(승강장 동기화 시 승강장 상면), 그 외 = 중간 슬래브 상면
        if floor_n == 1:
            on_platform = cp.sync_with_platform and self.platform_overlap(t_lo, t_hi) == "over"
            z_bot = floor_top_z + (pf.plat_height + pf.plat_thick if on_platform else 0.0)
        else:
            z_bot = floor_top_z + (floor_n - 1) * story_h + p.slab_t / 2
        # 상단: 최상층 = 천장 슬래브 하면, 그 외 = 중간 슬래브 하면
        if floor_n < p.floors:
            z_top = floor_top_z + floor_n * story_h - p.slab_t / 2
        else:
            z_top = floor_top_z + p.height - p.slab_t
        return z_bot, z_top

    @staticmethod
    def _footprint(col: ColumnData) -> list[tuple[float, float]]:
        s, t = col.pos_x, col.pos_y
        if isinstance(col.shape, CircleColumn):
            return CommonHelper.circle_polygon(s, t, col.shape.radius)
        hs, ht = col.shape.half_s, col.shape.half_t
        return [(s - hs, t - ht), (s + hs, t - ht), (s + hs, t + ht), (s - hs, t + ht)]

    def _make_shape(self, spec: ColumnSpec, height: float):
        if spec.shape_type == ColumnShapeType.CIRCLE:
            return CircleColumn(column_type=ColumnShapeType.CIRCLE, height=height, radius=spec.radius)
        return RectangularColumn(column_type=ColumnShapeType.RECTANGLE, height=height,
                                 width=spec.width, depth=spec.depth)

    @staticmethod
    def _type_name(spec: ColumnSpec) -> str:
        if spec.shape_type == ColumnShapeType.CIRCLE:
            return f"D{int(round(spec.radius * 2000))}mm"
        return f"{int(round(spec.width * 1000))}x{int(round(spec.depth * 1000))}mm"

    # ---------- 생성 ----------
    def _build_column_bim_objects(self):
        p, cp = self.sp, self.cp

        for floor_n in cp.target_floors:
            if not 1 <= floor_n <= p.floors:
                raise ValueError(f"기둥 설정의 층 번호 {floor_n} 이(가) 층수 {p.floors} 범위를 벗어났습니다.")
            level = self.level_name(floor_n)
            package = ColumnPackage(level=level, package_id=f"PKG_{level}_COLUMNS")

            for row_idx, row in enumerate(cp.floors[floor_n].rows, start=1):
                if row.interval <= 0:
                    raise ValueError(f"{level} {row_idx}열: 배치 간격은 0보다 커야 합니다.")
                if not row.pattern:
                    raise ValueError(f"{level} {row_idx}열: 기둥 규격(pattern)이 비어 있습니다.")

                s_first = p.wall_t + row.start_offset
                s_last = p.length - p.wall_t - row.start_offset
                n = int((s_last - s_first) / row.interval + 1e-9) + 1 if s_last >= s_first else 0

                for i in range(n):
                    spec = row.pattern[i % len(row.pattern)]
                    s = s_first + i * row.interval
                    t_lo, t_hi = row.t_offset - spec.half_t, row.t_offset + spec.half_t
                    if floor_n == 1 and self.platform_overlap(t_lo, t_hi) == "straddle":
                        raise ValueError(f"{level} {row_idx}열 기둥이 승강장 끝단에 걸쳐 있습니다 (t={row.t_offset:.2f}m).")
                    z_bot, z_top = self.z_range(floor_n, s, t_lo, t_hi)
                    if z_top - z_bot <= 0:
                        raise ValueError(f"{level} 기둥 높이가 0 이하입니다 (s={s:.1f}m). 승강장 높이/슬래브 두께를 확인하세요.")

                    package.add_column(ColumnData(
                        name=f"COL_{level}_R{row_idx}_{i + 1:02d}",
                        family_name="콘크리트-원형 기둥" if spec.shape_type == ColumnShapeType.CIRCLE else "콘크리트-직사각형 기둥",
                        type_name=self._type_name(spec),
                        level=level,
                        pos_x=s,
                        pos_y=row.t_offset,
                        pos_z=z_bot,
                        rotation=0.0,
                        material="Concrete_C24",
                        shape_type=spec.shape_type,
                        shape=self._make_shape(spec, z_top - z_bot),
                    ))
            self.column_packages.append(package)

    # ---------- 작도 ----------
    def add_column_mesh(self, msp, bp_x, bp_y, theta):
        """3D 절대 좌표계 메쉬 (bp_x, bp_y = 정거장 시점의 WCS 좌표). 한 번만 호출할 것"""
        for package in self.column_packages:
            for col in package.columns:
                faces = CommonHelper.create_prism_faces_global(
                    self._footprint(col), col.pos_z, col.pos_z + col.shape.height, bp_x, bp_y, theta)
                col.source_element = [msp.add_3dface(f, dxfattribs={"layer": "STRUCT_COLUMN"}) for f in faces]

    def add_column_plan(self, msp):
        """평면도: 최하층(없으면 첫 번째 설정 층) 기둥 단면 (절단 레벨 FL+2.0m 기준 대표층)"""
        if not self.column_packages:
            return
        package = next((k for k in self.column_packages if k.level == self.level_name(1)), self.column_packages[0])
        for col in package.columns:
            if isinstance(col.shape, CircleColumn):
                msp.add_circle((col.pos_x, col.pos_y), col.shape.radius, dxfattribs={'layer': 'PLAN_OUTLINE'})
            else:
                msp.add_lwpolyline(self._footprint(col), close=True, dxfattribs={'layer': 'PLAN_OUTLINE'})

    def add_column_section(self, sta, x_offset, msp):
        """횡단면도: 측점 sta에서 층·열별 기둥 (한 열에 혼합 규격이 있으면 가장 두꺼운 폭으로 표시)"""
        for floor_n in self.cp.target_floors:
            for row in self.cp.floors[floor_n].rows:
                ht = max(spec.half_t for spec in row.pattern)
                z_bot, z_top = self.z_range(floor_n, sta, row.t_offset - ht, row.t_offset + ht)
                cx = x_offset + row.t_offset
                msp.add_lwpolyline([(cx - ht, z_bot), (cx + ht, z_bot), (cx + ht, z_top), (cx - ht, z_top)],
                                   close=True, dxfattribs={'layer': 'SEC_CONCRETE'})

    def add_column_profile(self, msp, x_pts):
        """종단면도: 모든 기둥의 측면 윤곽"""
        for package in self.column_packages:
            for col in package.columns:
                hs = col.shape.half_s
                z1, z2 = col.pos_z, col.pos_z + col.shape.height
                msp.add_lwpolyline([(col.pos_x - hs, z1), (col.pos_x + hs, z1), (col.pos_x + hs, z2), (col.pos_x - hs, z2)],
                                   close=True, dxfattribs={'layer': 'PROF_CONCRETE'})
