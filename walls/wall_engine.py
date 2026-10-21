from config.master_config import StationProjectConfig
from helper.box_helper import CommonHelper
from walls.rectangular_wall import RectangularWall
from walls.wall_data import WallData
from walls.wall_package import WallPackage
from walls.wall_shape_type import WallShapeType


class WallEngine:
    """외벽(좌/우)과 시·종점 마감벽 BIM 객체를 층별로 만들고, 3D DXF / IFC의 단일 데이터 원천이 된다.

    - 벽체는 층별로 분할: 층 경계는 중간 슬래브 중심면 (최하층 바닥 = 바닥 슬래브 상면, 최상층 상단 = 천장 슬래브 하면)
    - 모서리 체적이 겹치지 않도록 측벽은 마감벽 사이 구간(wall_t ~ L-wall_t)만 차지
    """

    def __init__(self, config_params: StationProjectConfig):
        self.cfg = config_params
        self.sp = config_params.station
        self.wall_packages: list[WallPackage] = []
        self._build_wall_bim_objects()

    # ---------- 공통 ----------
    def level_name(self, floor_n: int) -> str:
        """floor_n: 1 = 최하층"""
        p = self.sp
        return f"B{p.floors - floor_n + 1}F" if p.floors > 1 else f"{floor_n}F"

    def z_offsets(self, floor_n: int) -> tuple[float, float]:
        """층 floor_n 벽체의 하단/상단 (바닥 슬래브 상면 기준 상대 높이)"""
        p = self.sp
        story_h = p.height / p.floors
        bottom = (floor_n - 1) * story_h
        top = floor_n * story_h if floor_n < p.floors else p.height - p.slab_t
        return bottom, top

    def wall_corners(self, wall: WallData) -> tuple[float, float, float, float, float, float]:
        """(s0, s1, t0, t1, z_bot(s0), z_bot(s1))"""
        sh = wall.shape
        return CommonHelper.prism_corners(wall.pos_x, wall.pos_y, wall.pos_z, sh.length, sh.width, sh.rise)

    def _wall_defs(self):
        """(코드, 계열명, s0, s1, t0, t1)"""
        p = self.sp
        hw, wt = p.width / 2.0, p.wall_t
        return [
            ("START", "콘크리트-마감벽", 0.0, wt, -hw, hw),
            ("L", "콘크리트-외벽", wt, p.length - wt, -hw, -hw + wt),
            ("R", "콘크리트-외벽", wt, p.length - wt, hw - wt, hw),
            ("END", "콘크리트-마감벽", p.length - wt, p.length, -hw, hw),
        ]

    # ---------- 생성 ----------
    def _build_wall_bim_objects(self):
        p = self.sp
        if p.wall_t <= 0 or 2 * p.wall_t >= min(p.length, p.width):
            raise ValueError("외벽 두께가 0 이하이거나 정거장 길이/폭에 비해 너무 큽니다.")

        for floor_n in range(1, p.floors + 1):
            level = self.level_name(floor_n)
            package = WallPackage(level=level, package_id=f"PKG_{level}_WALLS")
            z_lo, z_hi = self.z_offsets(floor_n)
            if z_hi - z_lo <= 0:
                raise ValueError(f"{level} 벽체 높이가 0 이하입니다. 층 높이/슬래브 두께를 확인하세요.")

            for code, family, s0, s1, t0, t1 in self._wall_defs():
                lv0, lv1 = self.cfg.lv(s0) - p.offset, self.cfg.lv(s1) - p.offset
                shape = RectangularWall(
                    wall_type=WallShapeType.RECTANGLE,
                    length=s1 - s0, width=t1 - t0, height=z_hi - z_lo, rise=lv1 - lv0)
                package.add_wall(WallData(
                    name=f"WALL_{level}_{code}",
                    family_name=family,
                    type_name=f"{int(round(p.wall_t * 1000))}mm",
                    level=level,
                    pos_x=(s0 + s1) / 2.0,
                    pos_y=(t0 + t1) / 2.0,
                    pos_z=(lv0 + lv1) / 2.0 + z_lo,
                    rotation=0.0,
                    material="Concrete_C24",
                    shape_type=WallShapeType.RECTANGLE,
                    shape=shape,
                ))
            self.wall_packages.append(package)

    # ---------- 작도 ----------
    def add_wall_mesh(self, msp, bp_x, bp_y, theta):
        """3D 절대 좌표계 메쉬 (bp_x, bp_y = 정거장 시점의 WCS 좌표). 한 번만 호출할 것"""
        for package in self.wall_packages:
            for wall in package.walls:
                s0, s1, t0, t1, z0, z1 = self.wall_corners(wall)
                h = wall.shape.height
                faces = CommonHelper.create_sloped_box_faces_global(
                    s0, s1, t0, t1, z0, z1, z0 + h, z1 + h, bp_x, bp_y, theta)
                wall.source_element = [msp.add_3dface(f, dxfattribs={"layer": "STRUCT_WALL"}) for f in faces]
