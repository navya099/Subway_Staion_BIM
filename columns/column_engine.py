import math
from config.master_config import StationProjectConfig
from helper.box_helper import CommonHelper
from columns.column_shape_type import ColumnShapeType
from columns.rectangular_column import RectangularColumn
from columns.column_data import ColumnData
from columns.column_package import ColumnPackage


class ColumnEngine:
    def __init__(self, config_params: StationProjectConfig):
        self.sp = config_params.station
        self.pf = config_params.platform
        self.cp = config_params.column

        # BIM 객체들을 층별로 관리할 패키지 딕셔너리 또는 리스트
        self.column_packages: list[ColumnPackage] = []
        self._build_column_bim_objects()

    def _build_column_bim_objects(self):
        """
        선형 제원과 기둥 파라미터를 바탕으로 모든 기둥의 BIM 객체(Data & Shape)를 생성하고 패키징
        """
        p = self.sp
        cp = self.cp
        pf = self.pf

        story_h = p.height / p.floors
        s_start = p.wall_t + cp.width
        s_end = p.length - p.wall_t - cp.width

        # 층별(Level)로 ColumnPackage 생성 관리
        for floor_idx in cp.target_floors:
            level_name = f"B{p.floors - floor_idx + 1}F" if p.floors > 1 else f"{floor_idx}F"
            package = ColumnPackage()  # 층별 그룹 패키지

            curr_s = s_start
            col_count = 1
            while curr_s <= s_end:
                # 1. 위치 및 고도 계산
                align_lv = p.calc_align_lv(curr_s)
                floor_top_z = align_lv - p.offset

                if floor_idx == 1 and cp.sync_with_platform:
                    z_bot = floor_top_z + pf.plat_height + pf.plat_thick
                    z_top = floor_top_z + story_h - p.slab_t / 2
                else:
                    z_bot = floor_top_z + ((floor_idx - 1) * story_h) + p.slab_t / 2
                    z_top = floor_top_z + (floor_idx * story_h) - p.slab_t / 2

                col_height = z_top - z_bot

                # 2. 형상 객체 생성 (RectangularColumn)
                col_shape = RectangularColumn(
                    column_type=ColumnShapeType.RECTANGLE,
                    height=col_height,
                    width=cp.width,
                    depth=cp.depth
                )

                # 3. BIM 데이터 객체 생성 (ColumnData -> CommonBIMData 상속)
                col_data = ColumnData(
                    name=f"COL_{level_name}_{col_count:02d}",
                    family_name="콘크리트-직사각형 기둥",
                    type_name=f"{int(cp.width * 1000)}x{int(cp.depth * 1000)}mm",
                    level=level_name,
                    pos_x=curr_s,  # 선형 로컬 기준 S 좌표 또는 절대 좌표 변환 전 임시 저장
                    pos_y=0.0,
                    pos_z=z_bot,
                    rotation=0.0,
                    material="Concrete_C24",
                    shape_type=ColumnShapeType.RECTANGLE,
                    shape=col_shape
                )

                package.columns.append(col_data) if hasattr(package, 'columns') else setattr(package, 'columns',
                                                                                             [col_data])
                curr_s += cp.interval
                col_count += 1

            self.column_packages.append(package)

    def add_column_mesh(self, msp, bp_x, bp_y, theta):
        """
        구축된 BIM 객체 데이터를 순회하며 3D 절대 좌표계 메쉬 작도
        """
        p = self.sp
        cp = self.cp
        half_w_col = cp.width / 2.0
        half_d_col = cp.depth / 2.0

        for package in self.column_packages:
            for col in package.columns:
                curr_s = col.pos_x
                z_bot = col.pos_z
                z_top = z_bot + col.shape.height

                faces = CommonHelper.create_sloped_box_faces_global(
                    curr_s - half_w_col, curr_s + half_w_col,
                    -half_d_col, half_d_col,
                    z_bot, z_bot, z_top, z_top,
                    bp_x, bp_y, theta
                )
                for f in faces:
                    # 원본 3D 엔티티 바인딩 (source_element 활용)
                    ent = msp.add_3dface(f, dxfattribs={"layer": "STRUCT_COLUMN"})
                    col.source_element = ent

    def add_column_plan(self, msp):
        """2D 평면도 상에 기둥 단면 표시"""
        cp = self.cp
        half_w_col = cp.width / 2.0
        half_d_col = cp.depth / 2.0

        # 첫 번째 패키지(또는 전체 대표 층)의 기둥 위치 순회
        if self.column_packages:
            for col in self.column_packages[0].columns:
                curr_s = col.pos_x
                col_poly = [
                    (curr_s - half_w_col, -half_d_col),
                    (curr_s + half_w_col, -half_d_col),
                    (curr_s + half_w_col, half_d_col),
                    (curr_s - half_w_col, half_d_col)
                ]
                msp.add_lwpolyline(col_poly, close=True, dxfattribs={'layer': 'PLAN_OUTLINE'})

    def add_column_section(self, floor_top_z, x_offset, msp):
        """2D 횡단면도 상에 중앙 기둥 단면 표시"""
        p = self.sp
        cp = self.cp
        pf = self.pf
        half_d_col = cp.depth / 2.0
        story_h = p.height / p.floors

        for floor_idx in cp.target_floors:
            z_bot = floor_top_z + ((floor_idx - 1) * story_h) + (
                pf.plat_height if floor_idx == 1 else p.slab_t / 2) if hasattr(self, 'pf') else floor_top_z + (
                        (floor_idx - 1) * story_h) + p.slab_t / 2
            z_top = floor_top_z + (floor_idx * story_h) - p.slab_t / 2

            col_section_poly = [
                (x_offset - half_d_col, z_bot),
                (x_offset + half_d_col, z_bot),
                (x_offset + half_d_col, z_top),
                (x_offset - half_d_col, z_top)
            ]
            msp.add_lwpolyline(col_section_poly, close=True, dxfattribs={'layer': 'SEC_CONCRETE'})

    def add_column_profile(self, msp, x_pts):
        """2D 종단면도 상에 기둥 단면 일괄 작도"""
        cp = self.cp
        half_w_col = cp.width / 2.0

        for package in self.column_packages:
            for col in package.columns:
                curr_s = col.pos_x
                s1 = curr_s - half_w_col
                s2 = curr_s + half_w_col
                z_bot1 = col.pos_z
                z_bot2 = col.pos_z
                z_top1 = z_bot1 + col.shape.height
                z_top2 = z_bot2 + col.shape.height

                col_poly = [
                    (s1, z_bot1),
                    (s2, z_bot2),
                    (s2, z_top2),
                    (s1, z_top1)
                ]
                msp.add_lwpolyline(col_poly, close=True, dxfattribs={'layer': 'PROF_CONCRETE'})