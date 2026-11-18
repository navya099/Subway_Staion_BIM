"""열차 정차 배치: 선로마다 차량·문 위치(s) 계산과 검증.

선두 정지 위치 front_s 에서 진행방향 반대쪽으로 차량을 이어 놓는다 (direction = +1 이면 차량 k 의 앞끝 s = front − 앞 차량 길이 합).
문 중심 s = 차량 앞끝 − direction × offset. 번호: 차량 = 선두부터 1, 문 = 차량 앞끝부터 1 → 표시 '차량-문' (예: 9-1).
"""
import math
from dataclasses import dataclass

from trains.train_spec import TRACKS

_EPS = 1e-6


@dataclass
class DoorPosition:
    track: str                   # 'L' | 'R'
    car_no: int                  # 선두부터 1
    door_no: int                 # 차량 앞끝부터 1
    s: float                     # 문 중심 s (정거장 로컬)
    width: float                 # 문 폭

    @property
    def label(self) -> str:
        return f"{self.car_no}-{self.door_no}"


@dataclass
class TrainPlacement:
    track: str
    direction: int
    front_s: float
    rear_s: float
    t: float                     # 선로 중심 t
    side: int                    # 승강장 쪽 (+1 = +t 승강장, −1 = −t)
    cars: list                   # [(차량 번호, 앞끝 s, 뒤끝 s)]
    doors: list                  # DoorPosition


def track_t(cfg, track: str) -> float:
    return (cfg.platform.track_spacing / 2.0) * (1.0 if track == "L" else -1.0)


def front_of(cfg, stop, train) -> float:
    """선두 정지 위치 (비우면 열차 중심 = 내공 중심)"""
    if stop.front_s is not None:
        return stop.front_s
    return cfg.station.length / 2.0 + stop.direction * train.length / 2.0


def layout_trains(cfg) -> list:
    """정차하는 선로마다 TrainPlacement (열차를 쓰지 않으면 빈 목록)"""
    ts = getattr(cfg, "train_settings", None)
    if ts is None or not ts.enabled:
        return []
    out = []
    for stop in ts.stops:
        d = stop.direction
        front = front_of(cfg, stop, ts.train)
        cars, doors, s = [], [], front
        for i, car in enumerate(ts.train.cars, start=1):
            a, b = s, s - d * car.length
            cars.append((i, a, b))
            for j, door in enumerate(car.doors, start=1):
                doors.append(DoorPosition(stop.track, i, j, a - d * door.offset, door.width))
            s = b
        side = 1 if stop.track == "L" else -1
        out.append(TrainPlacement(stop.track, d, front, s, track_t(cfg, stop.track), side, cars, doors))
    return out


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def check_train(cfg):
    """열차 입력 검사 (ValueError): 차량·문 치수, 문이 차량 안·서로 안 겹침, 선로·방향, 열차가 내공 길이 안"""
    ts = getattr(cfg, "train_settings", None)
    if ts is None or not ts.enabled:
        return
    tr = ts.train
    if tr.total_cars < 1:
        raise ValueError("열차: 차량이 1량 이상이어야 합니다")
    if not _finite(ts.mark_width) or ts.mark_width <= 0:
        raise ValueError(f"열차: 승하차 위치 표시 폭은 0보다 커야 합니다 ({ts.mark_width})")
    for i, car in enumerate(tr.cars, start=1):
        where = f"열차 {i}호차"
        if not _finite(car.length) or car.length <= 0:
            raise ValueError(f"{where}: 차량 길이는 0보다 커야 합니다 ({car.length})")
        if not car.doors:
            raise ValueError(f"{where}: 문이 1개 이상이어야 합니다")
        prev = None
        for j, door in enumerate(car.doors, start=1):
            if not _finite(door.width) or door.width <= 0:
                raise ValueError(f"{where} 문 {j}: 문 폭은 0보다 커야 합니다 ({door.width})")
            if not _finite(door.offset) or door.offset - door.width / 2 < -_EPS or door.offset + door.width / 2 > car.length + _EPS:
                raise ValueError(f"{where} 문 {j}: 문({door.offset:g} ± {door.width / 2:g})이 차량 길이(0 ~ {car.length:g}) 밖입니다")
            if prev is not None and door.offset - door.width / 2 < prev.offset + prev.width / 2 - _EPS:
                raise ValueError(f"{where} 문 {j}: 앞 문과 겹치거나 순서가 앞끝 기준 오름차순이 아닙니다")
            prev = door
    L = cfg.station.length
    tracks = [s.track for s in ts.stops]
    if len(set(tracks)) != len(tracks):
        raise ValueError("열차: 같은 선로에 정차가 두 번 있습니다")
    for stop in ts.stops:
        if stop.track not in TRACKS:
            raise ValueError(f"열차: 선로는 L 또는 R 이어야 합니다 ({stop.track!r})")
        if stop.direction not in (1, -1):
            raise ValueError(f"열차: 진행방향은 +1 또는 −1 이어야 합니다 ({stop.direction!r})")
        if stop.front_s is not None and not _finite(stop.front_s):
            raise ValueError(f"열차: 선두 정지 위치가 숫자가 아닙니다 ({stop.front_s!r})")
    for p in layout_trains(cfg):
        lo, hi = min(p.front_s, p.rear_s), max(p.front_s, p.rear_s)
        if lo < -1e-3 or hi > L + 1e-3:
            sta = cfg.station.start_station
            raise ValueError(f"열차({p.track} 선로): 정차한 열차 STA {sta + lo:.2f} ~ {sta + hi:.2f} 가 정거장 내공 "
                             f"STA {sta:.2f} ~ {sta + L:.2f} 를 벗어납니다 (선두 정지 위치 확인)")
