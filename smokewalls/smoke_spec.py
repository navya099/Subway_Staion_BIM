"""계단·에스컬레이터 입구 천장 제연경계벽 제원 (모든 계단·ESC 공통).

실무: 계단·ESC 가 올라가는 오프닝의 입구 쪽(오르기 시작하는 쪽) 가장자리 천장에서 아래로 유리 제연경계벽을 내림.
오프닝 옆은 계단 옆 벽체가 막으므로 입구 쪽만 (사용자 지정). 위·아래 프레임 + 유리판, 유리 색은 유리난간처럼 RGB.
"""
import dataclasses


@dataclasses.dataclass
class SmokeBarrierSettings:
    """제연경계벽. enabled: 생성 여부 (모델 기본 끔, GUI 켬)
    depth: 천장(천장판 하면, 천장이 없으면 위 슬래브 하면) 아래로 내려오는 깊이 — 켜면 계단·ESC 자동 오프닝을 이만큼
           늘려 경계벽 아래에서도 머리 높이를 확보
    frame_h / frame_d: 위·아래 프레임 높이 / 두께(진행방향), glass_t: 유리 두께, glass_rgb (0~255)·glass_alpha: 보기 재질"""
    enabled: bool = False
    escalators: bool = True
    depth: float = 0.6
    frame_h: float = 0.05
    frame_d: float = 0.05
    frame_material: str = "알루미늄 프레임"
    glass_t: float = 0.012
    glass_rgb: tuple = (150, 205, 190)
    glass_alpha: float = 0.35

    def check(self) -> None:
        for nm, v in (("깊이", self.depth), ("프레임 높이", self.frame_h), ("프레임 두께", self.frame_d),
                      ("유리 두께", self.glass_t)):
            if v <= 0:
                raise ValueError(f"제연경계벽 {nm}({v:g})는 0 보다 커야 합니다")
        if 2 * self.frame_h >= self.depth - 0.05:
            raise ValueError("제연경계벽 깊이가 위·아래 프레임 높이에 비해 너무 작습니다")
        if self.glass_t > self.frame_d:
            raise ValueError("제연경계벽 유리 두께가 프레임 두께보다 큽니다")
        if len(tuple(self.glass_rgb)) != 3 or any(not 0 <= int(c) <= 255 for c in self.glass_rgb):
            raise ValueError("제연경계벽 유리 색은 R, G, B 0 ~ 255 세 값이어야 합니다")
        if not 0 < self.glass_alpha <= 1:
            raise ValueError("제연경계벽 유리 불투명도는 0 보다 크고 1 이하여야 합니다")


def head_drop(cfg) -> float:
    """계단·ESC 자동 오프닝의 머리 높이 기준을 낮출 양 (제연경계벽을 쓰면 그 깊이)"""
    sb = getattr(cfg, "smoke_settings", None)
    return sb.depth if sb is not None and sb.enabled else 0.0
