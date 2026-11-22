"""평면 사다리꼴 각기둥 조각 (출입구 바깥면 사선 전이 쐐기).

출입구 좌표 (u, t, z) 에서 u0 ~ u1 구간, t 범위가 끝마다 (ta0, tb0) → (ta1, tb1) 로 직선 변화, 하면 zb0 → zb1 · 상면 zt0 → zt1 직선.
하면·상면은 t 와 무관해 평면, 측면은 연직 평면이라 모든 면이 평면인 볼록 다면체 (한쪽 끝 폭 0 이면 삼각 기둥).
세계 좌표 = 출입구 좌표계 (ox, oy, ux, uy) — BoxPiece 와 같이 dataclasses.replace(ox=0, oy=0, ux=1, uy=0) 로 출입구 좌표 면을 얻음.
"""
from dataclasses import dataclass

from helper.box_piece import cut_faces_by_plane
from helper.strip_member import _degenerate_faces


@dataclass
class TaperPiece:
    ox: float
    oy: float
    ux: float
    uy: float
    u0: float
    u1: float
    ta0: float
    tb0: float
    ta1: float
    tb1: float
    zb0: float
    zb1: float
    zt0: float
    zt1: float

    def _w(self, u: float, t: float) -> tuple[float, float]:
        return self.ox + u * self.ux - t * self.uy, self.oy + u * self.uy + t * self.ux

    def rings(self) -> list:
        out = []
        for u, ta, tb, zb, zt in ((self.u0, self.ta0, self.tb0, self.zb0, self.zt0), (self.u1, self.ta1, self.tb1, self.zb1, self.zt1)):
            (xa, ya), (xb, yb) = self._w(u, ta), self._w(u, tb)
            out.append([(xa, ya, zb), (xb, yb, zb), (xb, yb, zt), (xa, ya, zt)])
        return out

    def faces(self) -> list[tuple]:
        """닫힌 면 집합 (바깥 방향, 폭 0 인 끝은 삼각형)"""
        return _degenerate_faces(self.rings())

    @property
    def volume(self) -> float:
        """∫ 폭(u)·높이(u) du — 둘 다 u 에 선형"""
        w0, w1 = self.tb0 - self.ta0, self.tb1 - self.ta1
        h0, h1 = self.zt0 - self.zb0, self.zt1 - self.zb1
        return (self.u1 - self.u0) * (2 * w0 * h0 + w0 * h1 + w1 * h0 + 2 * w1 * h1) / 6.0

    def cut_by_plane(self, px: float, py: float, nx: float, ny: float):
        return cut_faces_by_plane(self.faces(), px, py, nx, ny)
