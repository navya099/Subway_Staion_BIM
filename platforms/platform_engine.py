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