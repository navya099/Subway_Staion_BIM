from dataclasses import dataclass, field

from shapes.base_shape import BaseShape


@dataclass
class StairStrip:
    """계단 부재를 s 방향으로 자른 띠 1개: s0 ~ s1 구간에서 상면은 수평(zt), 하면은 zb0 → zb1 직선.
    표고는 절대 표고 (계단 디딤판은 종단구배와 관계없이 수평). curve_factor = 곡선 체적 보정 (직선 1.0)"""
    s0: float
    s1: float
    zb0: float
    zb1: float
    zt: float
    curve_factor: float = 1.0

    def zb_at(self, s: float) -> float:
        if self.s1 - self.s0 <= 0:
            return self.zb0
        return self.zb0 + (self.zb1 - self.zb0) * (s - self.s0) / (self.s1 - self.s0)

    @property
    def area(self) -> float:
        """s–z 단면적"""
        return (self.s1 - self.s0) * (2.0 * self.zt - self.zb0 - self.zb1) / 2.0


@dataclass
class StairPartShape(BaseShape):
    """계단 런 / 계단참 형상: 띠(StairStrip)들을 s 순서로 이은 단면을 t 방향 width 만큼 편 각기둥.
    Attributes:
        strips: s 오름차순, 서로 맞닿고 겹치지 않음
        width: t 방향 폭 (m)
    """
    strips: list = field(default_factory=list)
    width: float = 0.0

    @property
    def length(self) -> float:
        return self.strips[-1].s1 - self.strips[0].s0 if self.strips else 0.0

    @property
    def volume(self) -> float:
        return sum(st.area * self.width * st.curve_factor for st in self.strips)

    def profile_points(self) -> list[tuple[float, float]]:
        """(s, z) 단면 외곽 다각형 (반시계): 하면을 s 증가 방향으로, 상면(계단 모양)을 s 감소 방향으로"""
        bottom, top = [], []
        for st in self.strips:
            bottom += [(st.s0, st.zb0), (st.s1, st.zb1)]
            top += [(st.s0, st.zt), (st.s1, st.zt)]
        pts = bottom + list(reversed(top))
        out = []
        for p in pts:                                      # 연속 중복점 제거
            if not out or abs(p[0] - out[-1][0]) > 1e-9 or abs(p[1] - out[-1][1]) > 1e-9:
                out.append(p)
        if len(out) > 1 and abs(out[0][0] - out[-1][0]) < 1e-9 and abs(out[0][1] - out[-1][1]) < 1e-9:
            out.pop()
        return out
