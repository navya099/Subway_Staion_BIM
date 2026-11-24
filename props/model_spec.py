"""비품에 쓰는 외부 3D 모델 등록: 파일(경로만)·단위·위쪽 축·돌림·배율 → 객체 좌표(앞 +x, 왼쪽 +y, 위 +z, m) 의 삼각형.

돌림 0 = glTF 규약(위 Y, 앞 +Z) 또는 위 Z 파일의 앞 = −Y 가 객체의 앞(+x) 이 됨. 놓는 방식마다 기준점(바닥 중심·뒷면·천장)에 맞춰 옮긴다.
"""
import dataclasses
import math

import numpy as np

from props.model_file import load_model
from props.prop_kinds import CEILING, WALL

UNITS = {"m": 1.0, "cm": 0.01, "mm": 0.001, "inch": 0.0254, "ft": 0.3048}
UPS = ("Y", "Z")
MIN_SIZE, MAX_SIZE = 0.001, 30.0
DEFAULT_LIMIT = 5000                 # 3D DXF·IFC 에 실제 모양을 쓰는 면 수 한도 (넘으면 외곽 상자)


@dataclasses.dataclass
class PropModel:
    """외부 모델 1개. name: 비품이 고르는 이름, path: 파일 경로, angle: 위쪽 축 둘레 돌림(도), scale: 배율,
    size: 마지막으로 읽은 크기 (깊이 x, 폭 y, 높이 z) — 파일이 없을 때 '외부 모델' 을 상자로 만드는 데 씀"""
    name: str
    path: str
    unit: str = "m"
    up: str = "Y"
    angle: float = 0.0
    scale: float = 1.0
    size: tuple = None


def check_models(models, limit) -> None:
    names = [m.name.strip() for m in models]
    for m in models:
        w = f"비품 모델 {m.name.strip() or m.path}"
        if not m.name.strip():
            raise ValueError("비품 모델: 이름을 입력하세요")
        if m.unit not in UNITS:
            raise ValueError(f"{w}: 단위는 {', '.join(UNITS)} 중 하나여야 합니다 ({m.unit!r})")
        if m.up not in UPS:
            raise ValueError(f"{w}: 위쪽 축은 Y 또는 Z 여야 합니다 ({m.up!r})")
        if not m.scale > 0:
            raise ValueError(f"{w}: 배율은 0보다 커야 합니다 ({m.scale:g})")
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ValueError(f"비품 모델 이름이 중복됩니다: {', '.join(dup)}")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise ValueError(f"비품 모델 면 한도는 0 이상의 정수여야 합니다 ({limit!r})")


def model_mesh(m: PropModel) -> list:
    """객체 방향·m 로 바꾼 MeshPart 목록 (기준점은 옮기지 않음). 파일을 못 읽거나 크기가 이상하면 ValueError"""
    parts = load_model(m.path)
    k = UNITS[m.unit] * m.scale
    a = math.radians(m.angle) + math.pi / 2                           # 앞(−y) → +x
    c, s = math.cos(a), math.sin(a)
    up = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=float) if m.up == "Y" else np.eye(3)
    R = k * np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]]) @ up
    out = [dataclasses.replace(p, pos=p.pos @ R.T) for p in parts]
    sz = mesh_size(out)
    if max(sz) > MAX_SIZE or max(sz) < MIN_SIZE:
        raise ValueError(f"크기가 {sz[1]:.3g} × {sz[0]:.3g} × {sz[2]:.3g} m 입니다 — 단위·배율을 확인하세요")
    return out


def bounds(parts) -> tuple:
    lo = np.min([p.pos[np.unique(p.idx)].min(axis=0) for p in parts], axis=0)
    hi = np.max([p.pos[np.unique(p.idx)].max(axis=0) for p in parts], axis=0)
    return lo, hi


def mesh_size(parts) -> tuple:
    """(깊이 x, 폭 y, 높이 z)"""
    lo, hi = bounds(parts)
    return tuple(float(x) for x in hi - lo)


def placed_mesh(parts, mount: str, z: float = 0.0) -> list:
    """놓는 방식의 기준점으로 옮김: 바닥·매달림 = 평면 중심·아래 z / 벽 = 뒷면 x 0·아래 z / 천장 = 윗면 0"""
    lo, hi = bounds(parts)
    mid = (lo + hi) / 2.0
    d = np.array([-lo[0] if mount == WALL else -mid[0], -mid[1], -hi[2] if mount == CEILING else z - lo[2]])
    return [dataclasses.replace(p, pos=p.pos + d) for p in parts]


def triangle_count(parts) -> int:
    return sum(len(p.idx) for p in parts)
