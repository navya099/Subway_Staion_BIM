import math
import os
import uuid
import ifcopenshell
import ifcopenshell.guid
import ifcopenshell.template
from columns.column_engine import ColumnEngine
from columns.circle_column import CircleColumn
from columns.rectangular_column import RectangularColumn
from config.master_config import StationProjectConfig
from helper import prism_member as PM
from platforms.platform_engine import PlatformEngine
from platforms.platform_type import PlatformPart
from slabs.slab_engine import SlabEngine
from slabs.slab_shape_type import SlabKind
from escalators.escalator_engine import EscalatorEngine
from escalators.escalator_type import EscalatorPartKind
from helper.strip_member import part_faces
from passages.passage_engine import PassageEngine
from passages.passage_type import PassagePartKind
from stairs.stair_engine import StairEngine
from stairs.stair_type import StairPartKind
from walls.wall_engine import WallEngine


class IFCExporter:
    def __init__(self, config: StationProjectConfig, schema_version: str = "IFC4"):
        self.config = config
        self.schema = schema_version

        # 1. ifcopenshell.file()을 직접 호출하여 빈 IFC 파일 생성 (스스로 스키마 지정)
        self.file = ifcopenshell.file(schema=self.schema)
        self._materials: dict[str, ifcopenshell.entity_instance] = {}

        # 2. 필수 기본 엔티티(Project, Units, Context 등) 수동 생성
        self._init_project_structure(project_name="지하철 개착정거장 BIM 프로젝트")

        # 3. 공간 구조(Spatial Structure) 맵 초기화
        self.storeys: dict[str, ifcopenshell.entity_instance] = {}
        self._setup_spatial_structure()

    def _init_project_structure(self, project_name: str):
        """기본 IFC 프로젝트 및 미터법 단위계, 기하학적 표현 컨텍스트 설정"""
        # 1. 미터법 단위계 설정 (METRE, SQUARE_METRE, CUBIC_METRE)
        length_unit = self.file.create_entity(
            "IfcSIUnit",
            UnitType="LENGTHUNIT",
            Name="METRE"
        )
        area_unit = self.file.create_entity(
            "IfcSIUnit",
            UnitType="AREAUNIT",
            Name="SQUARE_METRE"
        )
        volume_unit = self.file.create_entity(
            "IfcSIUnit",
            UnitType="VOLUMEUNIT",
            Name="CUBIC_METRE"
        )

        unit_assignment = self.file.create_entity(
            "IfcUnitAssignment",
            Units=[length_unit, area_unit, volume_unit]
        )

        # 2. 3D 기하 표현 컨텍스트 설정
        geom_context = self.file.create_entity(
            "IfcGeometricRepresentationContext",
            ContextIdentifier="Model",
            ContextType="Model",
            CoordinateSpaceDimension=3,
            Precision=1e-5,
            WorldCoordinateSystem=self.file.create_entity(
                "IfcAxis2Placement3D",
                Location=self.file.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))
            )
        )

        # 3. IfcProject 생성
        self.project = self.file.create_entity(
            "IfcProject",
            GlobalId=ifcopenshell.guid.new(),
            Name=project_name,
            UnitsInContext=unit_assignment,
            RepresentationContexts=[geom_context]
        )

    def _placement(self, z: float = 0.0, relative_to=None):
        """(0, 0, z) 에 놓인 IfcLocalPlacement (공간 구조 요소용)"""
        point = self.file.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, float(z)))
        axis2 = self.file.create_entity("IfcAxis2Placement3D", Location=point)
        return self.file.create_entity("IfcLocalPlacement", PlacementRelTo=relative_to, RelativePlacement=axis2)

    def _setup_spatial_structure(self):
        """IfcSite, IfcBuilding 및 층별 IfcBuildingStorey 공간 계층 구성 (모두 WCS 원점 기준 배치)

        부재는 WCS 절대 좌표로 배치되므로 층의 Elevation 도 절대 표고
        (정거장 시점 s=0 에서의 바닥 슬래브 상면 + 층 하단 높이)로 둔다.
        """
        # 1. Site
        site_placement = self._placement()
        site = self.file.create_entity("IfcSite", GlobalId=ifcopenshell.guid.new(), Name="Station Site",
                                       ObjectPlacement=site_placement)
        self.file.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=self.project,
                                RelatedObjects=[site])

        # 2. Building
        building_placement = self._placement(relative_to=site_placement)
        building = self.file.create_entity("IfcBuilding", GlobalId=ifcopenshell.guid.new(), Name="지하철 정거장",
                                           ObjectPlacement=building_placement)
        self.file.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=site,
                                RelatedObjects=[building])

        # 3. Storeys (층별 공간)
        p = self.config.station
        floor_top_z = self.config.lv(0.0) - p.offset

        for floor_idx in range(1, p.floors + 1):
            level_name = f"B{p.floors - floor_idx + 1}F" if p.floors > 1 else f"{floor_idx}F"
            elevation = floor_top_z + p.floor_level(floor_idx)

            storey = self.file.create_entity(
                "IfcBuildingStorey",
                GlobalId=ifcopenshell.guid.new(),
                Name=level_name,
                ObjectPlacement=self._placement(elevation, relative_to=building_placement),
                Elevation=float(elevation)
            )
            self.file.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=building,
                                    RelatedObjects=[storey])
            self.storeys[level_name] = storey

    def export_columns(self, column_engine: ColumnEngine):
        """ColumnEngine의 ColumnPackage/ColumnData를 순회하며 IfcColumn으로 매핑"""
        for package in column_engine.column_packages:
            storey = self.storeys[package.level]  # 패키지 level이 층 이름과 일치해야 함
            contained_elements = []

            for col in package.columns:
                if not col.shape:
                    continue

                # GUID 변환 (Python UUID -> IFC Base64 GUID)
                ifc_guid = ifcopenshell.guid.compress(uuid.UUID(col.guid).hex)

                # 1. 위치 및 회전 좌표계 (IfcLocalPlacement)
                placement = self._create_local_placement(col.pos_x, col.pos_y, col.pos_z)

                # 2. 형상(Geometry Representation) 생성
                representation = None
                if isinstance(col.shape, RectangularColumn):
                    representation = self._create_rectangular_column_geometry(
                        width=col.shape.width,
                        depth=col.shape.depth,
                        height=col.shape.height
                    )
                elif isinstance(col.shape, CircleColumn):
                    representation = self._create_circle_column_geometry(
                        radius=col.shape.radius, height=col.shape.height)

                # 3. IfcColumn 엔티티 생성
                ifc_column = self.file.create_entity(
                    "IfcColumn",
                    GlobalId=ifc_guid,
                    Name=col.name,
                    ObjectType=col.type_name,
                    PredefinedType="COLUMN",
                    ObjectPlacement=placement,
                    Representation=representation
                )

                # 4. 재질(Material) 연동
                if col.material:
                    self._assign_material(ifc_column, col.material)

                contained_elements.append(ifc_column)

            # 해당 층(IfcBuildingStorey)에 기둥 요소 그룹 배치 바인딩
            if contained_elements:
                self.file.create_entity(
                    "IfcRelContainedInSpatialStructure",
                    GlobalId=ifcopenshell.guid.new(),
                    RelatingStructure=storey,
                    RelatedElements=contained_elements
                )

    def export_walls(self, wall_engine: WallEngine):
        """WallEngine의 WallPackage/WallData를 순회하며 IfcWall로 매핑 (층별 IfcBuildingStorey에 포함)"""
        for package in wall_engine.wall_packages:
            storey = self.storeys[package.level]
            elements = []
            for wall in package.walls:
                if not wall.shape:
                    continue
                if wall.pieces:                                   # 출구통로 오프닝이 있는 측벽: 조각들
                    placement, representation = self._slab_geometry(wall)
                else:
                    placement, representation = self._member_geometry(wall, "WallProfile")
                ifc_wall = self.file.create_entity(
                    "IfcWall",
                    GlobalId=ifcopenshell.guid.compress(uuid.UUID(wall.guid).hex),
                    Name=wall.name,
                    ObjectType=wall.type_name,
                    ObjectPlacement=placement,
                    Representation=representation,
                    PredefinedType="SOLIDWALL"
                )
                if wall.material:
                    self._assign_material(ifc_wall, wall.material)
                elements.append(ifc_wall)
                self._export_slab_openings(wall, ifc_wall)

            if elements:
                self.file.create_entity(
                    "IfcRelContainedInSpatialStructure",
                    GlobalId=ifcopenshell.guid.new(),
                    RelatingStructure=storey,
                    RelatedElements=elements
                )

    def export_platforms(self, platform_engine: PlatformEngine):
        """승강장(ㅠ형)을 슬래브는 IfcSlab(USERDEFINED: PLATFORM), 지지벽체는 IfcWall(PLATFORM_SUPPORT)로 매핑"""
        for package in platform_engine.platform_packages:
            storey = self.storeys[package.level]
            elements = []
            for plat in package.platforms:
                if not plat.shape:
                    continue
                is_slab = plat.part == PlatformPart.SLAB
                if is_slab and plat.pieces:                      # 에스컬레이터 피트 구멍이 있는 승강장 슬래브: 조각들
                    placement, representation = self._slab_geometry(plat)
                else:
                    placement, representation = self._member_geometry(
                        plat, "PlatformProfile" if is_slab else "PlatformSupportProfile")
                ifc_plat = self.file.create_entity(
                    "IfcSlab" if is_slab else "IfcWall",
                    GlobalId=ifcopenshell.guid.compress(uuid.UUID(plat.guid).hex),
                    Name=plat.name,
                    ObjectType="PLATFORM" if is_slab else "PLATFORM_SUPPORT",
                    ObjectPlacement=placement,
                    Representation=representation,
                    PredefinedType="USERDEFINED" if is_slab else "SOLIDWALL"
                )
                if plat.material:
                    self._assign_material(ifc_plat, plat.material)
                elements.append(ifc_plat)
                if is_slab:
                    self._export_slab_openings(plat, ifc_plat)

            if elements:
                self.file.create_entity(
                    "IfcRelContainedInSpatialStructure",
                    GlobalId=ifcopenshell.guid.new(),
                    RelatingStructure=storey,
                    RelatedElements=elements
                )

    _SLAB_PREDEFINED = {SlabKind.FLOOR: "BASESLAB", SlabKind.MID: "FLOOR", SlabKind.ROOF: "ROOF"}

    def export_slabs(self, slab_engine: SlabEngine):
        """SlabEngine의 SlabPackage/SlabData를 순회하며 IfcSlab으로 매핑 (소속 층 IfcBuildingStorey에 포함)"""
        for package in slab_engine.slab_packages:
            storey = self.storeys[package.level]
            elements = []
            for slab in package.slabs:
                if not slab.shape:
                    continue
                placement, representation = self._slab_geometry(slab)
                ifc_slab = self.file.create_entity(
                    "IfcSlab",
                    GlobalId=ifcopenshell.guid.compress(uuid.UUID(slab.guid).hex),
                    Name=slab.name,
                    ObjectType=slab.type_name,
                    ObjectPlacement=placement,
                    Representation=representation,
                    PredefinedType=self._SLAB_PREDEFINED[slab.kind]
                )
                if slab.material:
                    self._assign_material(ifc_slab, slab.material)
                elements.append(ifc_slab)
                self._export_slab_openings(slab, ifc_slab)

            if elements:
                self.file.create_entity(
                    "IfcRelContainedInSpatialStructure",
                    GlobalId=ifcopenshell.guid.new(),
                    RelatingStructure=storey,
                    RelatedElements=elements
                )

    def _slab_geometry(self, slab):
        """슬래브의 (배치, 형상). 오프닝이 없으면 일반 부재와 같고, 있으면 오프닝을 뺀 직사각형 조각들을 한 형상의 여러 덩어리로 담는다"""
        if not slab.pieces:
            return self._member_geometry(slab, "SlabProfile")
        cfg = self.config
        if cfg.align.is_straight:
            s0, _, t0, _, z0, _ = PM.corners(cfg, slab)             # 슬래브 최소 모서리 = 배치 원점
            items = []
            for m in slab.pieces:
                ps0, _, pt0, _, pz0, _ = PM.corners(cfg, m)
                sh = m.shape
                items.append(self._sloped_prism_solid(sh.length, sh.width, sh.vertical, sh.rise, "SlabProfile",
                                                      origin=(ps0 - s0, pt0 - t0, pz0 - z0)))
            return self._create_local_placement(s0, t0, z0), self._product_shape(items, "SweptSolid")
        items = [self._face_set(PM.sweep_quads(PM.rings(cfg, m))) for m in slab.pieces]
        return self._placement(), self._product_shape(items, "Tessellation")

    def _export_slab_openings(self, slab, ifc_slab):
        """슬래브를 뚫는 오프닝을 IfcOpeningElement 로 만들어 IfcRelVoidsElement 로 슬래브에 연결"""
        for op in slab.openings:
            placement, representation = self._member_geometry(op, "OpeningProfile")
            ifc_op = self.file.create_entity(
                "IfcOpeningElement",
                GlobalId=ifcopenshell.guid.compress(uuid.UUID(op.guid).hex),
                Name=op.name, Description=op.type_name, ObjectType=op.kind.code,
                ObjectPlacement=placement, Representation=representation, PredefinedType="OPENING")
            self.file.create_entity(
                "IfcRelVoidsElement", GlobalId=ifcopenshell.guid.new(),
                RelatingBuildingElement=ifc_slab, RelatedOpeningElement=ifc_op)

    def export_stairs(self, stair_engine: StairEngine):
        """계단: IfcStair(STRAIGHT_RUN_STAIR) 가 런(IfcStairFlight)과 중간 계단참(IfcSlab LANDING)을 IfcRelAggregates 로 묶고,
        IfcStair 만 시작 층 IfcBuildingStorey 에 포함 (부분 부재는 집합체를 통해 층에 속함)"""
        for package in stair_engine.stair_packages:
            storey = self.storeys[package.level]
            elements = []
            for stair in package.stairs:
                s0, _ = stair.s_range
                t0, _ = stair.t_range
                ifc_stair = self.file.create_entity(
                    "IfcStair", GlobalId=ifcopenshell.guid.compress(uuid.UUID(stair.guid).hex),
                    Name=stair.name, Description=f"{stair.level} → 위층, 승강장 위" if stair.on_platform else f"{stair.level} → 위층",
                    ObjectType=stair.type_name, PredefinedType="STRAIGHT_RUN_STAIR",
                    ObjectPlacement=self._create_local_placement(s0, t0, stair.pos_z) if self.config.align.is_straight
                    else self._placement(stair.pos_z))
                parts = []
                for part in stair.parts:
                    placement, representation = self._strip_part_geometry(part, "StairProfile")
                    common = dict(GlobalId=ifcopenshell.guid.compress(uuid.UUID(part.guid).hex), Name=part.name,
                                  ObjectType=part.type_name, ObjectPlacement=placement, Representation=representation)
                    if part.kind == StairPartKind.FLIGHT:
                        el = self.file.create_entity(
                            "IfcStairFlight", **common, PredefinedType="STRAIGHT", NumberOfRisers=part.n_risers,
                            NumberOfTreads=part.n_treads, RiserHeight=float(stair.riser), TreadLength=float(stair.tread))
                    else:
                        el = self.file.create_entity("IfcSlab", **common, PredefinedType="LANDING")
                    if part.material:
                        self._assign_material(el, part.material)
                    parts.append(el)
                self.file.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(),
                                        RelatingObject=ifc_stair, RelatedObjects=parts)
                elements.append(ifc_stair)
            if elements:
                self.file.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                                        RelatingStructure=storey, RelatedElements=elements)

    _ESC_ENTITY = {EscalatorPartKind.TRUSS: ("IfcBuildingElementPart", "USERDEFINED"),
                   EscalatorPartKind.STEPS: ("IfcBuildingElementPart", "USERDEFINED"),
                   EscalatorPartKind.BALUSTRADE: ("IfcRailing", "BALUSTRADE"),
                   EscalatorPartKind.HANDRAIL: ("IfcRailing", "HANDRAIL")}

    def export_escalators(self, escalator_engine: EscalatorEngine):
        """에스컬레이터: IfcTransportElement(ESCALATOR) 가 트러스·스텝(IfcBuildingElementPart), 난간 패널·핸드레일(IfcRailing)을
        IfcRelAggregates 로 묶고, IfcTransportElement 만 시작 층 IfcBuildingStorey 에 포함"""
        for package in escalator_engine.escalator_packages:
            storey = self.storeys[package.level]
            elements = []
            for esc in package.escalators:
                s0 = esc.s_wp[0]
                ifc_esc = self.file.create_entity(
                    "IfcTransportElement", GlobalId=ifcopenshell.guid.compress(uuid.UUID(esc.guid).hex),
                    Name=esc.name, Description=f"{esc.level} → 위층" + (", 승강장 위" if esc.on_platform else ""),
                    ObjectType=esc.type_name, PredefinedType="ESCALATOR",
                    ObjectPlacement=self._create_local_placement(s0, esc.pos_y, esc.pos_z) if self.config.align.is_straight
                    else self._placement(esc.pos_z))
                parts = []
                for part in esc.parts:
                    entity, predefined = self._ESC_ENTITY[part.kind]
                    placement, representation = self._strip_part_geometry(part, f"Escalator{part.kind.value.title()}Profile")
                    el = self.file.create_entity(
                        entity, GlobalId=ifcopenshell.guid.compress(uuid.UUID(part.guid).hex), Name=part.name,
                        ObjectType=part.kind.value, ObjectPlacement=placement, Representation=representation,
                        PredefinedType=predefined)
                    if part.material:
                        self._assign_material(el, part.material)
                    parts.append(el)
                self.file.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(),
                                        RelatingObject=ifc_esc, RelatedObjects=parts)
                elements.append(ifc_esc)
            if elements:
                self.file.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                                        RelatingStructure=storey, RelatedElements=elements)

    _PASSAGE_ENTITY = {PassagePartKind.FLOOR: ("IfcSlab", "FLOOR"), PassagePartKind.ROOF: ("IfcSlab", "ROOF"),
                       PassagePartKind.WALL: ("IfcWall", "SOLIDWALL")}

    def export_passages(self, passage_engine: PassageEngine):
        """출구통로: IfcElementAssembly(USERDEFINED: EXIT_PASSAGE) 가 구간별 바닥·천장 슬래브(IfcSlab)와 측벽(IfcWall)을 묶고,
        IfcElementAssembly 만 통로가 붙는 층 IfcBuildingStorey 에 포함. 부재 형상 = 조각마다 곧은 압출(세계 좌표)"""
        for package in passage_engine.passage_packages:
            storey = self.storeys[package.level]
            elements = []
            for ps in package.passages:
                asm = self.file.create_entity(
                    "IfcElementAssembly", GlobalId=ifcopenshell.guid.compress(uuid.UUID(ps.guid).hex), Name=ps.name,
                    Description=f"{ps.level} 출구통로 (꼭짓점 {len(ps.vertices)}개, 꺾임 {len(ps.corners)}곳)", ObjectType="EXIT_PASSAGE",
                    ObjectPlacement=self._placement(), PredefinedType="USERDEFINED")
                parts = []
                for e in ps.elements:
                    entity, predefined = self._PASSAGE_ENTITY[e.kind]
                    if any(p.skewed for p in e.pieces):         # 꺾임부 연귀(비스듬한 끝): 면 집합으로 정확히
                        items, rep = [self._face_set(p.faces()) for p in e.pieces], "Tessellation"
                    else:
                        items = [self._box_piece_solid(p, f"Passage{e.kind.value.title()}Profile") for p in e.pieces]
                        rep = "SweptSolid"
                    el = self.file.create_entity(
                        entity, GlobalId=ifcopenshell.guid.compress(uuid.UUID(e.guid).hex), Name=e.name,
                        ObjectType=e.type_name, ObjectPlacement=self._placement(),
                        Representation=self._product_shape(items, rep), PredefinedType=predefined)
                    if e.material:
                        self._assign_material(el, e.material)
                    parts.append(el)
                self.file.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(),
                                        RelatingObject=asm, RelatedObjects=parts)
                elements.append(asm)
            if elements:
                self.file.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                                        RelatingStructure=storey, RelatedElements=elements)

    def _box_piece_solid(self, p, profile_name):
        """BoxPiece → 세계 좌표의 IfcExtrudedAreaSolid: 연직 단면(v, dz)을 축 방향 + 구배로 민 각기둥.
        Position: 원점 = 축 시작점(기준 표고), z' = 축 방향, x' = v(축의 왼쪽) → y' = 연직 위.
        압출 방향 (0, 구배, 1) 이라 연직 단면이 그대로 유지된다 (체적 = 단면적 x 수평 길이)"""
        f = self.file
        x0, y0, z0 = p.point(p.a0, 0.0, 0.0)
        poly = f.create_entity("IfcPolyline", Points=[f.create_entity("IfcCartesianPoint", Coordinates=(float(v), float(dz)))
                                                      for v, dz in p.sect + [p.sect[0]]])
        profile = f.create_entity("IfcArbitraryClosedProfileDef", ProfileType="AREA", ProfileName=profile_name, OuterCurve=poly)
        position = f.create_entity(
            "IfcAxis2Placement3D",
            Location=f.create_entity("IfcCartesianPoint", Coordinates=(float(x0), float(y0), float(z0))),
            Axis=f.create_entity("IfcDirection", DirectionRatios=(float(p.ux), float(p.uy), 0.0)),
            RefDirection=f.create_entity("IfcDirection", DirectionRatios=(float(p.vx), float(p.vy), 0.0)))
        norm = math.hypot(1.0, p.slope)
        return f.create_entity(
            "IfcExtrudedAreaSolid", SweptArea=profile, Position=position,
            ExtrudedDirection=f.create_entity("IfcDirection", DirectionRatios=(0.0, float(p.slope / norm), float(1.0 / norm))),
            Depth=float(p.length * norm))

    def _strip_part_geometry(self, part, profile_name):
        """띠 부재(계단 런/계단참, 에스컬레이터 부재)의 (배치, 형상). 직선: s–z 단면 다각형 압출 1개, 곡선: 띠마다 닫힌 면 집합"""
        cfg = self.config
        t0, t1 = part.t_range
        if cfg.align.is_straight:
            pts = part.shape.profile_points()
            s_min, z_min = min(p[0] for p in pts), min(p[1] for p in pts)
            local = [(s - s_min, z - z_min) for s, z in pts]
            solid = self._profile_solid(local, t1 - t0, profile_name)
            return self._create_local_placement(s_min, t0, z_min), self._product_shape([solid], "SweptSolid")
        items = [self._face_set(quads) for quads in part_faces(cfg, part)]
        return self._placement(), self._product_shape(items, "Tessellation")

    def _member_geometry(self, m, profile_name):
        """벽체/슬래브/승강장 부재의 (배치, 형상).
        직선 선형: 압출 Solid + 부재 최소 모서리 배치 (정확하고 가벼움).
        곡선 선형: 선형을 따라 휜 부재라 압출로 표현할 수 없어, 표본 측점마다의 단면을 이은 닫힌 면 집합(IfcPolygonalFaceSet)으로
        내보내고 좌표는 WCS 절대값이라 배치는 원점."""
        cfg, sh = self.config, m.shape
        if cfg.align.is_straight:
            s0, s1, t0, t1, z0, z1 = PM.corners(cfg, m)
            return (self._create_local_placement(s0, t0, z0),
                    self._create_sloped_prism_geometry(sh.length, sh.width, sh.vertical, sh.rise, profile_name))
        return self._placement(), self._create_tessellated_geometry(PM.sweep_quads(PM.rings(cfg, m)))

    def _create_tessellated_geometry(self, quads):
        """바깥 방향 사각 면 목록 → IfcPolygonalFaceSet (Tessellation) 형상"""
        return self._product_shape([self._face_set(quads)], "Tessellation")

    def _face_set(self, quads):
        f = self.file
        index, coords = {}, []

        def idx(p):
            key = tuple(round(c, 9) for c in p)
            if key not in index:
                coords.append(tuple(float(c) for c in p))
                index[key] = len(coords)                      # IFC 인덱스는 1부터
            return index[key]
        faces = [f.create_entity("IfcIndexedPolygonalFace", CoordIndex=[idx(p) for p in q]) for q in quads]
        return f.create_entity("IfcPolygonalFaceSet", Coordinates=f.create_entity("IfcCartesianPointList3D", CoordList=coords),
                               Closed=True, Faces=faces)

    def _product_shape(self, items, rep_type):
        f = self.file
        shape_rep = f.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=f.by_type("IfcGeometricRepresentationContext")[0],
            RepresentationIdentifier="Body", RepresentationType=rep_type, Items=items)
        return f.create_entity("IfcProductDefinitionShape", Representations=[shape_rep])

    def _create_sloped_prism_geometry(self, length, width, height, rise, profile_name):
        """s–z 평행사변형 단면(구배 반영)을 t 방향 width만큼 압출한 Solid (벽체·슬래브 공통).
        배치 원점 = 부재 최소 모서리, 로컬 X = s, Y = t, Z = 상향."""
        return self._product_shape([self._sloped_prism_solid(length, width, height, rise, profile_name)], "SweptSolid")

    def _sloped_prism_solid(self, length, width, height, rise, profile_name, origin=(0.0, 0.0, 0.0)):
        """위 압출 Solid 1개. origin = 배치 원점 기준 (ds, dt, dz) 이동 (한 부재가 여러 덩어리일 때)"""
        pts = [(0.0, 0.0), (length, rise), (length, rise + height), (0.0, height)]
        return self._profile_solid(pts, width, profile_name, origin)

    def _profile_solid(self, pts, width, profile_name, origin=(0.0, 0.0, 0.0)):
        """s–z 다각형 단면(로컬 X = s, 프로파일 Y = 상향)을 t 방향 width 만큼 압출한 Solid (각기둥 부재·계단 공통)"""
        f = self.file
        ds, dt, dz = origin
        poly = f.create_entity(
            "IfcPolyline",
            Points=[f.create_entity("IfcCartesianPoint", Coordinates=(float(x), float(z))) for x, z in pts + [pts[0]]])
        profile = f.create_entity("IfcArbitraryClosedProfileDef", ProfileType="AREA", ProfileName=profile_name,
                                  OuterCurve=poly)
        # 압출 축을 -Y(로컬)로 두고 Y=width에서 시작 → t0 ~ t0+width 범위를 채움, 프로파일 Y축은 상향(+Z)
        position = f.create_entity(
            "IfcAxis2Placement3D",
            Location=f.create_entity("IfcCartesianPoint", Coordinates=(float(ds), float(dt + width), float(dz))),
            Axis=f.create_entity("IfcDirection", DirectionRatios=(0.0, -1.0, 0.0)),
            RefDirection=f.create_entity("IfcDirection", DirectionRatios=(1.0, 0.0, 0.0)))
        return f.create_entity(
            "IfcExtrudedAreaSolid",
            SweptArea=profile, Position=position,
            ExtrudedDirection=f.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0)),
            Depth=float(width))

    def _create_local_placement(self, s: float, t: float, z: float):
        """정거장 로컬 (s, t, z) → WCS 위치 + 선형 방위각 회전의 IfcLocalPlacement"""
        x, y = self.config.to_world(s, t)
        theta = self.config.theta_at(s)
        c, sn = math.cos(theta), math.sin(theta)
        point = self.file.create_entity("IfcCartesianPoint", Coordinates=[float(x), float(y), float(z)])
        axis2placement = self.file.create_entity(
            "IfcAxis2Placement3D",
            Location=point,
            RefDirection=self.file.create_entity("IfcDirection", DirectionRatios=(c, sn, 0.0))
        )
        return self.file.create_entity("IfcLocalPlacement", PlacementRelTo=None, RelativePlacement=axis2placement)

    def _create_rectangular_column_geometry(self, width: float, depth: float, height: float):
        """압출(ExtrudedAreaSolid) 방식을 통한 사각기둥 3D Solid 형상 정의"""
        profile = self.file.create_entity(
            "IfcRectangleProfileDef",
            ProfileType="AREA",
            ProfileName="ColumnRectangleProfile",
            XDim=float(width),
            YDim=float(depth)
        )
        return self._extrude_profile(profile, height)

    def _create_circle_column_geometry(self, radius: float, height: float):
        profile = self.file.create_entity(
            "IfcCircleProfileDef",
            ProfileType="AREA",
            ProfileName="ColumnCircleProfile",
            Radius=float(radius)
        )
        return self._extrude_profile(profile, height)

    def _extrude_profile(self, profile, height: float):
        # 압출 방향 (Z축 + 방향)
        dir3d = self.file.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0))
        position = self.file.create_entity(
            "IfcAxis2Placement3D",
            Location=self.file.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))
        )

        # 3D Solid Extrusion
        solid = self.file.create_entity(
            "IfcExtrudedAreaSolid",
            SweptArea=profile,
            Position=position,
            ExtrudedDirection=dir3d,
            Depth=float(height)
        )

        # SolidRepresentation 생성
        rep_item = solid
        shape_rep = self.file.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=self.file.by_type("IfcGeometricRepresentationContext")[0],
            RepresentationIdentifier="Body",
            RepresentationType="SweptSolid",
            Items=[rep_item]
        )
        return self.file.create_entity("IfcProductDefinitionShape", Representations=[shape_rep])

    def _assign_material(self, element, material_name: str):
        """BIM 요소에 IfcMaterial 할당"""
        mat = self._materials.get(material_name)
        if mat is None:
            mat = self._materials[material_name] = self.file.create_entity("IfcMaterial", Name=material_name)
        self.file.create_entity(
            "IfcRelAssociatesMaterial",
            GlobalId=ifcopenshell.guid.new(),
            RelatedObjects=[element],
            RelatingMaterial=mat
        )

    def save(self, filepath: str):
        """IFC 파일 저장"""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        self.file.write(filepath)