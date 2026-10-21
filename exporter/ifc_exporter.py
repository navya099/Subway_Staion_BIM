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
from platforms.platform_engine import PlatformEngine
from platforms.platform_type import PlatformPart
from slabs.slab_engine import SlabEngine
from slabs.slab_shape_type import SlabKind
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
        story_h = p.height / p.floors
        floor_top_z = self.config.lv(0.0) - p.offset

        for floor_idx in range(1, p.floors + 1):
            level_name = f"B{p.floors - floor_idx + 1}F" if p.floors > 1 else f"{floor_idx}F"
            elevation = floor_top_z + (floor_idx - 1) * story_h

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
                s0, s1, t0, t1, z0, z1 = wall_engine.wall_corners(wall)
                ifc_wall = self.file.create_entity(
                    "IfcWall",
                    GlobalId=ifcopenshell.guid.compress(uuid.UUID(wall.guid).hex),
                    Name=wall.name,
                    ObjectType=wall.type_name,
                    ObjectPlacement=self._create_local_placement(s0, t0, z0),  # 벽체 최소 모서리(s0, t0, 하단)
                    Representation=self._create_wall_geometry(wall.shape),
                    PredefinedType="SOLIDWALL"
                )
                if wall.material:
                    self._assign_material(ifc_wall, wall.material)
                elements.append(ifc_wall)

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
                s0, s1, t0, t1, z0, z1 = platform_engine.platform_corners(plat)
                sh = plat.shape
                is_slab = plat.part == PlatformPart.SLAB
                ifc_plat = self.file.create_entity(
                    "IfcSlab" if is_slab else "IfcWall",
                    GlobalId=ifcopenshell.guid.compress(uuid.UUID(plat.guid).hex),
                    Name=plat.name,
                    ObjectType="PLATFORM" if is_slab else "PLATFORM_SUPPORT",
                    ObjectPlacement=self._create_local_placement(s0, t0, z0),
                    Representation=self._create_sloped_prism_geometry(
                        sh.length, sh.width, sh.thickness, sh.rise, "PlatformProfile" if is_slab else "PlatformSupportProfile"),
                    PredefinedType="USERDEFINED" if is_slab else "SOLIDWALL"
                )
                if plat.material:
                    self._assign_material(ifc_plat, plat.material)
                elements.append(ifc_plat)

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
                s0, s1, t0, t1, z0, z1 = slab_engine.slab_corners(slab)
                sh = slab.shape
                ifc_slab = self.file.create_entity(
                    "IfcSlab",
                    GlobalId=ifcopenshell.guid.compress(uuid.UUID(slab.guid).hex),
                    Name=slab.name,
                    ObjectType=slab.type_name,
                    ObjectPlacement=self._create_local_placement(s0, t0, z0),
                    Representation=self._create_sloped_prism_geometry(
                        sh.length, sh.width, sh.thickness, sh.rise, "SlabProfile"),
                    PredefinedType=self._SLAB_PREDEFINED[slab.kind]
                )
                if slab.material:
                    self._assign_material(ifc_slab, slab.material)
                elements.append(ifc_slab)

            if elements:
                self.file.create_entity(
                    "IfcRelContainedInSpatialStructure",
                    GlobalId=ifcopenshell.guid.new(),
                    RelatingStructure=storey,
                    RelatedElements=elements
                )

    def _create_wall_geometry(self, shape):
        return self._create_sloped_prism_geometry(shape.length, shape.width, shape.height, shape.rise, "WallProfile")

    def _create_sloped_prism_geometry(self, length, width, height, rise, profile_name):
        """s–z 평행사변형 단면(구배 반영)을 t 방향 width만큼 압출한 Solid (벽체·슬래브 공통).
        배치 원점 = 부재 최소 모서리, 로컬 X = s, Y = t, Z = 상향."""
        f = self.file
        pts = [(0.0, 0.0), (length, rise), (length, rise + height), (0.0, height)]
        poly = f.create_entity(
            "IfcPolyline",
            Points=[f.create_entity("IfcCartesianPoint", Coordinates=(float(x), float(z))) for x, z in pts + [pts[0]]])
        profile = f.create_entity("IfcArbitraryClosedProfileDef", ProfileType="AREA", ProfileName=profile_name,
                                  OuterCurve=poly)
        # 압출 축을 -Y(로컬)로 두고 Y=width에서 시작 → t0 ~ t0+width 범위를 채움, 프로파일 Y축은 상향(+Z)
        position = f.create_entity(
            "IfcAxis2Placement3D",
            Location=f.create_entity("IfcCartesianPoint", Coordinates=(0.0, float(width), 0.0)),
            Axis=f.create_entity("IfcDirection", DirectionRatios=(0.0, -1.0, 0.0)),
            RefDirection=f.create_entity("IfcDirection", DirectionRatios=(1.0, 0.0, 0.0)))
        solid = f.create_entity(
            "IfcExtrudedAreaSolid",
            SweptArea=profile, Position=position,
            ExtrudedDirection=f.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0)),
            Depth=float(width))
        shape_rep = f.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=f.by_type("IfcGeometricRepresentationContext")[0],
            RepresentationIdentifier="Body", RepresentationType="SweptSolid", Items=[solid])
        return f.create_entity("IfcProductDefinitionShape", Representations=[shape_rep])

    def _create_local_placement(self, s: float, t: float, z: float):
        """정거장 로컬 (s, t, z) → WCS 위치 + 선형 방위각 회전의 IfcLocalPlacement"""
        ox, oy = self.config.origin()
        theta = self.config.align.theta
        c, sn = math.cos(theta), math.sin(theta)
        point = self.file.create_entity(
            "IfcCartesianPoint",
            Coordinates=[float(ox + s * c - t * sn), float(oy + s * sn + t * c), float(z)]
        )
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