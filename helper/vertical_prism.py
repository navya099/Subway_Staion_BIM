"""연직 다각형 기둥 조각 (세계 좌표): 평면 다각형 × 표고 z0 ~ z1. 원형 강관 기둥 등 (엘리베이터 투시형 승강로).

모든 면이 평면이라 볼록 다면체(볼록 다각형일 때). 체적 = 평면 면적 × 높이.
"""
import math
from dataclasses import dataclass

from helper.box_piece import cut_faces_by_plane, polygon_area


def circle_points(cx: float, cy: float, r: float, n: int = 16) -> list:
    """외접 n 각형 (반지름 r 의 원을 감싸는 정다각형, 반시계)"""
    rr = r / math.cos(math.pi / n)
    return [(cx + rr * math.cos(2 * math.pi * (k + 0.5) / n), cy + rr * math.sin(2 * math.pi * (k + 0.5) / n)) for k in range(n)]


@dataclass
class VerticalPrism:
    """pts = 평면 다각형 [(x, y)] (세계 좌표, 반시계), z0 < z1 = 아래·위 표고 (절대)"""
    pts: list
    z0: float
    z1: float

    @property
    def area(self) -> float:
        return abs(polygon_area(self.pts))

    @property
    def volume(self) -> float:
        return self.area * (self.z1 - self.z0)

    @property
    def z_range(self) -> tuple:
        return self.z0, self.z1

    def faces(self) -> list:
        """닫힌 면 집합 (바깥 방향): 옆면 + 윗면 + 아랫면"""
        p = self.pts if polygon_area(self.pts) > 0 else list(reversed(self.pts))
        n = len(p)
        out = [((p[i][0], p[i][1], self.z0), (p[(i + 1) % n][0], p[(i + 1) % n][1], self.z0),
                (p[(i + 1) % n][0], p[(i + 1) % n][1], self.z1), (p[i][0], p[i][1], self.z1)) for i in range(n)]
        out.append(tuple((x, y, self.z1) for x, y in p))
        out.append(tuple((x, y, self.z0) for x, y in reversed(p)))
        return out

    def cut_by_plane(self, px: float, py: float, nx: float, ny: float):
        """연직 평면과의 단면 다각형 [(w, z)] 또는 None (BoxPiece.cut_by_plane 과 같은 w)"""
        return cut_faces_by_plane(self.faces(), px, py, nx, ny)
