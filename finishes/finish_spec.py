"""건축 마감 제원: 용도별 마감표 (바닥·벽·천장·천장틀). 실은 용도로 마감을 찾고, 실마다 다른 마감 종류로 덮어쓸 수 있다.

기본값은 실무 일반값을 따른 예시이며 마감 탭에서 고친다 (실무 마감표가 있으면 그 값으로).
"""
import dataclasses

FILL_MORTAR = "mortar"           # 바닥 마감재 아래를 몰탈로 채움
FILL_VOID = "void"               # 바닥 마감재 아래가 빈 공간 (액세스 플로어)
FILLS = (FILL_MORTAR, FILL_VOID)
FRAME_M = "M"                    # M바 (경량 천장틀, 숨김형)
FRAME_T = "T"                    # T바 (노출형 그리드)
FRAMES = (FRAME_M, FRAME_T)
FALLBACK = "기본"                # 마감표에 없는 용도가 쓰는 마감 종류


SKIRT_MIN = 0.005               # 걸레받이가 마감 표면에서 들어가려면 남아야 하는 최소 두께


@dataclasses.dataclass(frozen=True)
class WallPass:
    """벽 마감 한 벌의 배치 값 (패널 또는 걸레받이): 구조체 면 → 뒷면·앞면 (본체 벽·기둥 gap/face, 칸막이벽 pgap/pface),
    z0 = 바닥 마감면 위 시작 높이, z1 = 끝 높이 (None = 천장판 하면 등 벽 윗면)"""
    gap: float
    face: float
    pgap: float
    pface: float
    z0: float
    z1: float
    skirt: bool


@dataclasses.dataclass
class FinishType:
    """마감 종류 1개 (보통 실 용도 이름과 같음).
    바닥: ffl = 마감 높이 (구조 바닥 상면 → 마감면, 0 이면 바닥 마감 없음), floor_t = 마감재 두께 (마감면에서 아래로),
          floor_fill = 그 아래 (FILL_MORTAR 몰탈 채움 | FILL_VOID 빈 공간 = 액세스 플로어)
    벽: wall_t = 마감재 두께 (0 = 면처리, 형상 없음), 마감면 ~ 천장(없으면 위 슬래브 하면),
        partition_face = 칸막이벽·구획분리 벽 면 → 마감 표면 거리 (None = wall_t, 이격 없음 — 본체 벽 wall_face 와 따로)
        wall_face = 구조체 면 → 마감 표면 거리 (None = wall_t, 이격 없음). 마감재 뒷면 이격 = wall_face − wall_t (빈 공간,
        하지재 미모델링). 예) 금속패널: 표면 0.15, 판 T1.6 → 이격 0.1484 (실무 상세 WB-14). 기둥·승강로 둘레에도 같은 거리
    걸레받이: skirt_h = 높이 (0 = 없음), skirt_t = 두께, skirt_recess = 벽 마감 표면에서 들어간 거리, 벽 마감재는 걸레받이 윗면부터.
        본체 벽·칸막이벽·기둥·승강로 둘레·통로·출입구, 벽 마감이 있을 때(wall_t > 0)만
    천장 기구: light_s / light_t = 매입 조명 간격 (진행방향 s · 직교방향 t, 0 = 없음), diff_gap = 디퓨저 간격 (0 = 없음) — 천장이 있을 때만,
        천장판 격자 0.6 에 맞춰 자동 배치 (fixtures.fixture_layout)
    천장: ceiling = 천장 있음, ceiling_h = 바닥 마감면에서 천장판 하면까지, board_t = 천장판 두께,
          frame = M | T, bar_spacing = 천장틀 바(M/T) 간격 (t 방향으로 뻗은 바를 s 방향으로 배열),
          carrier_spacing = 캐링 채널 간격 (s 방향으로 뻗은 바를 t 방향으로 배열), bar 단면 = 폭 bar_w × 높이 bar_h,
          캐링 채널 단면 = carrier_w × carrier_h (바 위)
    """
    name: str = FALLBACK
    ffl: float = 0.1
    floor_t: float = 0.03
    floor_fill: str = FILL_MORTAR
    floor_material: str = "화강석"
    wall_t: float = 0.05
    wall_material: str = "금속패널"
    ceiling: bool = True
    ceiling_h: float = 3.0
    board_t: float = 0.01
    ceiling_material: str = "알루미늄 천장판"
    frame: str = FRAME_M
    bar_spacing: float = 0.6
    carrier_spacing: float = 0.9
    bar_w: float = 0.025
    bar_h: float = 0.025
    carrier_w: float = 0.012
    carrier_h: float = 0.038
    wall_face: float = None
    partition_face: float = None
    skirt_h: float = 0.0
    skirt_t: float = 0.03
    skirt_recess: float = 0.01
    skirt_material: str = "흑색 걸레받이"
    light_s: float = 0.0
    light_t: float = 0.0
    diff_gap: float = 0.0

    @property
    def has_light(self) -> bool:
        return bool(self.ceiling) and self.light_s > 0 and self.light_t > 0

    @property
    def has_diffuser(self) -> bool:
        return bool(self.ceiling) and self.diff_gap > 0

    @property
    def has_skirt(self) -> bool:
        """걸레받이를 만드는가 (벽이 면처리(wall_t 0)면 없음)"""
        return self.skirt_h > 0 and self.wall_t > 0

    def skirt_span(self, face: float) -> tuple:
        """구조체 면에서 잰 걸레받이 (뒷면, 앞면). face = 그 벽의 구조체 면 → 마감 표면 거리.
        앞면 = 마감 표면에서 skirt_recess 들어간 면. 이격이 모자라 들어갈 자리가 없으면(남는 두께 < SKIRT_MIN) 표면과 같은 면,
        두께는 구조체 면까지로 줄임"""
        front = face - self.skirt_recess
        if front < SKIRT_MIN - 1e-12:
            front = face
        return max(0.0, front - self.skirt_t), front

    def panel_pass(self) -> "WallPass":
        """벽 마감재(패널) 배치 값: 걸레받이가 있으면 그 윗면부터"""
        gap = self.wall_gap if self.wall_t > 0 else 0.0
        return WallPass(gap, gap + self.wall_t, self.pgap, self.pface, self.skirt_h if self.has_skirt else 0.0, None, False)

    def skirt_pass(self) -> "WallPass":
        """걸레받이 배치 값: 바닥 마감면 ~ skirt_h"""
        return WallPass(*self.skirt_span(self.face), *self.skirt_span(self.pface), 0.0, self.skirt_h, True)

    @property
    def pface(self) -> float:
        """칸막이벽·구획분리 벽 면 → 벽 마감 표면 거리 (partition_face 를 비우면 마감재 두께, 즉 이격 없음 — 본체 측벽의
        큰 이격(설비 공간)과 따로)"""
        return self.wall_t if self.partition_face is None else self.partition_face

    @property
    def pgap(self) -> float:
        return self.pface - self.wall_t

    @property
    def face(self) -> float:
        """구조체 면 → 벽 마감 표면 거리 (wall_face 를 비우면 마감재 두께, 즉 이격 없음)"""
        return self.wall_t if self.wall_face is None else self.wall_face

    @property
    def wall_gap(self) -> float:
        """구조체 면 → 마감재 뒷면 이격 (빈 공간)"""
        return self.face - self.wall_t

    @property
    def frame_depth(self) -> float:
        """천장판 상면 위 천장틀 높이 (바 + 캐링 채널)"""
        return self.bar_h + self.carrier_h


