from config.master_config import StationProjectConfig
from helper import prism_member as PM
from helper.view_item import ViewItem
from openings import decompose
from openings.opening_data import OpeningData
from openings.opening_kind import OpeningKind
from platforms.platform_data import PlatformData
from platforms.platform_package import PlatformPackage
from platforms.platform_type import PlatformPart, PlatformSide, PlatformType
from platforms.rectangular_platform import RectangularPlatform
from slabs.slab_piece import SlabPiece


class PlatformEngine:
    """상대식 승강장(좌/우) BIM 객체를 만들고, 3D DXF / IFC의 단일 데이터 원천이 된다.

    - 승강장은 최하층에 놓이며, 내공 영역(0 ~ L)만 차지해 벽체와 겹치지 않음
    - 승강장 슬래브: 바닥 슬래브 상면 + plat_height 에서 plat_thick 두께 (기존 모델 정의 유지)
    - 2D 도면(횡단/종단/평면)은 현재 파라미터에서 직접 계산 (추후 객체 기반으로 전환 예정)
    """

    def __init__(self, config: StationProjectConfig):
        self.p = config.platform
        self.sp = config.station
        self.cfg = config
        self.lv = config.lv  # 정거장 로컬 거리 s → 선형 표고
        self.platform_packages: list[PlatformPackage] = []
        self._build_platform_bim_objects()

    # ---------- 공통 ----------
    def level_name(self, floor_n: int) -> str:
        """floor_n: 1 = 최하층"""
        return f"B{self.sp.floors - floor_n + 1}F" if self.sp.floors > 1 else f"{floor_n}F"

    def platform_corners(self, plat: PlatformData) -> tuple[float, float, float, float, float, float]:
        """(s0, s1, t0, t1, z_bot(s0), z_bot(s1))"""
        return PM.corners(self.cfg, plat)

    # ---------- 생성 ----------
    def _build_platform_bim_objects(self):
        p, sp = self.p, self.sp
        if p.plat_type != PlatformType.NORMAL:
            raise NotImplementedError("섬식 승강장은 아직 지원하지 않습니다 (상대식만 지원).")
        if p.plat_thick <= 0:
            return  # 승강장 미설정 → 객체 없음

        s0, s1 = 0.0, sp.length                          # 승강장은 내공 영역 안
        _, (edge, inner) = p.slab_t_ranges(sp.width)   # 선로 중심 ~ 승강장 끝단, 벽체 안쪽 면 (t 절대값)
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
        rise, mid_lv = lv1 - lv0, self.lv((s0 + s1) / 2.0) - sp.offset      # 중심 s 에서의 선형 표고

        def add(name, part, side, family, type_t, t0, t1, z_lo, vert):
            package.add_platform(PlatformData(
                name=name, family_name=family, type_name=f"{int(round(type_t * 1000))}mm", level=level,
                pos_x=(s0 + s1) / 2.0, pos_y=(t0 + t1) / 2.0, pos_z=mid_lv + z_lo, rotation=0.0,
                material="Concrete_C24", part=part, side=side,
                shape=RectangularPlatform(length=s1 - s0, width=t1 - t0, thickness=vert, rise=rise,
                                          curve_factor=PM.curve_factor(self.cfg, s0, s1, (t0 + t1) / 2.0))))

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
        self._cut_holes()

    def _cut_holes(self):
        """승강장 위 에스컬레이터의 하부 피트: 승강장 슬래브를 구멍만큼 조각으로 나누고 구멍 객체를 만든다.
        구멍은 슬래브 하나 안에 있어야 하고(배치 계산이 보장) 지지벽체와 겹치면 안 된다"""
        holes = self.cfg.platform_holes()
        if not holes:
            return
        plats = [pl for pk in self.platform_packages for pl in pk.platforms]
        for name, s0, s1, t0, t1 in holes:
            slab = next((pl for pl in plats if pl.part == PlatformPart.SLAB and
                         PM.t_range(pl)[0] - 1e-6 <= t0 and t1 <= PM.t_range(pl)[1] + 1e-6), None)
            if slab is None:
                raise ValueError(f"승강장 구멍 {name}: 승강장 슬래브 안에 있지 않습니다")
            for leg in plats:
                if leg.part == PlatformPart.SUPPORT_WALL and decompose.overlap_area(
                        (s0, s1, t0, t1), (*PM.s_range(leg), *PM.t_range(leg))) > 1e-9:
                    raise ValueError(f"승강장 구멍 {name}: 승강장 지지벽체 {leg.name} 과(와) 겹칩니다 "
                                     "(에스컬레이터 t 위치나 트러스 폭을 확인하세요)")
            slab.openings.append(OpeningData(
                name=f"OPEN_{name}_{slab.name}", family_name="승강장 구멍", type_name="에스컬레이터 피트",
                level=slab.level, kind=OpeningKind.ESCALATOR, slab_name=slab.name,
                s_range=(s0, s1), t_range=(t0, t1), **self._piece_dims(s0, s1, t0, t1)))
        for slab in plats:
            if slab.openings:
                region = (*PM.s_range(slab), *PM.t_range(slab))
                holes_of = [(*o.s_range, *o.t_range) for o in slab.openings]
                slab.pieces = [SlabPiece(name=f"{slab.name}_P{k}", **self._piece_dims(*rect))
                               for k, rect in enumerate(decompose.subtract_rects(region, holes_of), start=1)]

    def _piece_dims(self, s0, s1, t0, t1) -> dict:
        """승강장 슬래브와 같은 높이·두께의 (s0~s1) x (t0~t1) 부재 위치·형상"""
        p, sp = self.p, self.sp
        lv0, lv1 = self.lv(s0) - sp.offset, self.lv(s1) - sp.offset
        return dict(pos_x=(s0 + s1) / 2.0, pos_y=(t0 + t1) / 2.0,
                    pos_z=self.lv((s0 + s1) / 2.0) - sp.offset + p.plat_height,
                    shape=RectangularPlatform(length=s1 - s0, width=t1 - t0, thickness=p.plat_thick, rise=lv1 - lv0,
                                              curve_factor=PM.curve_factor(self.cfg, s0, s1, (t0 + t1) / 2.0)))

    # ---------- 작도 ----------
    def add_platform_mesh(self, msp):
        """3D 절대 좌표계 메쉬 (직선: 각기둥, 곡선: 선형을 따르는 스윕). 한 번만 호출할 것"""
        for package in self.platform_packages:
            for plat in package.platforms:
                faces = [f for m in plat.members for f in PM.mesh_faces(self.cfg, m)]
                plat.source_element = [msp.add_3dface(f, dxfattribs={"layer": "STRUCT_PLATFORM"}) for f in faces]

    # ---------- 2D 도면 (BIM 객체에서 직접 생성) ----------
    def section_items(self, sta):
        """횡단면도: 측점 sta 의 절단면에 걸리는 승강장 슬래브 + 지지벽체 (ㅠ형)"""
        items = []
        for package in self.platform_packages:
            for pl in package.platforms:
                cut = PM.section_rect(self.cfg, pl, sta)
                if not cut:
                    continue
                t0, t1, zb = cut
                th = pl.shape.thickness
                label = None
                if pl.part == PlatformPart.SLAB:
                    code = "L" if pl.side == PlatformSide.LEFT else "R"
                    label = (f"SIDE PLATFORM ({code})", min(t0, t1) + 0.5, zb + th + 0.3, 0.4, "SEC_TEXT")
                gaps = [o.t_range for o in pl.openings if o.s_range[0] - 1e-9 <= sta < o.s_range[1] - 1e-9]
                for k, (a, b) in enumerate(decompose.subtract_intervals(t0, t1, gaps)):   # 피트 구멍 구간은 비움
                    items.append(ViewItem.rect(pl.name, "SEC_PLATFORM", a, b, zb, zb + th,
                                               hatch_layer="SEC_HATCH", label=label if k == 0 else None))
        return items

    def profile_items(self):
        """종단면도: 선형 중심(t=0)에서는 잘리지 않고 측면에 보이는 승강장 (좌/우 동일 형상은 한 번만)"""
        items, seen = [], set()
        for package in self.platform_packages:
            for pl in package.platforms:
                s0, s1, t0, t1, z0, z1 = self.platform_corners(pl)
                if PM.cut_by_centerline(pl):
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
                items.append(PM.profile_view(self.cfg, pl, "PROF_BEYOND", label=label))
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
