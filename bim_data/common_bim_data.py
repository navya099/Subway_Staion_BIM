from dataclasses import dataclass, field
from typing import Any, Optional
import uuid


@dataclass
class CommonBIMData:
    """
    모든 BIM 객체가 공유하는 공통 속성 추상 클래스
    Attributes:
        guid: BIM 고유 글로벌 ID
        name: 객체 이름
        family_name: 라이브러리/패밀리 명 (예: "콘크리트-직사각형 기둥")
        type_name: # 타입/규격 명 (예: "600x600mm")
        level: 설치 레벨/층 (예: "1F", "B1")
        pos_x: 중심점 X 좌표
        pos_y: 중심점 Y 좌표
        pos_z: 중심점 Z 좌표 (고도)
        rotation: 배치 회전 각도
        material: 주요 자재/재질
        cost: 자재 단가
        source_element: 원본 3D 객체 바인딩
    """
    # 1. 식별 및 추적 정보
    guid: str = field(default_factory=lambda: str(uuid.uuid4()))  # BIM 고유 글로벌 ID (Revit UniqueId 또는 IFC GUID)
    name: str = ''  # 객체 이름 (예: "C1", "W1")
    family_name: str = ''  # 라이브러리/패밀리 명 (예: "콘크리트-직사각형 기둥")
    type_name: str = ''  # 타입/규격 명 (예: "600x600mm")

    # 2. 위치 및 공간 정보
    level: str = ''  # 설치 레벨/층 (예: "1F", "B1")
    pos_x: float = 0.0  # 중심점 X 좌표
    pos_y: float = 0.0  # 중심점 Y 좌표
    pos_z: float = 0.0  # 중심점 Z 좌표 (고도)
    rotation: float = 0.0  # 배치 회전 각도 (선형 방위각)

    # 3. 비기하학적/관리 속성
    material: str = ''  # 주요 자재/재질 (예: "Concrete_C24")
    cost: float = 0.0  # 자재 단가

    # 4. 원본 3D 객체 바인딩 (Revit API Element 또는 IfcProduct 등)
    source_element: Optional[Any] = None