def default_finishes() -> dict:
    """용도별 기본 마감표 (이름 → FinishType). 기계·전기·공조실은 콘크리트 면처리 + 천장 없음, 통신실은 액세스 플로어,
    대합실·승강장층·복도·역무실·통로·기타·기본은 금속패널(T1.6, 구조면에서 표면까지 0.15 — 실무 상세 WB-14), 화장실 타일은 이격 없음"""
    panel = dict(wall_t=0.0016, wall_face=0.15, wall_material="금속패널")
    concrete = dict(ffl=0.0, floor_t=0.0, floor_material="콘크리트 면처리", wall_t=0.0, wall_material="콘크리트 면처리",
                    ceiling=False)
    table = [
        FinishType("대합실", **panel),
        FinishType("승강장층", **panel),
        FinishType("복도", **panel),
        FinishType("역무실", floor_material="타일", ceiling_h=2.7, **panel),
        FinishType("기계실", **concrete),
        FinishType("전기실", **concrete),
        FinishType("공조실", **concrete),
        FinishType("통신실", ffl=0.45, floor_t=0.035, floor_fill=FILL_VOID, floor_material="액세스 플로어",
                   wall_t=0.0, wall_material="콘크리트 면처리", ceiling_h=2.7),
        FinishType("화장실", floor_material="타일", wall_t=0.03, wall_material="타일", ceiling_h=2.7,
                   ceiling_material="방수 천장판"),
        FinishType("창고", floor_material="타일", wall_t=0.0, wall_material="콘크리트 면처리", ceiling=False),
        FinishType("통로", **panel),
        FinishType("기타", **panel),
        FinishType(FALLBACK, **panel),
    ]
    return {f.name: f for f in table}


STEP_PLATE = "plate"             # 판석 계단석: 디딤판·챌판 판석 + 아래 채움(몰탈)
STEP_SOLID = "solid"             # 통석 계단석: 한 단 전체가 돌 + 아래 깔 몰탈
STEP_CONCRETE = "concrete"       # 콘크리트 계단: 스텝 전체가 채움 콘크리트 (판석 없음)
STEP_METHODS = (STEP_PLATE, STEP_SOLID, STEP_CONCRETE)


