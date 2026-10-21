from config.master_config import StationProjectConfig
from helper.box_helper import CommonHelper
from helper.view_item import ViewItem
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

    # ---------- 2D 도면 (BIM 객체에서 직접 생성) ----------
    def section_items(self, sta):
        """횡단면도: 측점 sta 의 절단면에 걸리는 승강장 슬래브 + 지지벽체 (ㅠ형)"""
        items = []
        L = self.sp.length
        for package in self.platform_packages:
            for pl in package.platforms:
                s0, s1, t0, t1, z0, z1 = self.platform_corners(pl)
                if not CommonHelper.cut_by_s(sta, s0, s1, L):
                    continue
                zb = z0 + (sta - s0) / (s1 - s0) * (z1 - z0)
                th = pl.shape.thickness
                label = None
                if pl.part == PlatformPart.SLAB:
                    code = "L" if pl.side == PlatformSide.LEFT else "R"
                    label = (f"SIDE PLATFORM ({code})", min(t0, t1) + 0.5, zb + th + 0.3, 0.4, "SEC_TEXT")
                items.append(ViewItem.rect(pl.name, "SEC_PLATFORM", t0, t1, zb, zb + th,
                                           hatch_layer="SEC_HATCH", label=label))
        return items

    def profile_items(self):
        """종단면도: 선형 중심(t=0)에서는 잘리지 않고 측면에 보이는 승강장 (좌/우 동일 형상은 한 번만)"""
        items, seen = [], set()
        for package in self.platform_packages:
            for pl in package.platforms:
                s0, s1, t0, t1, z0, z1 = self.platform_corners(pl)
                if CommonHelper.cut_by_t(t0, t1):
                    continue
                key = tuple(round(v, 4) for v in (s0, s1, z0, z1, pl.shape.thickness))
                if key in seen:
                    continue
                seen.add(key)
                label = None
                if pl.part == PlatformPart.SLAB:
                    mid = (s0 + s1) / 2.0
                    top = (z0 + z1) / 2.0 + pl.shape.thickness
                    label = (f"PLATFORM SLAB (FL+{self.p.plat_height:.2f}m)", mid - 10.0, top + 0.5, 0.6, "PROF_TEXT")
                items.append(ViewItem.sloped(pl.name, "PROF_BEYOND", s0, s1, z0, z1, pl.shape.thickness, label=label))
        return items

    def plan_items(self, cut_h):
        """평면도: 절단 높이 아래에 보이는 승강장 슬래브 윤곽 (지지벽체는 슬래브에 가려짐)"""
        items = []
        for package in self.platform_packages:
            for pl in package.platforms:
                if pl.part != PlatformPart.SLAB:
                    continue
                s0, s1, t0, t1, z0, z1 = self.platform_corners(pl)
                code = "L" if pl.side == PlatformSide.LEFT else "R"
                label = (f"SIDE PLATFORM ({code})", s0 + 5.0, (t0 + t1) / 2.0, 0.5, "PLAN_TEXT")
                items.append(ViewItem.rect(pl.name, "PLAN_OUTLINE", s0, s1, t0, t1, label=label))
        return items
