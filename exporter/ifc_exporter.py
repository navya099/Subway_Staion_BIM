import dataclasses
from types import SimpleNamespace
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
from entrances.entrance_engine import EntranceEngine
from escalators.escalator_engine import EscalatorEngine
from escalators.escalator_type import EscalatorPartKind
from helper.strip_member import Strip, StripShape, _fan, part_faces, strip_faces
from helper.taper_piece import TaperPiece
from entrances.entrance_layout import EntranceFrame
from passages.passage_engine import PassageEngine
from passages.passage_type import PassagePartKind
from rooms.room_engine import RoomEngine
from finishes.finish_engine import KINDS as FINISH_KINDS, FinishEngine
from elevators.elevator_engine import ElevatorEngine
from elevators.elevator_type import ElevatorPartKind
from ventilations.vent_engine import VentEngine
from ventilations.vent_type import VentPartKind
from stairs.stair_engine import StairEngine
from stairs.stair_finish import CODES as STAIR_FINISH_CODES
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
                if plat.pieces:                                  # 피트 구멍이 있는 승강장 슬래브·확폭 조각: 조각들
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
        if cfg.align.is_straight and not any(getattr(m, "trap", None) for m in slab.pieces):   # 확폭 사다리꼴 조각은 면 집합
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
                covers = []
                for fe in stair.finishes:                  # 계단 마감: IfcCovering → IfcRelCoversBldgElements (계단), 층 storey
                    label, predefined = STAIR_FINISH_CODES[fe.code]
                    el = self.file.create_entity(
                        "IfcCovering", GlobalId=ifcopenshell.guid.compress(uuid.UUID(fe.guid).hex), Name=fe.name,
                        Description=f"{stair.name} {label}", ObjectType=fe.type_name, ObjectPlacement=self._placement(),
                        Representation=self._product_shape([self._face_set(q) for q in part_faces(self.config, fe)],
                                                           "Tessellation"),
                        PredefinedType=predefined)
                    if fe.material:
                        self._assign_material(el, fe.material)
                    covers.append(el)
                if covers:
                    self.file.create_entity("IfcRelCoversBldgElements", GlobalId=ifcopenshell.guid.new(),
                                            RelatingBuildingElement=ifc_stair, RelatedCoverings=covers)
                    elements.extend(covers)
            if elements:
                self.file.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                                        RelatingStructure=storey, RelatedElements=elements)

    _ESC_ENTITY = {EscalatorPartKind.TRUSS: ("IfcBuildingElementPart", "USERDEFINED"),
                   EscalatorPartKind.STEPS: ("IfcBuildingElementPart", "USERDEFINED"),
                   EscalatorPartKind.BALUSTRADE: ("IfcRailing", "BALUSTRADE"),
                   EscalatorPartKind.HANDRAIL: ("IfcRailing", "HANDRAIL"),
                   EscalatorPartKind.SKIRT: ("IfcBuildingElementPart", "USERDEFINED"),
                   EscalatorPartKind.INNER_DECK: ("IfcBuildingElementPart", "USERDEFINED"),
                   EscalatorPartKind.OUTER_DECK: ("IfcBuildingElementPart", "USERDEFINED"),
                   EscalatorPartKind.FLOOR_PLATE: ("IfcBuildingElementPart", "USERDEFINED"),
                   EscalatorPartKind.COMB: ("IfcBuildingElementPart", "USERDEFINED"),
                   EscalatorPartKind.OUTER_PLATE: ("IfcBuildingElementPart", "USERDEFINED"),
                   EscalatorPartKind.NEWEL_BASE: ("IfcBuildingElementPart", "USERDEFINED"),
                   EscalatorPartKind.NEWEL_END_IN: ("IfcBuildingElementPart", "USERDEFINED"),
                   EscalatorPartKind.NEWEL_END_OUT: ("IfcBuildingElementPart", "USERDEFINED"),
                   EscalatorPartKind.CLAD_SIDE: ("IfcCovering", "CLADDING"),
                   EscalatorPartKind.CLAD_BOTTOM: ("IfcCovering", "CLADDING")}

    def export_escalators(self, escalator_engine: EscalatorEngine):
        """에스컬레이터: IfcTransportElement(ESCALATOR) 가 트러스·스텝(IfcBuildingElementPart), 난간 패널·핸드레일(IfcRailing)을
        IfcRelAggregates 로 묶고, IfcTransportElement 만 시작 층 IfcBuildingStorey 에 포함. 볼라드는 서는 층 storey"""
        bollards_at: dict = {}
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
                    ss = part.shape.strips
                    gapped = any(abs(b.s0 - a.s1) > 1e-9 for a, b in zip(ss, ss[1:]))    # 승강구 부재처럼 양끝에 떨어진 띠
                    if (part.kind == EscalatorPartKind.HANDRAIL and esc.steps) or gapped:  # 겹치거나 떨어진 띠 → 면 집합
                        placement = self._placement()
                        representation = self._product_shape([self._face_set(q) for q in part_faces(self.config, part)],
                                                             "Tessellation")
                    else:
                        placement, representation = self._strip_part_geometry(part, f"Escalator{part.kind.value.title()}Profile")
                    el = self.file.create_entity(
                        entity, GlobalId=ifcopenshell.guid.compress(uuid.UUID(part.guid).hex), Name=part.name,
                        ObjectType=part.kind.value, ObjectPlacement=placement, Representation=representation,
                        PredefinedType=predefined)
                    if part.material:
                        self._assign_material(el, part.material)
                    parts.append(el)
                for stp in esc.steps:                         # 개별 스텝: IfcBuildingElementPart(STEP) + 번호·체인 위치
                    el = self.file.create_entity(
                        "IfcBuildingElementPart", GlobalId=ifcopenshell.guid.compress(uuid.UUID(stp.guid).hex),
                        Name=stp.name, ObjectType="STEP", ObjectPlacement=self._placement(),
                        Representation=self._product_shape([self._face_set(q) for q in part_faces(self.config, stp)],
                                                           "Tessellation"), PredefinedType="USERDEFINED")
                    self._assign_material(el, stp.material)
                    props = [self.file.create_entity("IfcPropertySingleValue", Name="Index",
                                                     NominalValue=self.file.create_entity("IfcInteger", stp.index)),
                             self.file.create_entity("IfcPropertySingleValue", Name="ChainU",
                                                     NominalValue=self.file.create_entity("IfcLengthMeasure", float(stp.chain_u)))]
                    pset = self.file.create_entity("IfcPropertySet", GlobalId=ifcopenshell.guid.new(),
                                                   Name="SSBIM_EscalatorStep", HasProperties=props)
                    self.file.create_entity("IfcRelDefinesByProperties", GlobalId=ifcopenshell.guid.new(),
                                            RelatedObjects=[el], RelatingPropertyDefinition=pset)
                    parts.append(el)
                self.file.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(),
                                        RelatingObject=ifc_esc, RelatedObjects=parts)
                elements.append(ifc_esc)
                for b in esc.bollards:                        # 승강구 앞 볼라드: 서는 층 storey
                    el = self.file.create_entity(
                        "IfcBuildingElementProxy", GlobalId=ifcopenshell.guid.compress(uuid.UUID(b.guid).hex), Name=b.name,
                        Description=f"에스컬레이터 {esc.name} {'아래층' if b.end == 'L' else '위층'} 승강구 볼라드",
                        ObjectType="BOLLARD", ObjectPlacement=self._placement(), PredefinedType="USERDEFINED",
                        Representation=self._product_shape([self._face_set(self._finish_faces(p)) for p in b.pieces],
                                                           "Tessellation"))
                    self._assign_material(el, b.material)
                    bollards_at.setdefault(b.level, []).append(el)
            if elements:
                self.file.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                                        RelatingStructure=storey, RelatedElements=elements)
        for level, els in bollards_at.items():
            self.file.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                                    RelatingStructure=self.storeys[level], RelatedElements=els)

    def export_entrances(self, entrance_engine: EntranceEngine):
        """출입구: IfcElementAssembly(USERDEFINED: ENTRANCE) 가 박스 부재(IfcSlab FLOOR/ROOF, IfcWall),
        계단(IfcStair ⊃ IfcStairFlight + IfcSlab LANDING), 에스컬레이터(IfcTransportElement ⊃ 부재)를 묶고,
        IfcElementAssembly 만 통로가 붙은 층 storey 에 포함. 형상 = 출입구 좌표의 띠마다 s–z 사변형을 t 방향으로 민 압출"""
        for ent in entrance_engine.entrances:
            storey = self.storeys[ent.level]
            asm = self.file.create_entity(
                "IfcElementAssembly", GlobalId=ifcopenshell.guid.compress(uuid.UUID(ent.guid).hex), Name=ent.name,
                Description=f"{ent.level} 출입구 (출구통로 {ent.passage})", ObjectType="ENTRANCE",
                ObjectPlacement=self._frame_placement(ent.frame), PredefinedType="USERDEFINED")
            members = []
            for e in ent.elements:
                rep = "SweptSolid"
                local = [dataclasses.replace(p, ox=0.0, oy=0.0, ux=1.0, uy=0.0) for p in e.pieces]
                if any(isinstance(p, TaperPiece) for p in e.pieces):    # 바깥면 사선 전이 쐐기: 부재 전체를 면 집합 (출입구 좌표)
                    rep = "Tessellation"
                    t0, t1 = e.t_range
                    items = [self._face_set(strip_faces(self._LOCAL_FRAME, st, t0, t1)) for st in e.shape.strips] + \
                        [self._face_set(p.faces()) for p in local]
                else:
                    items = self._frame_strip_solids(e, "EntranceProfile") + \
                        [self._box_piece_solid(p, "EntranceHaunchProfile") for p in local]
                if e.kind == "WALL":
                    el = self._frame_element("IfcWall", e, ent.frame, items, PredefinedType="SOLIDWALL", rep=rep)
                elif e.kind == "ARCH":                         # 건축 마감 벽체 (파라펫 위 화강석 벽)
                    el = self._frame_element("IfcWall", e, ent.frame, items, PredefinedType="PARAPET", rep=rep)
                elif e.kind == "RAMP":                         # 바깥 경사로·계단 (박스 앞, 상부 승강구 ~ 지표)
                    el = self._frame_element("IfcRampFlight", e, ent.frame, items, PredefinedType="STRAIGHT", rep=rep)
                elif e.kind in ("PAVE", "LANDFIN"):            # 앞마당 포장·승강구 바닥 마감
                    el = self._frame_element("IfcCovering", e, ent.frame, items, PredefinedType="FLOORING", rep=rep)
                elif e.kind == "STEPS":
                    el = self._frame_element("IfcStairFlight", e, ent.frame, items, PredefinedType="STRAIGHT", rep=rep)
                else:
                    el = self._frame_element("IfcSlab", e, ent.frame, items, PredefinedType={"FLOOR": "FLOOR", "LEAN": "BASESLAB", "LANDING": "LANDING"}.get(e.kind, "ROOF"), rep=rep)
                members.append(el)
            st = ent.stair
            if st is not None:
                self._entrance_stair(ent, st, members)
            for esc in ent.escalators:
                self._entrance_escalator(ent, esc, members)
            for fe in ent.finishes:                            # 내부 마감: IfcCovering (바닥·벽·천장) / 천장틀 IfcMember
                items = self._frame_strip_solids(fe, "EntranceFinishProfile")
                if fe.kind == "FRAME":
                    members.append(self._frame_element("IfcMember", fe, ent.frame, items, PredefinedType="USERDEFINED"))
                else:
                    pre = {"FLOOR": "FLOORING", "FILL": "FLOORING", "WALL": "CLADDING", "SKIRT": "SKIRTINGBOARD", "CEILING": "CEILING"}[fe.kind]
                    members.append(self._frame_element("IfcCovering", fe, ent.frame, items, PredefinedType=pre))
            for ce in ent.canopy:                              # 캐노피: 기둥 IfcColumn · 보 IfcBeam · 유리 IfcPlate · 출구 사인
                items = self._frame_strip_solids(ce, "EntranceCanopyProfile")
                if ce.kind == "CP_POST":
                    members.append(self._frame_element("IfcColumn", ce, ent.frame, items, PredefinedType="COLUMN"))
                elif ce.kind == "CP_BEAM":
                    members.append(self._frame_element("IfcBeam", ce, ent.frame, items, PredefinedType="BEAM"))
                elif ce.kind == "CP_GLASS":
                    members.append(self._frame_element("IfcPlate", ce, ent.frame, items, PredefinedType="USERDEFINED"))
                elif ce.kind == "CP_WALL":                     # 외부 차단 유리벽
                    members.append(self._frame_element("IfcPlate", ce, ent.frame, items, PredefinedType="CURTAIN_PANEL"))
                else:
                    text = f"출입구 {ent.exit_number}" + (f" {ent.layout.spec.line_name}" if ent.layout.spec.line_name else "")
                    el = self._frame_element("IfcBuildingElementProxy", ce, ent.frame, items, PredefinedType="USERDEFINED",
                                             Description=text)
                    el.ObjectType = "SIGNAGE"
                    members.append(el)
            self.file.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=asm,
                                    RelatedObjects=members)
            self.file.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                                    RelatingStructure=storey, RelatedElements=[asm])

    def export_ext_evs(self, engine):
        """외부 엘리베이터: 지하 정지 층 storey 에 IfcElementAssembly(ELEVATOR) ⊃ 승강로·박스·기단 부재 +
        IfcTransportElement(ELEVATOR) ⊃ 카 부재. 형상 = 세계 좌표 면 집합 (EV 좌표계 띠 + 기운 조각)"""
        from elevators.ext_ev_engine import EXT_EV
        for x in engine.ext_evs:
            asm = self.file.create_entity(
                "IfcElementAssembly", GlobalId=ifcopenshell.guid.compress(uuid.UUID(x.guid).hex), Name=x.name,
                Description="외부 엘리베이터" + (f" ({x.layout.host_name})" if x.layout.host_name else ""), ObjectType="ELEVATOR",
                ObjectPlacement=self._placement(), PredefinedType="USERDEFINED")
            car = self.file.create_entity("IfcTransportElement", GlobalId=ifcopenshell.guid.new(), Name=f"{x.name}_CAR",
                                          ObjectType="ELEVATOR_CAR", ObjectPlacement=self._placement(), PredefinedType="ELEVATOR")
            shaft, car_parts = [car], []
            for e in x.elements:
                entity, pre = EXT_EV[e.kind][2]
                items = [self._face_set(f) for f in part_faces(e.frame, e)] + [self._face_set(p.faces()) for p in e.pieces]
                el = self.file.create_entity(entity, GlobalId=ifcopenshell.guid.compress(uuid.UUID(e.guid).hex), Name=e.name,
                                             ObjectType=e.type_name, ObjectPlacement=self._placement(),
                                             Representation=self._product_shape(items, "Tessellation"), PredefinedType=pre)
                if e.material:
                    self._assign_material(el, e.material)
                (car_parts if e.is_car else shaft).append(el)
            self.file.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=car, RelatedObjects=car_parts)
            self.file.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=asm, RelatedObjects=shaft)
            self.file.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                                    RelatingStructure=self.storeys[x.level], RelatedElements=[asm])

    def _entrance_stair(self, ent, st, members):
        """출입구 계단: IfcStair ⊃ 런·계단참, 계단 마감 IfcCovering → IfcRelCoversBldgElements"""
        ifc_stair = self.file.create_entity(
            "IfcStair", GlobalId=ifcopenshell.guid.compress(uuid.UUID(st.guid).hex), Name=st.name,
            ObjectType=st.type_name, PredefinedType="STRAIGHT_RUN_STAIR", ObjectPlacement=self._frame_placement(ent.frame))
        flights = []
        for p in st.parts:
            items = self._frame_strip_solids(p, "StairProfile")
            if p.kind == StairPartKind.FLIGHT:
                flights.append(self._frame_element("IfcStairFlight", p, ent.frame, items, PredefinedType="STRAIGHT",
                                                   NumberOfRisers=p.n_risers, NumberOfTreads=p.n_treads,
                                                   RiserHeight=float(st.riser), TreadLength=float(st.tread)))
            else:
                flights.append(self._frame_element("IfcSlab", p, ent.frame, items, PredefinedType="LANDING"))
        self.file.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=ifc_stair,
                                RelatedObjects=flights)
        members.append(ifc_stair)
        covers = []
        from stairs.stair_finish import CODES as STAIR_FIN_CODES
        for fe in st.finishes:                                 # 계단 마감 (정거장 계단과 같음)
            covers.append(self._frame_element("IfcCovering", fe, ent.frame, self._frame_strip_solids(fe, "StairFinishProfile"),
                                              PredefinedType=STAIR_FIN_CODES[fe.code][1]))
        if covers:
            self.file.create_entity("IfcRelCoversBldgElements", GlobalId=ifcopenshell.guid.new(),
                                    RelatingBuildingElement=ifc_stair, RelatedCoverings=covers)
            members += covers

    def _entrance_escalator(self, ent, esc, members):
        """출입구 에스컬레이터 1대: IfcTransportElement ⊃ 부재·스텝"""
        ifc_esc = self.file.create_entity(
            "IfcTransportElement", GlobalId=ifcopenshell.guid.compress(uuid.UUID(esc.guid).hex), Name=esc.name,
            ObjectType=esc.type_name, PredefinedType="ESCALATOR", ObjectPlacement=self._frame_placement(ent.frame))
        eparts = []
        for p in esc.parts:
            entity, predefined = self._ESC_ENTITY[p.kind]
            eparts.append(self._frame_element(entity, p, ent.frame, self._frame_strip_solids(p, "EscalatorProfile"),
                                              PredefinedType=predefined, ObjectType=p.kind.value))
        for stp in esc.steps:                                  # 개별 스텝 (정거장 에스컬레이터와 같은 속성)
            el = self._frame_element("IfcBuildingElementPart", stp, ent.frame,
                                     self._frame_strip_solids(stp, "EscalatorStepProfile"),
                                     PredefinedType="USERDEFINED", ObjectType="STEP")
            props = [self.file.create_entity("IfcPropertySingleValue", Name="Index",
                                             NominalValue=self.file.create_entity("IfcInteger", stp.index)),
                     self.file.create_entity("IfcPropertySingleValue", Name="ChainU",
                                             NominalValue=self.file.create_entity("IfcLengthMeasure", float(stp.chain_u)))]
            pset = self.file.create_entity("IfcPropertySet", GlobalId=ifcopenshell.guid.new(),
                                           Name="SSBIM_EscalatorStep", HasProperties=props)
            self.file.create_entity("IfcRelDefinesByProperties", GlobalId=ifcopenshell.guid.new(),
                                    RelatedObjects=[el], RelatingPropertyDefinition=pset)
            eparts.append(el)
        self.file.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=ifc_esc,
                                RelatedObjects=eparts)
        members.append(ifc_esc)

    def _frame_placement(self, frame):
        """출입구 좌표계 배치: 원점 = 통로 끝(표고 0), 로컬 X = 출입구 진행 방향, Y = 왼쪽(t), Z = 위"""
        f = self.file
        axis2 = f.create_entity("IfcAxis2Placement3D",
                                Location=f.create_entity("IfcCartesianPoint", Coordinates=(float(frame.px), float(frame.py), 0.0)),
                                RefDirection=f.create_entity("IfcDirection", DirectionRatios=(float(frame.ux), float(frame.uy), 0.0)))
        return f.create_entity("IfcLocalPlacement", PlacementRelTo=None, RelativePlacement=axis2)

    def _frame_strip_solids(self, m, profile_name):
        """띠 부재 → 띠마다 IfcExtrudedAreaSolid (출입구 좌표: s–z 사변형을 t 방향 폭만큼 압출)"""
        t0, t1 = m.t_range
        out = []
        for st in m.shape.strips:
            zmin = min(st.zb0, st.zb1)
            pts = [(0.0, st.zb0 - zmin), (st.s1 - st.s0, st.zb1 - zmin), (st.s1 - st.s0, st.zt_end - zmin), (0.0, st.zt - zmin)]
            pts = [q for i, q in enumerate(pts) if abs(q[0] - pts[i - 1][0]) + abs(q[1] - pts[i - 1][1]) > 1e-9]   # 높이 0 끝: 삼각형
            out.append(self._profile_solid(pts, t1 - t0, profile_name, origin=(st.s0, t0, zmin)))
        return out

    def _frame_element(self, entity, m, frame, items, rep="SweptSolid", **attrs):
        el = self.file.create_entity(
            entity, GlobalId=ifcopenshell.guid.compress(uuid.UUID(m.guid).hex), Name=m.name,
            ObjectPlacement=self._frame_placement(frame), Representation=self._product_shape(items, rep),
            **({"ObjectType": m.type_name} | attrs))
        if m.material:
            self._assign_material(el, m.material)
        return el

    _LOCAL_FRAME = EntranceFrame(0.0, 0.0, 1.0, 0.0)            # 출입구 좌표 그대로 (부재 배치 = 출입구 좌표계)

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

    _EV_ENTITY = {ElevatorPartKind.HOIST_WALL: ("IfcWall", "SOLIDWALL"), ElevatorPartKind.PIT_SLAB: ("IfcSlab", "BASESLAB"),
                  ElevatorPartKind.TOP_SLAB: ("IfcSlab", "ROOF"), ElevatorPartKind.CAR_FLOOR: ("IfcBuildingElementPart", "USERDEFINED"),
                  ElevatorPartKind.CAR_WALL: ("IfcBuildingElementPart", "USERDEFINED"),
                  ElevatorPartKind.CAR_ROOF: ("IfcBuildingElementPart", "USERDEFINED"), ElevatorPartKind.CAR_DOOR: ("IfcDoor", "DOOR"),
                  ElevatorPartKind.PIT_WALL: ("IfcWall", "SOLIDWALL"), ElevatorPartKind.COLUMN: ("IfcColumn", "COLUMN"),
                  ElevatorPartKind.GIRT: ("IfcMember", "MEMBER"), ElevatorPartKind.GLASS: ("IfcPlate", "CURTAIN_PANEL"),
                  ElevatorPartKind.PANEL: ("IfcCovering", "CLADDING"),
                  ElevatorPartKind.CAR_GLASS: ("IfcBuildingElementPart", "USERDEFINED"),
                  ElevatorPartKind.LANDING_DOOR: ("IfcDoor", "DOOR"), ElevatorPartKind.DOOR_FRAME: ("IfcMember", "USERDEFINED"),
                  ElevatorPartKind.SPIDER: ("IfcDiscreteAccessory", "BRACKET"), ElevatorPartKind.LADDER: ("IfcMember", "USERDEFINED"),
                  ElevatorPartKind.CALL_PANEL: ("IfcUnitaryControlElement", "CONTROLPANEL"),
                  ElevatorPartKind.CALL_BUTTON: ("IfcSwitchingDevice", "MOMENTARYSWITCH"),
                  ElevatorPartKind.INDICATOR: ("IfcUnitaryControlElement", "INDICATORPANEL")}

    def export_elevators(self, elevator_engine: ElevatorEngine):
        """엘리베이터: IfcElementAssembly(USERDEFINED: ELEVATOR) 가 승강로 벽(IfcWall)·피트 슬래브(IfcSlab BASESLAB)·
        승강로 천장 슬래브(IfcSlab ROOF)와 카(IfcTransportElement ELEVATOR ⊃ 바닥·벽·천장 IfcBuildingElementPart + 문 IfcDoor)를 묶고,
        IfcElementAssembly 만 최하 정지층 storey 에 포함. 정지층 출입구는 IfcOpeningElement(ELEVATOR_DOOR)로 승강로 벽에 연결.
        형상 = 상자 띠마다 닫힌 면 집합(세계 좌표, 곡선 선형에서도 본체 슬래브 오프닝과 같은 곡면)"""
        cfg = self.config
        for ev in elevator_engine.elevators:
            asm = self.file.create_entity(
                "IfcElementAssembly", GlobalId=ifcopenshell.guid.compress(uuid.UUID(ev.guid).hex), Name=ev.name,
                Description=f"엘리베이터 {cfg.station.level_name(ev.lower_floor)} ~ {cfg.station.level_name(ev.upper_floor)}"
                            + (" (승강장 위)" if ev.on_platform else ""),
                ObjectType="ELEVATOR", ObjectPlacement=self._placement(), PredefinedType="USERDEFINED")
            car = self.file.create_entity(
                "IfcTransportElement", GlobalId=ifcopenshell.guid.new(), Name=f"{ev.name}_CAR",
                Description=f"카 ({cfg.station.level_name(ev.car_floor)} 정지)", ObjectType="ELEVATOR_CAR",
                ObjectPlacement=self._placement(), PredefinedType="ELEVATOR")
            shaft_parts, car_parts, walls = [car], [], {}
            for e in ev.elements:
                entity, predefined = self._EV_ENTITY[e.kind]
                items = [self._face_set(part.solid.faces()) if part.solid is not None else self._face_set(fs)
                         for part in e.parts for fs in ([None] if part.solid is not None else part_faces(cfg, part))]
                el = self.file.create_entity(
                    entity, GlobalId=ifcopenshell.guid.compress(uuid.UUID(e.guid).hex), Name=e.name, ObjectType=e.type_name,
                    ObjectPlacement=self._placement(), Representation=self._product_shape(items, "Tessellation"),
                    PredefinedType=predefined)
                if e.material:
                    self._assign_material(el, e.material)
                (car_parts if e.kind.is_car else shaft_parts).append(el)
                if e.kind == ElevatorPartKind.HOIST_WALL:
                    walls[e.code] = el
            for name, code, _, (s0, s1, t0, t1), z0, z1 in ev.door_openings:
                if code not in walls:                          # 투시형: 유리는 문 자리를 비워 만듦 (뚫을 벽 없음)
                    continue
                box = SimpleNamespace(t_range=(t0, t1), shape=StripShape(
                    strips=[Strip(s0, s1, z0, z0, z1, PM.curve_factor(cfg, s0, s1, (t0 + t1) / 2.0))], width=t1 - t0))
                op = self.file.create_entity(
                    "IfcOpeningElement", GlobalId=ifcopenshell.guid.new(), Name=f"OPEN_{name}", Description="엘리베이터 출입구",
                    ObjectType="ELEVATOR_DOOR", ObjectPlacement=self._placement(),
                    Representation=self._product_shape([self._face_set(fs) for fs in part_faces(cfg, box)], "Tessellation"),
                    PredefinedType="OPENING")
                self.file.create_entity("IfcRelVoidsElement", GlobalId=ifcopenshell.guid.new(),
                                        RelatingBuildingElement=walls[code], RelatedOpeningElement=op)
            self.file.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=car, RelatedObjects=car_parts)
            self.file.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=asm, RelatedObjects=shaft_parts)
            self.file.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                                    RelatingStructure=self.storeys[ev.level], RelatedElements=[asm])

    def export_rooms(self, room_engine: RoomEngine):
        """실: 층마다 IfcSpace(INTERNAL, LongName = 용도)를 IfcRelAggregates 로 IfcBuildingStorey 에 넣고(공간 분할),
        칸막이벽·구획분리 벽은 IfcWall(PARTITIONING, Description = 종류), 두께 없는 구획분리선은 IfcVirtualElement(바닥 높이의
        Axis 곡선)로 그 층 storey 에 포함. 형상 = 조각마다 닫힌 면 집합(세계 좌표)"""
        cfg = self.config
        by_level: dict = {}
        wall_ents: dict = {}
        self._space_ents = {}
        for r in room_engine.rooms:
            items = [self._face_set(PM.sweep_quads(PM.rings(cfg, p))) for p in r.pieces]   # 바깥 방향 면
            space = self.file.create_entity(
                "IfcSpace", GlobalId=ifcopenshell.guid.compress(uuid.UUID(r.guid).hex), Name=r.name, LongName=r.use,
                Description=f"{r.level} {r.use} ({r.area:.2f} m2)" + (" — 기본 실" if r.is_default else ""),
                ObjectType=r.use, ObjectPlacement=self._placement(),
                Representation=self._product_shape(items, "Tessellation"), CompositionType="ELEMENT", PredefinedType="INTERNAL")
            by_level.setdefault(r.level, ([], []))[0].append(space)
            self._space_ents[r.name] = space
        for pw in room_engine.partitions:
            items = [self._face_set(PM.sweep_quads(PM.rings(cfg, p))) for p in pw.pieces]
            wall = self.file.create_entity(
                "IfcWall", GlobalId=ifcopenshell.guid.compress(uuid.UUID(pw.guid).hex), Name=pw.name,
                Description=pw.family_name, ObjectType=f"{pw.family_name} {pw.type_name}",
                ObjectPlacement=self._placement(), Representation=self._product_shape(items, "Tessellation"),
                PredefinedType="PARTITIONING")
            if pw.material:
                self._assign_material(wall, pw.material)
            by_level.setdefault(pw.level, ([], []))[1].append(wall)
            wall_ents[pw.name] = wall
        for d in room_engine.doors:                       # 문: 벽 개구부(Voids) + 닫힌 문 IfcDoor(문틀·문짝·손잡이, Fills)
            op = self.file.create_entity(
                "IfcOpeningElement", GlobalId=ifcopenshell.guid.new(), Name=f"OPEN_{d.name}", Description="실 출입문 개구부",
                ObjectType="DOOR", ObjectPlacement=self._placement(),
                Representation=self._product_shape([self._face_set(PM.sweep_quads(PM.rings(cfg, d.opening)))], "Tessellation"),
                PredefinedType="OPENING")
            self.file.create_entity("IfcRelVoidsElement", GlobalId=ifcopenshell.guid.new(),
                                    RelatingBuildingElement=wall_ents[d.wall], RelatedOpeningElement=op)
            door = self.file.create_entity(
                "IfcDoor", GlobalId=ifcopenshell.guid.compress(uuid.UUID(d.guid).hex), Name=d.name,
                Description=f"{d.room} 출입문 ({d.kind})", ObjectType=d.type_name, ObjectPlacement=self._placement(),
                Representation=self._product_shape([self._face_set(PM.sweep_quads(PM.rings(cfg, p.piece))) for p in d.parts], "Tessellation"),
                OverallHeight=float(d.height), OverallWidth=float(d.width), PredefinedType="DOOR",
                OperationType=d.operation)
            if d.material:
                self._assign_material(door, d.material)
            self.file.create_entity("IfcRelFillsElement", GlobalId=ifcopenshell.guid.new(),
                                    RelatingOpeningElement=op, RelatedBuildingElement=door)
            by_level.setdefault(d.level, ([], []))[1].append(door)
        for sl in room_engine.separations:                 # 두께 없는 구획분리 = IfcVirtualElement (바닥 높이의 선)
            s0, s1, t0, t1 = sl.rect
            ss = cfg.sample_s(s0, s1) if s1 - s0 > 1e-9 else [s0, s0]
            ts = [t0, t1] if s1 - s0 <= 1e-9 else [t0] * len(ss)
            off = cfg.station.offset
            pts = [self.file.create_entity("IfcCartesianPoint", Coordinates=(
                *[float(v) for v in cfg.to_world(s, t)], float(cfg.lv(s) - off + sl.z_rel))) for s, t in zip(ss, ts)]
            rep = self.file.create_entity(
                "IfcShapeRepresentation", ContextOfItems=self.file.by_type("IfcGeometricRepresentationContext")[0],
                RepresentationIdentifier="Axis", RepresentationType="Curve3D",
                Items=[self.file.create_entity("IfcPolyline", Points=pts)])
            ve = self.file.create_entity(
                "IfcVirtualElement", GlobalId=ifcopenshell.guid.compress(uuid.UUID(sl.guid).hex), Name=sl.name,
                Description="구획분리선 (가상 경계)", ObjectType="SPACE_SEPARATION", ObjectPlacement=self._placement(),
                Representation=self.file.create_entity("IfcProductDefinitionShape", Representations=[rep]))
            by_level.setdefault(sl.level, ([], []))[1].append(ve)
        for level, (spaces, walls) in by_level.items():
            if spaces:
                self.file.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(),
                                        RelatingObject=self.storeys[level], RelatedObjects=spaces)
            if walls:
                self.file.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                                        RelatingStructure=self.storeys[level], RelatedElements=walls)

    def _tri_set(self, faces_list):
        """조각이 아주 많은 부재(천장틀·천장 기구)용: 조각들의 면을 삼각형으로 나눠 IfcTriangulatedFaceSet 하나로 (면마다 엔티티를 만들지 않아
        파일이 작고 빠름). faces_list = 조각마다 면 목록"""
        pts, tris = [], []
        for faces in faces_list:
            index = {}                                               # 조각끼리는 점을 나누지 않음 (맞닿은 조각의 모서리가 얽히지 않게)
            for face in faces:
                ids = []
                for p in face:
                    key = (round(p[0], 7), round(p[1], 7), round(p[2], 7))
                    if key not in index:
                        index[key] = len(pts) + 1
                        pts.append([float(c) for c in p])
                    ids.append(index[key])
                for i in range(1, len(ids) - 1):
                    if len({ids[0], ids[i], ids[i + 1]}) == 3:
                        tris.append((ids[0], ids[i], ids[i + 1]))
        coords = self.file.create_entity("IfcCartesianPointList3D", CoordList=pts)
        return self.file.create_entity("IfcTriangulatedFaceSet", Coordinates=coords, Closed=True, CoordIndex=tris)

    def _finish_faces(self, p):
        """마감 조각 면: 직선은 사각 면, 곡선은 비틀린 사각 면을 중심점 4분할 삼각형으로 (얇은 층이라 삼각형 분할 방향에 따른
        체적 차이가 상대적으로 커지는 것을 막음)"""
        quads = PM.sweep_quads(PM.rings(self.config, p))
        if self.config.align.is_straight:
            return quads
        return [tri for q in quads for tri in _fan(q)]

    _PASSAGE_FINISH = {"FLOOR": ("IfcCovering", "FLOORING"), "FILL": ("IfcCovering", "FLOORING"),
                       "WALL": ("IfcCovering", "CLADDING"), "SKIRT": ("IfcCovering", "SKIRTINGBOARD"),
                       "CEILING": ("IfcCovering", "CEILING"), "FRAME": ("IfcMember", "USERDEFINED")}

    def export_passage_finishes(self, engine):
        """출구통로 마감: 바닥 마감재·채움(IfcCovering FLOORING), 벽(CLADDING), 천장판(CEILING), 천장틀(IfcMember) — 면 집합,
        통로가 붙는 층 storey"""
        f = self.file
        by_level: dict = {}
        for e in engine.elements:
            entity, predefined = self._PASSAGE_FINISH[e.code]
            el = f.create_entity(
                entity, GlobalId=ifcopenshell.guid.compress(uuid.UUID(e.guid).hex), Name=e.name,
                Description=f"출구통로 {e.passage} {e.type_name}", ObjectType=e.type_name, ObjectPlacement=self._placement(),
                Representation=self._product_shape([self._face_set(p.faces()) for p in e.pieces], "Tessellation"),
                PredefinedType=predefined)
            if e.material:
                self._assign_material(el, e.material)
            by_level.setdefault(e.level, []).append(el)
        for level, els in by_level.items():
            f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                            RelatingStructure=self.storeys[level], RelatedElements=els)

    def export_finishes(self, finish_engine: FinishEngine):
        """마감: 실마다 바닥 마감재·채움(IfcCovering FLOORING), 벽·기둥·승강로 마감(CLADDING), 천장판(CEILING),
        천장틀(IfcMember). 마감은 IfcRelCoversSpaces 로 그 실(IfcSpace)에 연결하고, 모든 부재는 층 storey 에 포함.
        IfcSpace 에는 마감 속성 세트(SSBIM_SpaceFinish: 마감 종류·재질·마감 높이·벽 마감 두께·마감면 거리·이격·천장 높이)를 붙인다"""
        f = self.file
        spaces = getattr(self, "_space_ents", {})
        by_level: dict = {}
        for rf in finish_engine.rooms:
            covers = []
            for e in rf.elements:
                entity, predefined, label, _ = FINISH_KINDS[e.code]
                if e.code in ("FRAME", "CEILING"):
                    items = [self._tri_set([self._finish_faces(p) for p in e.pieces])]
                else:
                    items = [self._face_set(self._finish_faces(p)) for p in e.pieces] + [self._face_set(b.faces()) for b in e.boxes]
                el = f.create_entity(
                    entity, GlobalId=ifcopenshell.guid.compress(uuid.UUID(e.guid).hex), Name=e.name,
                    Description=f"{rf.room} {label}", ObjectType=e.type_name, ObjectPlacement=self._placement(),
                    Representation=self._product_shape(items, "Tessellation"), PredefinedType=predefined)
                if e.material:
                    self._assign_material(el, e.material)
                by_level.setdefault(rf.level, []).append(el)
                if entity == "IfcCovering":
                    covers.append(el)
            space = spaces.get(rf.room)
            if space is None:
                continue
            if covers:
                f.create_entity("IfcRelCoversSpaces", GlobalId=ifcopenshell.guid.new(), RelatingSpace=space, RelatedCoverings=covers)
            ft = rf.finish
            vals = [("FinishType", "IfcLabel", ft.name), ("FloorMaterial", "IfcLabel", ft.floor_material),
                    ("FloorFinishLevel", "IfcLengthMeasure", float(ft.ffl)), ("WallMaterial", "IfcLabel", ft.wall_material),
                    ("WallFinishThickness", "IfcLengthMeasure", float(ft.wall_t)),
                    ("WallFinishFace", "IfcLengthMeasure", float(ft.face)),          # 구조체 면 → 마감 표면
                    ("WallFinishGap", "IfcLengthMeasure", float(ft.wall_gap)),       # 마감재 뒷면 이격 (하지 공간)
                    ("PartitionFinishFace", "IfcLengthMeasure", float(ft.pface)),    # 칸막이벽 면 → 마감 표면
                    ("SkirtingMaterial", "IfcLabel", ft.skirt_material if ft.has_skirt else "없음"),
                    ("SkirtingHeight", "IfcLengthMeasure", float(ft.skirt_h if ft.has_skirt else 0.0)),
                    ("CeilingMaterial", "IfcLabel", ft.ceiling_material if ft.ceiling else "없음"),
                    ("CeilingHeight", "IfcLengthMeasure", float(ft.ceiling_h if ft.ceiling else 0.0)),
                    ("CeilingFrame", "IfcLabel", f"{ft.frame}바" if ft.ceiling else "없음")]
            props = [f.create_entity("IfcPropertySingleValue", Name=n, NominalValue=f.create_entity(t, v)) for n, t, v in vals]
            pset = f.create_entity("IfcPropertySet", GlobalId=ifcopenshell.guid.new(), Name="SSBIM_SpaceFinish", HasProperties=props)
            f.create_entity("IfcRelDefinesByProperties", GlobalId=ifcopenshell.guid.new(), RelatedObjects=[space],
                            RelatingPropertyDefinition=pset)
        for level, els in by_level.items():
            f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                            RelatingStructure=self.storeys[level], RelatedElements=els)

    def export_tactiles(self, tactile_engine):
        """점자블록: 층·종류(점형/선형)마다 IfcCovering(FLOORING, ObjectType = 점자블록 점형|선형), 재질, 층 storey 에 포함.
        형상은 마감과 같은 면 집합 (곡선은 중심점 4분할 삼각형)"""
        f = self.file
        by_level: dict = {}
        for e in tactile_engine.elements:
            items = [self._face_set(self._finish_faces(p)) for p in e.pieces]
            el = f.create_entity(
                "IfcCovering", GlobalId=ifcopenshell.guid.compress(uuid.UUID(e.guid).hex), Name=e.name,
                Description=f"{e.level} {e.material} ({len(e.pieces)}조각, {e.area:.2f}m²)", ObjectType=e.material,
                ObjectPlacement=self._placement(), Representation=self._product_shape(items, "Tessellation"),
                PredefinedType="FLOORING")
            self._assign_material(el, e.material)
            by_level.setdefault(e.level, []).append(el)
        for level, els in by_level.items():
            f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                            RelatingStructure=self.storeys[level], RelatedElements=els)

    def export_fixtures(self, engine):
        """천장 기구: 조명 = IfcLightFixture(DIRECTIONSOURCE), 디퓨저 = IfcAirTerminal(DIFFUSER) — 몸체 + 면 면 집합, 층 storey"""
        f = self.file
        by_level: dict = {}
        for e in engine.elements:
            light = e.kind == "LIGHT"
            el = f.create_entity(
                "IfcLightFixture" if light else "IfcAirTerminal", GlobalId=ifcopenshell.guid.compress(uuid.UUID(e.guid).hex), Name=e.name,
                Description=f"{e.room} {e.type_name}", ObjectType=e.type_name, ObjectPlacement=self._placement(),
                Representation=self._product_shape([self._tri_set([p.faces() if hasattr(p, "faces") else self._finish_faces(p)])
                                                    for p in (e.body, e.face)], "Tessellation"),
                PredefinedType="DIRECTIONSOURCE" if light else "DIFFUSER")
            by_level.setdefault((e.level, e.material), []).append(el)
        for (level, material), els in by_level.items():
            f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                            RelatingStructure=self.storeys[level], RelatedElements=els)
            for el in els:
                self._assign_material(el, material)

    def export_props(self, engine):
        """배치 객체(비품): 종류마다 IfcFurniture · IfcElectricAppliance · IfcFireSuppressionTerminal · IfcBuildingElementProxy (조각마다 면 집합),
        층 storey, Pset SSBIM_Prop (종류·입력 값)"""
        from props.prop_kinds import KINDS
        f = self.file
        by_level: dict = {}
        for e in engine.elements:
            entity, pre = KINDS[e.kind].ifc
            el = f.create_entity(
                entity, GlobalId=ifcopenshell.guid.compress(uuid.UUID(e.guid).hex), Name=e.name, Description=f"비품 {e.type_name}",
                ObjectType=e.kind, ObjectPlacement=self._placement(),
                Representation=self._product_shape(
                    [self._tri_set([list(tris.tolist())]) for _, tris in engine.model_faces(e) if len(tris)] if e.detail
                    else [self._face_set(engine.part_faces(e, p)) for p in e.parts], "Tessellation"),
                PredefinedType=pre)
            if e.material:
                self._assign_material(el, e.material)
            vals = [("Kind", e.type_name)] + ([("Model", e.model)] if e.model else []) + [(x.label, e.values[x.key]) for x in KINDS[e.kind].fields]
            props = [f.create_entity("IfcPropertySingleValue", Name=n, NominalValue=f.create_entity("IfcLabel", v) if isinstance(v, str)
                                     else f.create_entity("IfcReal", float(v))) for n, v in vals]
            pset = f.create_entity("IfcPropertySet", GlobalId=ifcopenshell.guid.new(), Name="SSBIM_Prop", HasProperties=props)
            f.create_entity("IfcRelDefinesByProperties", GlobalId=ifcopenshell.guid.new(), RelatedObjects=[el], RelatingPropertyDefinition=pset)
            by_level.setdefault(e.level, []).append(el)
        for level, els in by_level.items():
            f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                            RelatingStructure=self.storeys[level], RelatedElements=els)

    def export_psds(self, psd_engine):
        """스크린도어: 선로마다 IfcElementAssembly(USERDEFINED: PLATFORM_SCREEN_DOOR) ⊃ POST(IfcColumn), 구동부(IfcMember
        USERDEFINED PSD_HEADER), 가동문(IfcDoor SLIDING_TO_LEFT/RIGHT), 비상문 겸용 고정부(IfcDoor SINGLE_SWING), 고정부·채움 패널
        (IfcPlate CURTAIN_PANEL). 형상 = 조각(프레임 + 유리) 면 집합, 최하층 storey"""
        f = self.file
        if not psd_engine.elements:
            return
        level = psd_engine.elements[0].level
        asms = []
        for track in sorted({e.track for e in psd_engine.elements}):
            asm = f.create_entity("IfcElementAssembly", GlobalId=ifcopenshell.guid.new(), Name=f"PSD_{track}",
                                  Description=f"스크린도어 ({track} 선로)", ObjectType="PLATFORM_SCREEN_DOOR",
                                  ObjectPlacement=self._placement(), PredefinedType="USERDEFINED")
            parts = []
            for e in (e for e in psd_engine.elements if e.track == track):
                kw = dict(GlobalId=ifcopenshell.guid.compress(uuid.UUID(e.guid).hex), Name=e.name, ObjectType=e.type_name,
                          Description=f"스크린도어 {e.type_name}" + (f" (유닛 {e.unit})" if e.unit else ""),
                          ObjectPlacement=self._placement(),
                          Representation=self._product_shape([self._face_set(self._finish_faces(p)) for p in e.pieces],
                                                             "Tessellation"))
                s0, s1 = e.s_range
                if e.kind == "POST":
                    el = f.create_entity("IfcColumn", PredefinedType="COLUMN", **kw)
                elif e.kind == "HEADER":
                    kw["ObjectType"] = "PSD_HEADER"
                    el = f.create_entity("IfcMember", PredefinedType="USERDEFINED", **kw)
                elif e.kind in ("DOOR", "EMERGENCY"):
                    op = ("SLIDING_TO_LEFT" if e.name.endswith("_N") else "SLIDING_TO_RIGHT") if e.kind == "DOOR" else "SINGLE_SWING_LEFT"
                    el = f.create_entity("IfcDoor", PredefinedType="DOOR", OperationType=op, OverallWidth=float(s1 - s0),
                                         OverallHeight=float(e.height), **kw)
                else:
                    el = f.create_entity("IfcPlate", PredefinedType="CURTAIN_PANEL", **kw)
                self._assign_material(el, e.material)
                parts.append(el)
            f.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=asm, RelatedObjects=parts)
            asms.append(asm)
        f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                        RelatingStructure=self.storeys[level], RelatedElements=asms)

    def export_railings(self, railing_engine):
        """오프닝 유리난간: 난간마다 IfcRailing(GUARDRAIL) ⊃ 경계석 IfcBuildingElementPart(USERDEFINED CURB) · POST IfcMember(POST)
        · 레일 IfcMember(USERDEFINED HANDRAIL) · 유리 IfcPlate(CURTAIN_PANEL). 형상 = 조각 면 집합, 난간이 서는 층 storey"""
        f = self.file
        by_level: dict = {}
        for r in railing_engine.railings:
            rail = f.create_entity("IfcRailing", GlobalId=ifcopenshell.guid.compress(uuid.UUID(r.guid).hex), Name=r.name,
                                   Description=f"오프닝 {r.opening} 유리난간 ({', '.join(r.edges)})", ObjectType=r.type_name,
                                   ObjectPlacement=self._placement(), PredefinedType="GUARDRAIL")
            parts = []
            for e in r.parts:
                kw = dict(GlobalId=ifcopenshell.guid.compress(uuid.UUID(e.guid).hex), Name=e.name, ObjectType=e.type_name,
                          ObjectPlacement=self._placement(),
                          Representation=self._product_shape([self._face_set(self._finish_faces(p)) for p in e.pieces],
                                                             "Tessellation"))
                if e.code in ("CURB", "SKIRT", "CORE"):
                    kw["ObjectType"] = {"CURB": "CURB_PLATE", "SKIRT": "CURB_SKIRTING", "CORE": "CURB_CORE"}[e.code]
                    el = f.create_entity("IfcBuildingElementPart", PredefinedType="USERDEFINED", **kw)
                elif e.code == "POST":
                    el = f.create_entity("IfcMember", PredefinedType="POST", **kw)
                elif e.code == "RAIL":
                    kw["ObjectType"] = "HANDRAIL"
                    el = f.create_entity("IfcMember", PredefinedType="USERDEFINED", **kw)
                else:
                    el = f.create_entity("IfcPlate", PredefinedType="CURTAIN_PANEL", **kw)
                self._assign_material(el, e.material)
                parts.append(el)
            f.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=rail, RelatedObjects=parts)
            by_level.setdefault(r.level, []).append(rail)
        for level, els in by_level.items():
            f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                            RelatingStructure=self.storeys[level], RelatedElements=els)

    def export_smoke_barriers(self, smoke_engine):
        """제연경계벽: 경계벽마다 IfcCurtainWall(USERDEFINED SMOKE_BARRIER) ⊃ 프레임 IfcMember(USERDEFINED FRAME)·유리 IfcPlate,
        매달린 층 storey"""
        f = self.file
        by_level: dict = {}
        for b in smoke_engine.barriers:
            wall = f.create_entity("IfcCurtainWall", GlobalId=ifcopenshell.guid.compress(uuid.UUID(b.guid).hex), Name=b.name,
                                   Description=f"오프닝 {b.opening} 입구 천장 제연경계벽", ObjectType="SMOKE_BARRIER",
                                   ObjectPlacement=self._placement(), PredefinedType="USERDEFINED")
            parts = []
            for e in b.parts:
                kw = dict(GlobalId=ifcopenshell.guid.compress(uuid.UUID(e.guid).hex), Name=e.name, ObjectType=e.type_name,
                          ObjectPlacement=self._placement(),
                          Representation=self._product_shape([self._face_set(self._finish_faces(p)) for p in e.pieces],
                                                             "Tessellation"))
                if e.code == "GLASS":
                    el = f.create_entity("IfcPlate", PredefinedType="CURTAIN_PANEL", **kw)
                else:
                    kw["ObjectType"] = "FRAME"
                    el = f.create_entity("IfcMember", PredefinedType="USERDEFINED", **kw)
                self._assign_material(el, e.material)
                parts.append(el)
            f.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=wall, RelatedObjects=parts)
            by_level.setdefault(b.level, []).append(wall)
        for level, els in by_level.items():
            f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                            RelatingStructure=self.storeys[level], RelatedElements=els)

    def export_signs(self, sign_engine):
        """역명판·안내사인: 사인마다 IfcBuildingElementProxy(USERDEFINED, ObjectType SIGNAGE) — 본체 + 이미지 면, 재질,
        속성 세트 SSBIM_Sign(종류·문구), 그 층 storey"""
        f = self.file
        by_level: dict = {}
        for e in sign_engine.elements:
            el = f.create_entity(
                "IfcBuildingElementProxy", GlobalId=ifcopenshell.guid.compress(uuid.UUID(e.guid).hex), Name=e.name,
                Description=e.text, ObjectType="SIGNAGE", ObjectPlacement=self._placement(),
                Representation=self._product_shape([self._face_set(self._finish_faces(p)) for p in e.pieces], "Tessellation"),
                PredefinedType="USERDEFINED")
            self._assign_material(el, e.material)
            props = [f.create_entity("IfcPropertySingleValue", Name=n, NominalValue=f.create_entity("IfcLabel", v))
                     for n, v in (("Kind", e.type_name), ("Text", e.text))]
            pset = f.create_entity("IfcPropertySet", GlobalId=ifcopenshell.guid.new(), Name="SSBIM_Sign", HasProperties=props)
            f.create_entity("IfcRelDefinesByProperties", GlobalId=ifcopenshell.guid.new(), RelatedObjects=[el],
                            RelatingPropertyDefinition=pset)
            by_level.setdefault(e.level, []).append(el)
        for level, els in by_level.items():
            f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                            RelatingStructure=self.storeys[level], RelatedElements=els)

    _VENT_ENTITY = {VentPartKind.FLOOR: ("IfcSlab", "FLOOR"), VentPartKind.ROOF: ("IfcSlab", "ROOF"),
                    VentPartKind.WALL: ("IfcWall", "SOLIDWALL"), VentPartKind.MID_WALL: ("IfcWall", "SOLIDWALL"),
                    VentPartKind.END_WALL: ("IfcWall", "SOLIDWALL"), VentPartKind.SHAFT_WALL: ("IfcWall", "SOLIDWALL"),
                    VentPartKind.GRILL: ("IfcAirTerminal", "GRILLE")}

    def export_vents(self, vent_engine: VentEngine):
        """환기구: IfcElementAssembly(USERDEFINED: VENTILATION) 가 덕트 바닥·천장(IfcSlab), 바깥 벽·중벽·끝 벽·수직구 벽(IfcWall),
        칸별 금속 그릴(IfcAirTerminal GRILLE)을 묶고, IfcElementAssembly 만 환기구가 붙는 층 storey 에 포함.
        형상 = 조각마다 곧은 압출(세계 좌표), 연귀 조각이 있는 부재는 면 집합"""
        by_storey: dict = {}
        for vt in vent_engine.vents:
            asm = self.file.create_entity(
                "IfcElementAssembly", GlobalId=ifcopenshell.guid.compress(uuid.UUID(vt.guid).hex), Name=vt.name,
                Description=f"{vt.level} 환기구 ({vt.cells}련, 수직구 {len(vt.shafts)}곳, 그릴 {len(vt.grills)}개)",
                ObjectType="VENTILATION", ObjectPlacement=self._placement(), PredefinedType="USERDEFINED")
            parts = []
            for e in vt.elements + vt.grills:
                entity, predefined = self._VENT_ENTITY[e.kind]
                if any(q.skewed for q in e.pieces):
                    items, rep = [self._face_set(q.faces()) for q in e.pieces], "Tessellation"
                else:
                    items = [self._box_piece_solid(q, f"Vent{e.kind.value.title()}Profile") for q in e.pieces]
                    rep = "SweptSolid"
                el = self.file.create_entity(
                    entity, GlobalId=ifcopenshell.guid.compress(uuid.UUID(e.guid).hex), Name=e.name,
                    ObjectType=e.type_name, ObjectPlacement=self._placement(),
                    Representation=self._product_shape(items, rep), PredefinedType=predefined)
                if e.material:
                    self._assign_material(el, e.material)
                parts.append(el)
            self.file.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=asm, RelatedObjects=parts)
            by_storey.setdefault(vt.level, []).append(asm)
        for level, elements in by_storey.items():
            self.file.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                                    RelatingStructure=self.storeys[level], RelatedElements=elements)

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