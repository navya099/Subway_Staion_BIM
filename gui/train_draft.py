"""열차 입력의 화면 비의존 모델 (문자열 초안 → TrainSettings 변환 + 검증).

편성 = 같은 차량 n 량 (선두 차량만 문 배치를 따로 줄 수 있음), 문 위치 = 차량 앞끝에서 문 중심까지 거리 (쉼표).
선로마다 정차 여부·진행방향·선두 정지 STA (비우면 열차 중심을 내공 중심에).
"""
from dataclasses import dataclass

from gui.column_draft import _num
from trains.train_spec import CarDoor, TrainSettings, TrainStop, make_train

DIRS = ["+s (종점 방향)", "−s (시점 방향)"]
_DIR = {DIRS[0]: 1, DIRS[1]: -1}
_SPEC = TrainSettings()
_CAR = _SPEC.train.cars[0]


def _offsets(text: str, where: str) -> list:
    parts = [x for x in str(text).replace(" ", "").split(",") if x]
    if not parts:
        raise ValueError(f"{where}: 문 위치를 하나 이상 입력하세요 (차량 앞끝에서 문 중심까지, 쉼표 구분)")
    return [_num(x, where, "문 위치") for x in parts]


@dataclass
class TrainDraft:
    """열차 입력 (입력창 문자열). l_* / r_* = 왼쪽(+t) / 오른쪽(−t) 선로"""
    enabled: bool = True
    cars: str = f"{_SPEC.train.total_cars}"
    car_length: str = f"{_CAR.length:g}"
    door_offsets: str = ", ".join(f"{d.offset:g}" for d in _CAR.doors)
    door_width: str = f"{_CAR.doors[0].width:g}"
    first_doors: str = ""                       # 비우면 다른 차량과 같음
    mark_width: str = f"{_SPEC.mark_width:g}"
    r_stop: bool = True
    r_dir: str = DIRS[0]
    r_front: str = ""
    l_stop: bool = True
    l_dir: str = DIRS[1]
    l_front: str = ""

    def to_settings(self, start_station: float) -> TrainSettings:
        if not self.enabled:
            return TrainSettings(enabled=False)
        try:
            n = int(str(self.cars).strip())
        except ValueError:
            raise ValueError(f"열차: 차량 수가 정수가 아닙니다 ('{self.cars}')") from None
        if n < 1:
            raise ValueError(f"열차: 차량 수는 1 이상이어야 합니다 ({n})")
        length = _num(self.car_length, "열차", "차량 길이", positive=True)
        w = _num(self.door_width, "열차", "문 폭", positive=True)
        doors = [CarDoor(o, w) for o in _offsets(self.door_offsets, "열차 문 위치")]
        first = [CarDoor(o, w) for o in _offsets(self.first_doors, "열차 선두 차량 문 위치")] if str(self.first_doors).strip() else None
        stops = []
        for track, on, d, front in (("R", self.r_stop, self.r_dir, self.r_front), ("L", self.l_stop, self.l_dir, self.l_front)):
            if not on:
                continue
            if d not in _DIR:
                raise ValueError(f"열차: 진행방향이 올바르지 않습니다 ('{d}')")
            fs = None if not str(front).strip() else _num(front, "열차", "선두 정지 STA") - start_station
            stops.append(TrainStop(track, _DIR[d], fs))
        return TrainSettings(enabled=True, train=make_train(n, length, doors, first), stops=stops,
                             mark_width=_num(self.mark_width, "열차", "승하차 표시 폭", positive=True))


def preview(d: TrainDraft, start_station: float) -> str:
    if not d.enabled:
        return "→ 열차 사용 안 함 (승하차 위치 표시 없음)"
    try:
        ts = d.to_settings(start_station)
    except ValueError:
        return "→ 입력값을 확인하세요"
    tr = ts.train
    return (f"→ {tr.total_cars}량 편성, 길이 {tr.length:g}m, 차량당 문 {len(tr.cars[-1].doors)}개 · "
            f"정차 선로 {len(ts.stops)}개 (선두 STA 를 비우면 열차 중심 = 승강장 중심)")
