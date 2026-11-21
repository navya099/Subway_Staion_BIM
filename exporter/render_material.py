"""3D 보기용(텍스처) 재질 목록: 마감 재질 이름 / 레이어 → 색 + 텍스처 이미지.

텍스처 모델(COLLADA .dae, 스케치업 둘러보기용)에만 쓰고 2D 도면·IFC 에는 쓰지 않는다.
텍스처 이미지는 assets/image/tile/ 의 `{texture}.jpg|.jpeg|.png` (파일 이름 = 아래 texture 값). 이미지가 없으면 색만 쓴다.
size_u / size_v = 이미지 한 장이 덮는 실제 크기 (m): u = 이미지 가로(벽은 수평, 바닥·천장은 선형 진행방향),
v = 이미지 세로(벽은 위쪽, 바닥·천장은 선형 왼쪽 +t).
"""
from dataclasses import dataclass
from pathlib import Path

TEXTURE_DIR = Path(__file__).resolve().parent.parent / "assets" / "image" / "tile"
IMAGE_EXTS = (".jpg", ".jpeg", ".png")


@dataclass(frozen=True)
class RenderMaterial:
    name: str                           # 재질 이름 (스케치업 재질 이름)
    color: tuple = (0.8, 0.8, 0.8)      # RGB 0~1 (텍스처가 없을 때의 색)
    texture: str = ""                   # 텍스처 이미지 파일 이름(확장자 제외), "" = 텍스처 없음
    size_u: float = 1.0                 # 이미지 한 장의 실제 가로 (m)
    size_v: float = 1.0                 # 이미지 한 장의 실제 세로 (m)
    alpha: float = 1.0                  # 불투명도 (1 = 불투명, 유리는 작게)
    image: str = ""                     # 이미지 파일 경로 (생성 이미지 — texture 대신, 반복 없이 frame 에 한 장)
    frame: tuple = None                 # (왼쪽 아래 세계 좌표, 오른쪽 단위 벡터, 위쪽 단위 벡터, 폭, 높이, 구배) — 이미지 한 장을 면에 맞춤


# 마감 재질 이름 → 보기 재질. 텍스처: 벽 금속패널, 바닥 화강석, 천장 패널(알루미늄 천장판)
FINISH_MATERIALS = {m.name: m for m in (
    RenderMaterial("금속패널", (0.78, 0.79, 0.80), "metal_panel", 1.2, 0.6),
    RenderMaterial("화강석", (0.62, 0.60, 0.58), "granite", 0.6, 0.6),
    RenderMaterial("계단석", (0.74, 0.74, 0.73), "stair_stone", 0.6, 0.6),   # 디딤판 윗면은 한 장씩 맞춤 (face_frames)
    RenderMaterial("알루미늄 천장판", (0.93, 0.93, 0.92), "ceiling_panel", 0.6, 0.6),
    RenderMaterial("석재", (0.66, 0.64, 0.60)),
    RenderMaterial("타일", (0.90, 0.90, 0.88)),
    RenderMaterial("방수 천장판", (0.95, 0.95, 0.95)),
    RenderMaterial("액세스 플로어", (0.55, 0.57, 0.60)),
    RenderMaterial("몰탈", (0.70, 0.70, 0.68)),
    RenderMaterial("콘크리트", (0.72, 0.72, 0.70), "Polished Concrete New", 2.0, 2.0),
    RenderMaterial("논슬립", (0.22, 0.22, 0.24)),
    RenderMaterial("스테인리스", (0.78, 0.79, 0.80)),
    RenderMaterial("흑색 걸레받이", (0.10, 0.10, 0.11), "Skirting", 0.8, 0.2),
    RenderMaterial("콘크리트 면처리", (0.72, 0.72, 0.70), "Polished Concrete New", 2.0, 2.0),
    RenderMaterial("패널", (0.80, 0.80, 0.78)),
    RenderMaterial("점자블록 점형", (0.96, 0.80, 0.10), "tactile_warning", 0.3, 0.3),
    RenderMaterial("점자블록 선형", (0.96, 0.80, 0.10), "tactile_guide", 0.3, 0.3),
    RenderMaterial("승하차위치표시", (0.86, 0.40, 0.75), "tactile_boarding", 0.3, 0.3),
    RenderMaterial("M바 천장틀", (0.60, 0.60, 0.60)),
    RenderMaterial("T바 천장틀", (0.60, 0.60, 0.60)),
)}
FINISH_DEFAULT = (0.80, 0.80, 0.80)       # 목록에 없는 마감 재질

# 구조 부재 기본 재질 (벽·슬래브·승강장·기둥·계단·통로·출입구·환기구·승강로): 콘크리트 텍스처, 2m 한 장
CONCRETE = RenderMaterial("콘크리트", (0.72, 0.72, 0.70), "Polished Concrete New", 2.0, 2.0)
# 마감이 아닌 3D 레이어 → 보기 재질 (목록에 없는 레이어는 콘크리트)
LAYER_MATERIALS = {
    "STRUCT_ESCALATOR": RenderMaterial("에스컬레이터", (0.55, 0.57, 0.60)),
    "STRUCT_ELEVATOR_CAR": RenderMaterial("엘리베이터 카", (0.70, 0.72, 0.75)),
    "STRUCT_PARTITION": RenderMaterial("칸막이벽", (0.86, 0.85, 0.82)),
    "STRUCT_SEPARATION": RenderMaterial("구획분리 벽", (0.62, 0.74, 0.84)),
    "STRUCT_DOOR": RenderMaterial("문", (0.45, 0.50, 0.55)),
    "STRUCT_GRILL": RenderMaterial("그릴", (0.30, 0.30, 0.32)),
    "STRUCT_PSD": RenderMaterial("PSD 프레임", (0.42, 0.44, 0.47)),
    "STRUCT_SIGN": RenderMaterial("사인 본체", (0.30, 0.31, 0.33)),
    "STRUCT_SIGN_FACE": RenderMaterial("사인 면", (0.95, 0.95, 0.95)),
    "STRUCT_PSD_GLASS": RenderMaterial("PSD 유리", (0.70, 0.85, 0.92), alpha=0.3),
    "STRUCT_RAILING": RenderMaterial("스테인리스", (0.78, 0.79, 0.80)),
    "STRUCT_RAILING_GLASS": RenderMaterial("난간 유리", (0.59, 0.80, 0.75), alpha=0.35),
}


def railing_glass_material(rs) -> RenderMaterial:
    """유리난간 유리 보기 재질 — 설정 색(RGB 0~255)·불투명도"""
    r, g, b = (max(0, min(255, int(c))) / 255.0 for c in rs.glass_rgb)
    return RenderMaterial("난간 유리", (r, g, b), alpha=float(rs.glass_alpha))


def finish_material(name: str) -> RenderMaterial:
    """마감 재질 이름 → 보기 재질 (목록에 없으면 이름 그대로 기본 색)"""
    return FINISH_MATERIALS.get(name) or RenderMaterial(name or "마감", FINISH_DEFAULT)


def layer_material(layer: str) -> RenderMaterial:
    return LAYER_MATERIALS.get(layer, CONCRETE)


def find_image(texture: str, texture_dir=TEXTURE_DIR):
    """텍스처 이름 → 이미지 파일 경로 (없으면 None)"""
    if not texture:
        return None
    for ext in IMAGE_EXTS:
        p = Path(texture_dir) / f"{texture}{ext}"
        if p.is_file():
            return p
    return None
