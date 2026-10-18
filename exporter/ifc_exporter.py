import uuid
import ifcopenshell
import ifcopenshell.guid
import ifcopenshell.template
from columns.column_engine import ColumnEngine
from columns.rectangular_column import RectangularColumn
from config.master_config import StationProjectConfig


class IFCExporter:
    def __init__(self, config: StationProjectConfig, schema_version: str = "IFC4"):
        self.config = config
        self.schema = schema_version

        # 1. ifcopenshell.file()을 직접 호출하여 빈 IFC 파일 생성 (스스로 스키마 지정)
        self.file = ifcopenshell.file(schema=self.schema)

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

    def _setup_spatial_structure(self):
        """IfcSite, IfcBuilding 및 층별 IfcBuildingStorey 공간 계층 구성"""
        owner_history = self.file.by_type("IfcOwnerHistory")[0] if self.file.by_type("IfcOwnerHistory") else None

        # 1. Site
        site = self.file.create_entity("IfcSite", GlobalId=ifcopenshell.guid.new(), Name="Station Site")
        self.file.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=self.project,
                                RelatedObjects=[site])

        # 2. Building
        building = self.file.create_entity("IfcBuilding", GlobalId=ifcopenshell.guid.new(), Name="지하철 정거장")
        self.file.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=site,
                                RelatedObjects=[building])

        # 3. Storeys (층별 공간)
        p = self.config.station
        story_h = p.height / p.floors

        for floor_idx in range(1, p.floors + 1):
            level_name = f"B{p.floors - floor_idx + 1}F" if p.floors > 1 else f"{floor_idx}F"
            elevation = (floor_idx - 1) * story_h

            storey = self.file.create_entity(
                "IfcBuildingStorey",
                GlobalId=ifcopenshell.guid.new(),
                Name=level_name,
                Elevation=float(elevation)
            )
            self.file.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=building,
                                    RelatedObjects=[storey])
            self.storeys[level_name] = storey

    def export_columns(self, column_engine: ColumnEngine):
        """ColumnEngine의 ColumnPackage/ColumnData를 순회하며 IfcColumn으로 매핑"""
        for package in column_engine.column_packages:
            storey = self.storeys.get(package.level, list(self.storeys.values())[0])
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

                # 3. IfcColumn 엔티티 생성
                ifc_column = self.file.create_entity(
                    "IfcColumn",
                    GlobalId=ifc_guid,
                    Name=col.name,
                    ObjectType=col.type_name,
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

    def _create_local_placement(self, x: float, y: float, z: float):
        """3D 좌표 위치에 대한 IfcLocalPlacement 생성"""
        # 1. 3D 좌표점 생성 (Coordinates는 반드시 Python 리스트 또는 튜플 형태)
        point = self.file.create_entity(
            "IfcCartesianPoint",
            Coordinates=[float(x), float(y), float(z)]
        )

        # 2. 3D 축/위치 배치 정의
        axis2placement = self.file.create_entity(
            "IfcAxis2Placement3D",
            Location=point
        )

        # 3. IfcLocalPlacement 생성 (올바른 인자 속성명 사용)
        return self.file.create_entity(
            "IfcLocalPlacement",
            PlacementRelTo=None,  # 최상위 배정이므로 None (상위 Placement가 있다면 해당 객체 지정)
            RelativePlacement=axis2placement
        )

    def _create_rectangular_column_geometry(self, width: float, depth: float, height: float):
        """압출(ExtrudedAreaSolid) 방식을 통한 사각기둥 3D Solid 형상 정의"""
        # 2D 사각형 단면 프로파일 정의
        profile = self.file.create_entity(
            "IfcRectangleProfileDef",
            ProfileType="AREA",
            ProfileName="ColumnRectangleProfile",
            XDim=float(width),
            YDim=float(depth)
        )
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
        mat = self.file.create_entity("IfcMaterial", Name=material_name)
        self.file.create_entity(
            "IfcRelAssociatesMaterial",
            GlobalId=ifcopenshell.guid.new(),
            RelatedObjects=[element],
            RelatingMaterial=mat
        )

    def save(self, filepath: str):
        """IFC 파일 저장"""
        self.file.write(filepath)