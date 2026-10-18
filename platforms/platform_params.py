import dataclasses


@dataclasses.dataclass
class PlatformParameters:
    """승강장 파라메터
    Attributes:
        track_spacing: 선로 간격 D (m) [하선: -D/2, 상선: +D/2]
        plat_offset: 선로 중심 ~ 승강장 끝단 거리 (m)
        plat_thick: 승강장 슬래브 두께 (m, 표준 200mm)
        plat_height: 바닥 상단 기준 승강장 높이 (m)
        plat_type: 승강장 타입 섬식 상대식
    """
    # --- [신규 승강장 파래미터] ---
    track_spacing: float = 0.0  # 선로 간격 D (m) [하선: -D/2, 상선: +D/2]
    plat_offset: float = 0.0  # 선로 중심 ~ 승강장 끝단 거리 (m)
    plat_thick: float = 0.0  # 승강장 슬래브 두께 (m, 표준 200mm)
    plat_height: float = 0.0  # 바닥 상단 기준 승강장 높이 (m)
    plat_type: str = ""