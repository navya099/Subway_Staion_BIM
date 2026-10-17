import math

from config.master_config import StationProjectConfig
from helper.box_helper import CommonHelper



class ColumnEngine:
    def __init__(self, config_params: StationProjectConfig):
        self.sp = config_params.station
        self.pf = config_params.platform
        self.cp = config_params.column

    def add_column_mesh(self, msp, bp_x, bp_y, theta):
        """
        3D 절대 좌표계 상에 선형 중심선을 따라 중앙 기둥 일괄 배치
        """
        p = self.sp
        cp = self.cp
        pf = self.pf

        half_w_col = cp.width / 2.0
        half_d_col = cp.depth / 2.0

        # 기둥 배치 구간 (시/종점 마감 벽체 제외)
        s_start = p.wall_t + cp.width
        s_end = p.length - p.wall_t - cp.width

        curr_s = s_start
        while curr_s <= s_end:
            # 해당 측점의 정거장 레벨 연산
            align_lv = p.calc_align_lv(curr_s)
            floor_top_z = align_lv - p.offset
            story_h = p.height / p.floors

            # 층별 기둥 생성 루프
            for floor_idx in cp.target_floors:
                # 층 하단/상단 Z 레벨 계산
                if floor_idx == 1 and cp.sync_with_platform:
                    # 승강장이 있는 최하층 바닥 ~ 중간 슬래브 하단
                    z_bot = floor_top_z + pf.plat_height + pf.plat_thick
                    z_top = floor_top_z + story_h - p.slab_t / 2
                else:
                    # 일반 층 (예: 상층 대합실 등)
                    z_bot = floor_top_z + ((floor_idx - 1) * story_h) + p.slab_t / 2
                    z_top = floor_top_z + (floor_idx * story_h) - p.slab_t / 2

                # 3D 박스 면 생성 (중앙 기둥이므로 t 근처 0.0 중심에 배치)
                # CommonHelper의 sloped_box_faces_global 사용 (s1, s2, t1, t2, zb1, zb2, zt1, zt2)
                faces = CommonHelper.create_sloped_box_faces_global(
                    curr_s - half_w_col, curr_s + half_w_col,
                    -half_d_col, half_d_col,
                    z_bot, z_bot, z_top, z_top,
                    bp_x, bp_y, theta
                )
                for f in faces:
                    msp.add_3dface(f, dxfattribs={"layer": "STRUCT_COLUMN"})

            curr_s += cp.interval

    def add_column_plan(self, msp):
        """2D 평면도 상에 기둥 단면(점 혹은 사각형) 표시"""
        p = self.sp
        cp = self.cp
        pf = self.pf

        half_w_col = cp.width / 2.0
        half_d_col = cp.depth / 2.0

        s_start = p.wall_t + cp.width
        s_end = p.length - p.wall_t - cp.width

        curr_s = s_start
        while curr_s <= s_end:
            col_poly = [
                (curr_s - half_w_col, -half_d_col),
                (curr_s + half_w_col, -half_d_col),
                (curr_s + half_w_col, half_d_col),
                (curr_s - half_w_col, half_d_col)
            ]
            msp.add_lwpolyline(col_poly, close=True, dxfattribs={'layer': 'PLAN_OUTLINE'})
            curr_s += cp.interval

    def add_column_section(self, floor_top_z, x_offset, msp):
        """2D 횡단면도 상에 중앙 기둥 단면 표시 (C.L. 위치)"""
        p = self.sp
        cp = self.cp
        pf = self.pf

        half_d_col = cp.depth / 2.0
        story_h = p.height / p.floors

        for floor_idx in cp.target_floors:
            z_bot = floor_top_z + ((floor_idx - 1) * story_h) + (pf.plat_height if floor_idx == 1 else p.slab_t / 2)
            z_top = floor_top_z + (floor_idx * story_h) - p.slab_t / 2

            col_section_poly = [
                (x_offset - half_d_col, z_bot),
                (x_offset + half_d_col, z_bot),
                (x_offset + half_d_col, z_top),
                (x_offset - half_d_col, z_top)
            ]
            msp.add_lwpolyline(col_section_poly, close=True, dxfattribs={'layer': 'SEC_CONCRETE'})

    def add_column_profile(self, msp, x_pts):
        """
        2D 종단면도 상에 종단구배를 반영한 중앙 기둥 단면 일괄 작도
        """
        p = self.sp
        cp = self.cp  # self.p 또는 self.cp (인스턴스 변수명에 맞게 연결)
        pf = self.pf

        half_w_col = cp.width / 2.0
        story_h = p.height / p.floors

        # 기둥 배치 구간 (시/종점 마감 벽체 제외)
        s_start = p.wall_t + cp.width
        s_end = p.length - p.wall_t - cp.width

        curr_s = s_start
        while curr_s <= s_end:
            s1 = curr_s - half_w_col
            s2 = curr_s + half_w_col

            # 기둥 시작/끝 위치에서의 바닥 상단 표고 연산 (종단구배 반영)
            f_top1 = p.calc_align_lv(s1) - p.offset
            f_top2 = p.calc_align_lv(s2) - p.offset

            # 층별 기둥 작도
            for floor_idx in cp.target_floors:
                if floor_idx == 1 and cp.sync_with_platform:
                    # 승강장이 있는 최하층 (승강장 상단 ~ 중간 슬래브 하단)
                    z_bot1 = f_top1 + pf.plat_height + pf.plat_thick
                    z_bot2 = f_top2 + pf.plat_height + pf.plat_thick
                    z_top1 = f_top1 + story_h - p.slab_t / 2.0
                    z_top2 = f_top2 + story_h - p.slab_t / 2.0
                else:
                    # 일반 층
                    z_bot1 = f_top1 + ((floor_idx - 1) * story_h) + p.slab_t / 2.0
                    z_bot2 = f_top2 + ((floor_idx - 1) * story_h) + p.slab_t / 2.0
                    z_top1 = f_top1 + (floor_idx * story_h) - p.slab_t / 2.0
                    z_top2 = f_top2 + (floor_idx * story_h) - p.slab_t / 2.0

                # 종단면 기둥 4점 다각형
                col_poly = [
                    (s1, z_bot1),
                    (s2, z_bot2),
                    (s2, z_top2),
                    (s1, z_top1)
                ]
                msp.add_lwpolyline(col_poly, close=True, dxfattribs={'layer': 'PROF_CONCRETE'})

            curr_s += cp.interval