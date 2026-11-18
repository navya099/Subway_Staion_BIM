"""승강장 스크린도어(PSD) 입력.

유닛(입면 4.8m 예시) = 고정부 | 가동문 | 가동문 | 고정부(한쪽은 비상문 겸용), 위에 구동부(헤더), 유닛 양옆에 POST.
열차(cfg.train_settings)의 문 중심에 유닛 중심(두 가동문 사이)을 맞춘다. 유닛 사이가 벌어지면 고정 패널로 채운다.
치수는 입면 상세도(고정부 1.35 · 가동문 1.05 × 2 · 문 높이 2.0 · 구동부 0.4)와 일반값 예시이며 승강장 탭에서 고친다.
"""
import dataclasses

EMERGENCY_SIDES = ("+s", "-s", "")       # 비상문 겸용 고정부 쪽 ('' = 없음)


@dataclasses.dataclass
class PsdSettings:
    """enabled: 생성 여부 (모델 기본 끔 — 기존 출력 유지, GUI 는 켬). 열차를 써야 함
    edge_offset: 승강장 끝단(선로 쪽)에서 PSD 중심선까지 거리 (m)
    fixed_w / door_w: 고정부 폭 / 가동문 한 짝 폭 (s 방향) → 유닛 폭 = 2 × (fixed_w + door_w)
    door_h: 문(고정부·가동문) 높이, header_h: 구동부(헤더) 높이 — 바닥 = 승강장 바닥 마감면 (마감 없으면 승강장 상면)
    post_w / post_d: POST 단면 (s 폭 × t 깊이), header_d: 구동부 깊이 (t)
    frame_w / frame_d: 패널 프레임 부재 폭(입면) / 두께(t), kick_h: 패널 하부 레일(킥플레이트) 높이, glass_t: 유리 두께
    emergency: 비상문 겸용 고정부 쪽 ('+s' | '-s' | '' 없음), fill_max: 유닛 사이 채움 고정 패널 한 장의 최대 폭"""
    enabled: bool = False
    edge_offset: float = 0.3
    fixed_w: float = 1.35
    door_w: float = 1.05
    door_h: float = 2.0
    header_h: float = 0.4
    post_w: float = 0.2
    post_d: float = 0.2
    header_d: float = 0.35
    frame_w: float = 0.05
    frame_d: float = 0.05
    kick_h: float = 0.1
    glass_t: float = 0.008
    emergency: str = "+s"
    fill_max: float = 1.5

    @property
    def unit_w(self) -> float:
        return 2.0 * (self.fixed_w + self.door_w)

    @property
    def height(self) -> float:
        return self.door_h + self.header_h
