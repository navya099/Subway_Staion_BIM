from config.master_config import StationProjectConfig
from helper.box_helper import CommonHelper
from helper.view_item import ViewItem
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

                inner = p.width / 2.0 - p.wall_t
                ht_max = max(sp.half_t for sp in row.pattern)
                hs_max = max(sp.half_s for sp in row.pattern)
                if abs(row.t_offset) + ht_max > inner + 1e-9:
                    raise ValueError(f"{level} {row_idx}열: 기둥이 벽체 안쪽 면을 벗어납니다 "
                                     f"(t 위치 {row.t_offset:.2f}m, 기둥 반폭 {ht_max:.2f}m, 안쪽 반폭 {inner:.2f}m)")
                if row.start_offset < hs_max - 1e-9:
                    raise ValueError(f"{level} {row_idx}열: 시작 여유({row.start_offset:.2f}m)가 기둥 반폭({hs_max:.2f}m)보다 작아 마감벽과 겹칩니다")
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
            self._check_overlaps(package)
            self.column_packages.append(package)

    # ---------- 검증 ----------
    @staticmethod
    def _overlap(a: ColumnData, b: ColumnData) -> bool:
        """같은 층 기둥 두 개의 평면 겹침 (원-원, 원-사각, 사각-사각을 정확히 판정)"""
        tol = 1e-6
        ca, cb = isinstance(a.shape, CircleColumn), isinstance(b.shape, CircleColumn)
        if ca and cb:
            return ((a.pos_x - b.pos_x) ** 2 + (a.pos_y - b.pos_y) ** 2) ** 0.5 < a.shape.radius + b.shape.radius - tol
        if ca or cb:
            c, r = (a, b) if ca else (b, a)
            nx = min(max(c.pos_x, r.pos_x - r.shape.half_s), r.pos_x + r.shape.half_s)
            ny = min(max(c.pos_y, r.pos_y - r.shape.half_t), r.pos_y + r.shape.half_t)
            return ((c.pos_x - nx) ** 2 + (c.pos_y - ny) ** 2) ** 0.5 < c.shape.radius - tol
        return (min(a.pos_x + a.shape.half_s, b.pos_x + b.shape.half_s) - max(a.pos_x - a.shape.half_s, b.pos_x - b.shape.half_s) > tol and
                min(a.pos_y + a.shape.half_t, b.pos_y + b.shape.half_t) - max(a.pos_y - a.shape.half_t, b.pos_y - b.shape.half_t) > tol)

    def _check_overlaps(self, package: ColumnPackage):
        cols = sorted(package.columns, key=lambda c: c.pos_x)
        reach = max((c.shape.half_s for c in cols), default=0.0) * 2
        for i, a in enumerate(cols):
            for b in cols[i + 1:]:
                if b.pos_x - a.pos_x > reach + 1e-9:
                    break
                if self._overlap(a, b):
                    raise ValueError(f"{package.level}: {a.name} 와 {b.name} 기둥이 서로 겹칩니다 (열 위치/간격/크기를 확인하세요)")

    # ---------- 작도 ----------
    def add_column_mesh(self, msp, bp_x, bp_y, theta):
        """3D 절대 좌표계 메쉬 (bp_x, bp_y = 정거장 시점의 WCS 좌표). 한 번만 호출할 것"""
        for package in self.column_packages:
            for col in package.columns:
                faces = CommonHelper.create_prism_faces_global(
                    self._footprint(col), col.pos_z, col.pos_z + col.shape.height, bp_x, bp_y, theta)
                col.source_element = [msp.add_3dface(f, dxfattribs={"layer": "STRUCT_COLUMN"}) for f in faces]

    # ---------- 2D 도면 (BIM 객체에서 직접 생성) ----------
    @staticmethod
    def _chord(col: ColumnData, offset: float) -> float:
        """기둥 중심에서 offset 만큼 떨어진 절단면에서의 반폭. 사각기둥은 offset 무관, 원기둥은 현(chord)"""
        if isinstance(col.shape, CircleColumn):
            r = col.shape.radius
            return (r * r - offset * offset) ** 0.5 if abs(offset) < r else 0.0
        return 0.0

    def section_items(self, sta):
        """횡단면도: 측점 sta 에서 절단되는 기둥(해치) + 앞쪽에 보이는 기둥(가장 가까운 것만, 윤곽선)"""
        cut, beyond, cut_keys = [], {}, set()
        for package in self.column_packages:
            for col in package.columns:
                z_bot, z_top = col.pos_z, col.pos_z + col.shape.height
                s_lo, s_hi = col.pos_x - col.shape.half_s, col.pos_x + col.shape.half_s
                ht = col.shape.half_t
                key = (col.level, round(col.pos_y, 4), round(ht, 4))
                if s_lo - 1e-9 <= sta < s_hi - 1e-9:
                    ht_cut = self._chord(col, sta - col.pos_x) if isinstance(col.shape, CircleColumn) else ht
                    if ht_cut > 0:
                        cut_keys.add(key)
                        cut.append(ViewItem.rect(col.name, "SEC_CONCRETE", col.pos_y - ht_cut, col.pos_y + ht_cut,
                                                 z_bot, z_top, hatch_layer="SEC_HATCH"))
                elif s_lo >= sta - 1e-9 and (key not in beyond or s_lo < beyond[key][0]):
                    beyond[key] = (s_lo, ViewItem.rect(col.name, "SEC_BEYOND", col.pos_y - ht, col.pos_y + ht, z_bot, z_top))
        return cut + [it for k, (_, it) in beyond.items() if k not in cut_keys]

    def profile_items(self):
        """종단면도(선형 중심 t=0 절단): 중심선을 지나는 기둥(해치) + 측면에 보이는 기둥(동일 형상은 한 번만)"""
        cut, beyond, cut_keys = [], {}, set()
        for package in self.column_packages:
            for col in package.columns:
                z_bot, z_top = col.pos_z, col.pos_z + col.shape.height
                hs, ht = col.shape.half_s, col.shape.half_t
                if isinstance(col.shape, CircleColumn):
                    hs_cut = self._chord(col, col.pos_y)       # t=0 평면이 원을 자르는 현의 반폭
                else:
                    hs_cut = hs
                if CommonHelper.cut_by_t(col.pos_y - ht, col.pos_y + ht) and hs_cut > 0:
                    key = tuple(round(v, 3) for v in (col.pos_x - hs_cut, col.pos_x + hs_cut, z_bot, z_top))
                    cut_keys.add(key)
                    cut.append(ViewItem.rect(col.name, "PROF_CONCRETE", col.pos_x - hs_cut, col.pos_x + hs_cut,
                                             z_bot, z_top, hatch_layer="PROF_HATCH"))
                else:
                    key = tuple(round(v, 3) for v in (col.pos_x - hs, col.pos_x + hs, z_bot, z_top))
                    beyond.setdefault(key, ViewItem.rect(col.name, "PROF_BEYOND", col.pos_x - hs, col.pos_x + hs, z_bot, z_top))
        return cut + [it for k, it in beyond.items() if k not in cut_keys]

    def plan_items(self, cut_h):
        """평면도: 바닥 슬래브 상면 + cut_h 높이에서 절단되는 기둥 단면 (원기둥은 원, 사각기둥은 사각형)"""
        items = []
        for package in self.column_packages:
            for col in package.columns:
                zc = self.cfg.lv(col.pos_x) - self.sp.offset + cut_h
                if not (col.pos_z - 1e-9 <= zc < col.pos_z + col.shape.height - 1e-9):
                    continue
                if isinstance(col.shape, CircleColumn):
                    items.append(ViewItem(col.name, "PLAN_OUTLINE", circle=(col.pos_x, col.pos_y, col.shape.radius)))
                else:
                    hs, ht = col.shape.half_s, col.shape.half_t
                    items.append(ViewItem.rect(col.name, "PLAN_OUTLINE", col.pos_x - hs, col.pos_x + hs,
                                               col.pos_y - ht, col.pos_y + ht))
        return items
