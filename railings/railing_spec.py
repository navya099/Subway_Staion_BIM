"""계단·에스컬레이터 오프닝 유리난간 제원 (모든 오프닝 공통).

실무 사진 기준 단순 모델: 오프닝 가장자리 바깥 위층 바닥에 경계석(걸레받이 겸) → 그 위 얇은 판형 POST → POST 사이 유리판,
위쪽 파이프 레일 2개(바닥 쪽 면). 기본값은 일반값 예시 (실무 상세를 받으면 교체).
"""
import dataclasses


@dataclasses.dataclass
class RailingSettings:
    """유리난간. enabled: 생성 여부 (모델 기본 끔 — 기존 출력 유지, GUI 는 켬)
    escalators: 에스컬레이터 오프닝에도 둘지 (계단 오프닝은 항상)
    경계석: 오프닝 가장자리에서 바깥으로 curb_w, 위층 구조 바닥(슬래브 상면) ~ 바닥 마감면 + curb_h. ㅠ 형태 (실무):
            양 옆면 흑색 걸레받이 석재(두께 skirt_t, skirt_material) 위에 화강석 석판(두께 plate_t, curb_material, 경계석 폭 전체),
            그 사이 속채움(core_material)
    POST: 난간 중심선(경계석 가운데) 위, 중심선 방향 두께 post_w × 가로지르는 폭 post_d, 간격 post_spacing 이하로 고르게
    레일: 지름(정사각 단면 한 변) rail_d, 위 레일 윗면 = 바닥 마감면 + rail_h1, 아래 레일 중심 = 마감면 + rail_h2,
          POST 바닥 쪽 면에 붙음
    유리: 두께 glass_t, 경계석 위 glass_gap ~ 마감면 + rail_h1 − glass_top_gap, POST 와 post_gap 띄움,
          색 glass_rgb (0~255), 불투명도 glass_alpha (보기 모델)"""
    enabled: bool = False
    escalators: bool = True
    curb_w: float = 0.25
    curb_h: float = 0.15
    curb_material: str = "화강석"
    plate_t: float = 0.03
    skirt_t: float = 0.02
    skirt_material: str = "흑색 걸레받이"
    core_material: str = "몰탈"
    post_w: float = 0.015
    post_d: float = 0.06
    post_spacing: float = 1.2
    post_material: str = "스테인리스"
    rail_d: float = 0.05
    rail_h1: float = 1.2
    rail_h2: float = 0.95
    glass_t: float = 0.012
    glass_gap: float = 0.05
    glass_top_gap: float = 0.08
    post_gap: float = 0.01
    glass_rgb: tuple = (150, 205, 190)
    glass_alpha: float = 0.35

    @property
    def center(self) -> float:
        """오프닝 가장자리 → 난간 중심선 거리 (경계석 가운데)"""
        return self.curb_w / 2.0

    def check(self) -> None:
        pos = (("경계석 폭", self.curb_w), ("경계석 높이", self.curb_h), ("POST 두께", self.post_w), ("POST 폭", self.post_d),
               ("POST 간격", self.post_spacing), ("레일 지름", self.rail_d), ("위 레일 높이", self.rail_h1),
               ("아래 레일 높이", self.rail_h2), ("유리 두께", self.glass_t))
        for nm, v in pos:
            if v <= 0:
                raise ValueError(f"유리난간 {nm}({v:g})은(는) 0 보다 커야 합니다")
        if self.plate_t <= 0 or self.plate_t >= self.curb_h:
            raise ValueError(f"유리난간 경계석 석판 두께({self.plate_t:g})는 0 보다 크고 경계석 높이보다 작아야 합니다")
        if self.skirt_t <= 0 or 2 * self.skirt_t >= self.curb_w:
            raise ValueError(f"유리난간 걸레받이 두께({self.skirt_t:g})는 0 보다 크고 경계석 폭의 절반보다 작아야 합니다")
        for nm, v in (("유리 아래 띄움", self.glass_gap), ("유리 위 띄움", self.glass_top_gap), ("유리·POST 틈", self.post_gap)):
            if v < 0:
                raise ValueError(f"유리난간 {nm}({v:g})은(는) 0 이상이어야 합니다")
        if self.post_d < self.glass_t:
            raise ValueError("유리난간 POST 폭이 유리 두께보다 작습니다")
        if self.rail_h2 + self.rail_d / 2.0 > self.rail_h1 - self.rail_d + 1e-9:
            raise ValueError(f"아래 레일(마감면 + {self.rail_h2:g})이 위 레일과 겹칩니다")
        if self.rail_h2 - self.rail_d / 2.0 < self.curb_h + 1e-9:
            raise ValueError("아래 레일이 경계석보다 낮습니다")
        if self.rail_h1 - self.glass_top_gap <= self.curb_h + self.glass_gap + 0.1:
            raise ValueError("유리판 높이가 너무 작습니다 (레일 높이·경계석 높이·띄움을 확인하세요)")
        if self.post_spacing < self.post_w + 2 * self.post_gap + 0.1:
            raise ValueError("POST 간격이 너무 작습니다")
        if len(tuple(self.glass_rgb)) != 3 or any(not 0 <= int(c) <= 255 for c in self.glass_rgb):
            raise ValueError("유리 색은 R, G, B 0 ~ 255 세 값이어야 합니다")
        if not 0 < self.glass_alpha <= 1:
            raise ValueError("유리 불투명도는 0 보다 크고 1 이하여야 합니다")