@dataclasses.dataclass
class StairFinish:
    """계단 마감 (마감을 켜고 enabled 일 때). 구조 = 매끈한 경사 슬래브, 그 위에 스텝(계단석)을 올린다 — 지하철 계단 일반 구조.
    디딤판 높이는 아래층 바닥 마감면 ~ 위층 바닥 마감면을 같은 단높이로 나눈다 (각 층 실의 마감 높이 ffl).
    method: STEP_PLATE | STEP_SOLID | STEP_CONCRETE
    depth: 마감 디딤판 안쪽 모서리 선(계단참은 마감면) → 구조 슬래브 상면 연직 거리 (스텝 받침 두께)
    tread_t / riser_t: 디딤판·챌판 판석 두께 (판석), 계단참 판석도 tread_t (통석도 계단참은 판석)
    bed: 통석 아래 깔 몰탈 두께 (통석)
    nosing: 논슬립 (디딤판·계단참 앞 코에서 nosing_w 폭, 상면에서 nosing_t 깊이로 박음, 양 끝 nosing_end 띄움)
    stone_len: 계단석 한 장 길이 (계단 폭 방향, 보기 텍스처를 디딤판마다 한 장씩 맞출 때 — 폭을 이 길이에 가깝게 고르게 나눔)
    side_t: 노출된 계단 옆면 마감 두께 (0 = 없음, 벽에 붙은 쪽은 없음). 계단 폭 안쪽에 두고 구조·스텝은 그만큼 좁아짐"""
    enabled: bool = True
    method: str = STEP_PLATE
    material: str = "계단석"
    fill_material: str = "몰탈"
    depth: float = 0.1
    tread_t: float = 0.03
    riser_t: float = 0.02
    bed: float = 0.03
    nosing: bool = True
    nosing_w: float = 0.05
    nosing_t: float = 0.005
    nosing_end: float = 0.05
    nosing_material: str = "논슬립"
    side_t: float = 0.02
    side_material: str = "화강석"
    stone_len: float = 1.2

    def check(self, riser: float = None) -> None:
        """입력 검사 (riser = 실제 단높이, 주면 판석 두께와 비교)"""
        if self.method not in STEP_METHODS:
            raise ValueError(f"계단 마감 방식 '{self.method}' 은(는) {', '.join(STEP_METHODS)} 중 하나여야 합니다")
        for nm, v in (("받침 두께", self.depth), ("디딤판 두께", self.tread_t), ("챌판 두께", self.riser_t),
                      ("깔 몰탈 두께", self.bed), ("논슬립 폭", self.nosing_w), ("논슬립 깊이", self.nosing_t),
                      ("논슬립 끝 여유", self.nosing_end), ("옆면 마감 두께", self.side_t)):
            if v < 0:
                raise ValueError(f"계단 마감 {nm}({v:g})는 0 이상이어야 합니다")
        if self.stone_len <= 0:
            raise ValueError("계단석 한 장 길이는 0 보다 커야 합니다")
        if self.depth <= 0:
            raise ValueError("계단 마감 받침 두께는 0 보다 커야 합니다")
        if self.method == STEP_PLATE and self.depth < self.tread_t + 1e-6:
            raise ValueError(f"계단 마감 받침 두께({self.depth:g})가 디딤판 두께({self.tread_t:g})보다 커야 합니다")
        if self.method == STEP_SOLID and self.depth < self.bed + 1e-6:
            raise ValueError(f"계단 마감 받침 두께({self.depth:g})가 깔 몰탈 두께({self.bed:g})보다 커야 합니다")
        if self.nosing and self.nosing_t >= (self.tread_t if self.method == STEP_PLATE else self.depth):
            raise ValueError("논슬립 깊이가 디딤판 두께 이상입니다")
        if riser is not None and self.method == STEP_PLATE and self.tread_t >= riser:
            raise ValueError(f"디딤판 두께({self.tread_t:g})가 단높이({riser:.3f})보다 작아야 합니다")


@dataclasses.dataclass
class FinishSettings:
    """마감 공통 설정. enabled: 마감 생성 여부 (모델 기본은 끔 — 기존 출력 유지, GUI 는 켬)
    table: 마감 종류 이름 → FinishType (용도 이름과 같은 종류를 그 용도에 씀, 없으면 '기본')
    stair: 계단 마감 (StairFinish)"""
    enabled: bool = False
    table: dict = dataclasses.field(default_factory=default_finishes)
    stair: StairFinish = dataclasses.field(default_factory=StairFinish)

    def stair_finish(self):
        """계단 마감을 쓰면 StairFinish, 아니면 None"""
        return self.stair if self.enabled and self.stair is not None and self.stair.enabled else None

    def for_room(self, use: str, override: str = "") -> FinishType:
        key = (override or "").strip() or use.strip()
        if key in self.table:
            return self.table[key]
        if (override or "").strip():
            raise ValueError(f"마감 종류 '{override}' 이(가) 마감표에 없습니다")
        return self.table.get(FALLBACK) or FinishType()
