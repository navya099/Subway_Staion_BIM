from config.cadconfig import StationParameters
from helper.box_helper import CommonHelper
from platforms.platform_params import PlatformParameters


class PlatformEngine:
    def __init__(self, params: StationParameters ,platform_params: PlatformParameters):
        self.p = platform_params
        self.sp = params

    def add_platform_mesh(self, msp, s_curr, s_next, f_top1, f_top2, half_w, bp_x, bp_y, theta):
        # --- [상대식 승강장 3D 메쉬 추가 (절대 좌표계 변환 적용)] ---
        plat_z1 = f_top1 + self.p.plat_height
        plat_z2 = f_top2 + self.p.plat_height

        # 좌측 승강장 (하선측: -D/2 기준)
        left_t1 = -self.p.track_spacing / 2 - self.p.plat_offset
        left_t2 = -half_w + self.sp.wall_t
        for f in CommonHelper.create_sloped_box_faces_global(
            s_curr, s_next, min(left_t1, left_t2), max(left_t1, left_t2),
            plat_z1, plat_z2, plat_z1 + self.p.plat_thick, plat_z2 + self.p.plat_thick,
            bp_x, bp_y, theta
        ):
            msp.add_3dface(f, dxfattribs={"layer": "STRUCT_PLATFORM"})

        # 우측 승강장 (상선측: +D/2 기준)
        right_t1 = half_w - self.sp.wall_t
        right_t2 = self.p.track_spacing / 2 + self.p.plat_offset
        for f in CommonHelper.create_sloped_box_faces_global(
            s_curr, s_next, min(right_t1, right_t2), max(right_t1, right_t2),
            plat_z1, plat_z2, plat_z1 + self.p.plat_thick, plat_z2 + self.p.plat_thick,
            bp_x, bp_y, theta
        ):
            msp.add_3dface(f, dxfattribs={"layer": "STRUCT_PLATFORM"})

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
            lv = self.sp.calc_align_lv(x)
            f_top = lv - self.sp.offset
            z_top = f_top + self.p.plat_height + self.p.plat_thick
            top_pts.append((x, z_top))

        # 2. 승강장 하단선 좌표 연산 (역순으로 감싸기)
        bot_pts = []
        for x in reversed(plat_x_pts):
            lv = self.sp.calc_align_lv(x)
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
        mid_lv = self.sp.calc_align_lv(mid_x)
        mid_z = (mid_lv - self.sp.offset) + self.p.plat_height + self.p.plat_thick + 0.5
        msp.add_text("PLATFORM SLAB (FL+1.1m)", dxfattribs={'height': 0.6, 'layer': 'PROF_TEXT'}).set_placement(
            (mid_x - 10.0, mid_z))