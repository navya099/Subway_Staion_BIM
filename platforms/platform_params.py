import dataclasses


@dataclasses.dataclass
class PlatformParameters:
    # --- [신규 승강장 파래미터] ---
    track_spacing: float = 4.4  # 선로 간격 D (m) [하선: -D/2, 상선: +D/2]
    plat_offset: float = 1.7  # 선로 중심 ~ 승강장 끝단 거리 (m)
    plat_thick: float = 0.2  # 승강장 슬래브 두께 (m, 표준 200mm)
    plat_height: float = 1.1  # 바닥 상단 기준 승강장 높이 (m)