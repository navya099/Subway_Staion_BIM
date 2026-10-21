from config.master_config import StationProjectConfig
from helper.box_helper import CommonHelper
from platforms.platform_data import PlatformData
from platforms.platform_package import PlatformPackage
from platforms.platform_type import PlatformPart, PlatformSide
from platforms.rectangular_platform import RectangularPlatform


class PlatformEngine:
    """상대식 승강장(좌/우) BIM 객체를 만들고, 3D DXF / IFC의 단일 데이터 원천이 된다.

    - 승강장은 최하층에 놓이며, 마감벽 안쪽 면 사이(wall_t ~ L-wall_t)만 차지해 벽체와 겹치지 않음
    - 승강장 슬래브: 바닥 슬래브 상면 + plat_height 에서 plat_thick 두께 (기존 모델 정의 유지)
    - 2D 도면(횡단/종단/평면)은 현재 파라미터에서 직접 계산 (추후 객체 기반으로 전환 예정)
    """

    def __init__(self, config: StationProjectConfig):
        self.p = config.platform
        self.sp = config.station
        self.lv = config.lv  # 정거장 로컬 거리 s → 선형 표고
        self.platform_packages: list[PlatformPackage] = []
        self._build_platform_bim_objects()

    # ---------- 공통 ----------
    def level_name(self, floor_n: int) -> str:
        """floor_n: 1 = 최하층"""
        return f"B{self.sp.floors - floor_n + 1}F" if self.sp.floors > 1 else f"{floor_n}F"

    def platform_corners(self, plat: PlatformData) -> tuple[float, float, float, float, float, float]:
        """(s0, s1, t0, t1, z_bot(s0), z_bot(s1))"""
        sh = plat.shape
        return CommonHelper.prism_corners(plat.pos_x, plat.pos_y, plat.pos_z, sh.length, sh.width, sh.rise)

    # ---------- 생성 ----------
    def _build_platform_bim_objects(self):
        p, sp = self.p, self.sp
        if p.plat_type not in ("", "0"):
            raise NotImplementedError("섬식 승강장은 아직 지원하지 않습니다 (상대식만 지원).")
        if p.plat_thick <= 0:
            return  # 승강장 미설정 → 객체 없음

        hw, wt = sp.width / 2.0, sp.wall_t
        s0, s1 = wt, sp.length - wt
        edge = p.track_spacing / 2.0 + p.plat_offset     # 선로 중심 ~ 승강장 끝단 (t 절대값)
        inner = hw - wt                                  # 벽체 안쪽 면 (t 절대값)
        width = inner - edge
        if width <= 0:
            raise ValueError(f"승강장 폭이 0 이하입니다: 선로간격/승강장 끝단({edge:.2f}m)이 벽체 안쪽 면({inner:.2f}m)을 넘습니다.")
        if p.support_t < 0 or (p.support_t > 0 and 2 * p.support_t >= width):
            raise ValueError(f"지지벽체 두께({p.support_t}m)가 승강장 폭({width:.2f}m)에 비해 너무 큽니다.")
        if p.support_t > 0 and p.plat_height <= 0:
            raise ValueError("지지벽체가 있으려면 승강장 높이(plat_height)가 0보다 커야 합니다.")

        level = self.level_name(1)
        package = PlatformPackage(level=level, package_id=f"PKG_{level}_PLATFORMS")
        lv0, lv1 = self.lv(s0) - sp.offset, self.lv(s1) - sp.offset
        rise, mid_lv = lv1 - lv0, (lv0 + lv1) / 2.0

        def add(name, part, side, family, type_t, t0, t1, z_lo, vert):
            package.add_platform(PlatformData(
                name=name, family_name=family, type_name=f"{int(round(type_t * 1000))}mm", level=level,
                pos_x=(s0 + s1) / 2.0, pos_y=(t0 + t1) / 2.0, pos_z=mid_lv + z_lo, rotation=0.0,
                material="Concrete_C24", part=part, side=side,
                shape=RectangularPlatform(length=s1 - s0, width=t1 - t0, thickness=vert, rise=rise)))

        st = p.support_t
        # 각 측: (측 코드, 측, 슬래브 t 범위, 선로측 다리 t 범위, 벽체측 다리 t 범위)
        sides = [
            ("L", PlatformSide.LEFT, (-inner, -edge), (-edge - st, -edge), (-inner, -inner + st)),
            ("R", PlatformSide.RIGHT, (edge, inner), (edge, edge + st), (inner - st, inner)),
        ]
        for code, side, slab_t, track_leg, out_leg in sides:
            add(f"PLAT_{level}_{code}", PlatformPart.SLAB, side, "콘크리트-승강장슬래브",
                p.plat_thick, *slab_t, p.plat_height, p.plat_thick)
            if st > 0:   # ㅠ형: 슬래브 하부 양 끝에 바닥 슬래브 상면에서 슬래브 하면까지 지지벽체
                add(f"PLATW_{level}_{code}_TRACK", PlatformPart.SUPPORT_WALL, side, "콘크리트-승강장지지벽체",
                    st, *track_leg, 0.0, p.plat_height)
                add(f"PLATW_{level}_{code}_OUT", PlatformPart.SUPPORT_WALL, side, "콘크리트-승강장지지벽체",
                    st, *out_leg, 0.0, p.plat_height)
        self.platform_packages.append(package)

    # ---------- 작도 ----------
    def add_platform_mesh(self, msp, bp_x, bp_y, theta):
        """3D 절대 좌표계 메쉬 (bp_x, bp_y = 정거장 시점의 WCS 좌표). 한 번만 호출할 것"""
        for package in self.platform_packages:
            for plat in package.platforms:
                s0, s1, t0, t1, z0, z1 = self.platform_corners(plat)
                th = plat.shape.thickness
                faces = CommonHelper.create_sloped_box_faces_global(
                    s0, s1, t0, t1, z0, z1, z0 + th, z1 + th, bp_x, bp_y, theta)
                plat.source_element = [msp.add_3dface(f, dxfattribs={"layer": "STRUCT_PLATFORM"}) for f in faces]

    def add_platform_section(self, floor_top_z, x_offset, half_w, msp):
        # --- [승강장 2D 단면 및 해치 작도] ---
        plat_z = floor_top_z + self.p.plat_height

        # 좌측 승강장 2D 폴리곤
        left_plat_poly = [
            (x_offset - half_w + self.sp.wall_t, plat_z),
            (x_offset - (self.p.track_spacing / 2) - self.p.plat_offset, plat_z),
            (x_offset - (self.p.track_spacing / 2) - self.p.plat_offset, plat_z + self.p.plat_thick),
            (x_offset - half_w + self.sp.wall_t, plat_z + self.p.plat_thick)
        ]
        msp.add_lwpolyline(left_plat_poly, close=True, dxfattribs={'layer': 'SEC_PLATFORM'})
        msp.add_text("SIDE PLATFORM (L)", dxfattribs={'height': 0.4, 'layer': 'SEC_TEXT'}).set_placement(
            (x_offset - half_w + 1.0, plat_z + 0.3))

        # 우측 승강장 2D 폴리곤
        right_plat_poly = [
            (x_offset + (self.p.track_spacing / 2) + self.p.plat_offset, plat_z),
            (x_offset + half_w - self.sp.wall_t, plat_z),
            (x_offset + half_w - self.sp.wall_t, plat_z + self.p.plat_thick),
            (x_offset + (self.p.track_spacing / 2) + self.p.plat_offset, plat_z + self.p.plat_thick)
        ]
        msp.add_lwpolyline(right_plat_poly, close=True, dxfattribs={'layer': 'SEC_PLATFORM'})
        msp.add_text("SIDE PLATFORM (R)", dxfattribs={'height': 0.4, 'layer': 'SEC_TEXT'}).set_placement(
            (x_offset + (self.p.track_spacing / 2) + self.p.plat_offset + 0.5, plat_z + 0.3))

        # 지지벽체 (ㅠ형 다리): 바닥 슬래브 상면 ~ 승강장 슬래브 하면
        st = self.p.support_t
        if st > 0:
            edge = self.p.track_spacing / 2 + self.p.plat_offset
            inner = half_w - self.sp.wall_t
            for t0, t1 in [(-edge - st, -edge), (-inner, -inner + st), (edge, edge + st), (inner - st, inner)]:
                msp.add_lwpolyline(
                    [(x_offset + t0, floor_top_z), (x_offset + t1, floor_top_z),
                     (x_offset + t1, plat_z), (x_offset + t0, plat_z)],
                    close=True, dxfattribs={'layer': 'SEC_PLATFORM'})

    def add_platform_profile(self, msp, x_pts):
        """
        2D 종단면도 상에 종단구배를 반영한 승강장 띠(Polygon) 작도
        x_pts: 종단 세그먼트 측점 목록 [0.0, 5.0, 10.0, ..., L]
        """
        # 시점/종점 마감 벽체 두께 안쪽으로 승강장 범위 지정
        s_start = self.sp.wall_t
        s_end = self.sp.length - self.sp.wall_t

        # 승강장에 해당하는 x 포인트 필터링 및 보정
        plat_x_pts = [x for x in x_pts if s_start <= x <= s_end]
        if not plat_x_pts or plat_x_pts[0] > s_start:
            plat_x_pts.insert(0, s_start)
        if plat_x_pts[-1] < s_end:
            plat_x_pts.append(s_end)

        # 1. 승강장 상단선 좌표 연산 (s -> Z_plat_top)
        top_pts = []
        for x in plat_x_pts:
            lv = self.lv(x)
            f_top = lv - self.sp.offset
            z_top = f_top + self.p.plat_height + self.p.plat_thick
            top_pts.append((x, z_top))

        # 2. 승강장 하단선 좌표 연산 (역순으로 감싸기)
        bot_pts = []
        for x in reversed(plat_x_pts):
            lv = self.lv(x)
            f_top = lv - self.sp.offset
            z_bot = f_top + self.p.plat_height
            bot_pts.append((x, z_bot))

        # 닫힌 승강장 종단 폴리곤 생성
        plat_poly = top_pts + bot_pts

        # 3. DXF 작도 및 해치/주석 기입
        msp.add_lwpolyline(plat_poly, close=True, dxfattribs={'layer': 'SEC_PLATFORM'})

        # 해치 기입 (옵션)
        hatch = msp.add_hatch(color=2, dxfattribs={'layer': 'PROF_HATCH'})
        hatch.set_pattern_fill('ANSI31', scale=0.3)
        path = hatch.paths.add_polyline_path(plat_poly)
        path.closed = True

        # 라벨 기입 (승강장 중앙 부근)
        mid_x = (s_start + s_end) / 2.0
        mid_lv = self.lv(mid_x)
        mid_z = (mid_lv - self.sp.offset) + self.p.plat_height + self.p.plat_thick + 0.5
        msp.add_text("PLATFORM SLAB (FL+1.1m)", dxfattribs={'height': 0.6, 'layer': 'PROF_TEXT'}).set_placement(
            (mid_x - 10.0, mid_z))

    def add_platform_plan(self, msp):
        """
        2D 평면도 상에 상대식 승강장 평면 윤곽선 작도
        """
        half_w = self.sp.width / 2.0
        s_start = self.sp.wall_t
        s_end = self.sp.length - self.sp.wall_t

        # 1. 좌측 승강장 평면 영역 (하선측)
        left_t1 = -self.p.track_spacing / 2 - self.p.plat_offset
        left_t2 = -half_w + self.sp.wall_t
        left_poly = [
            (s_start, min(left_t1, left_t2)),
            (s_end, min(left_t1, left_t2)),
            (s_end, max(left_t1, left_t2)),
            (s_start, max(left_t1, left_t2))
        ]
        msp.add_lwpolyline(left_poly, close=True, dxfattribs={'layer': 'PLAN_OUTLINE'})
        msp.add_text("SIDE PLATFORM (L)", dxfattribs={'height': 0.5, 'layer': 'PLAN_TEXT'}).set_placement(
            (s_start + 5.0, (min(left_t1, left_t2) + max(left_t1, left_t2)) / 2))

        # 2. 우측 승강장 평면 영역 (상선측)
        right_t1 = half_w - self.sp.wall_t
        right_t2 = self.p.track_spacing / 2 + self.p.plat_offset
        right_poly = [
            (s_start, min(right_t1, right_t2)),
            (s_end, min(right_t1, right_t2)),
            (s_end, max(right_t1, right_t2)),
            (s_start, max(right_t1, right_t2))
        ]
        msp.add_lwpolyline(right_poly, close=True, dxfattribs={'layer': 'PLAN_OUTLINE'})
        msp.add_text("SIDE PLATFORM (R)", dxfattribs={'height': 0.5, 'layer': 'PLAN_TEXT'}).set_placement(
            (s_start + 5.0, (min(right_t1, right_t2) + max(right_t1, right_t2)) / 2))