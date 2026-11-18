"""열차(편성) 정의와 선로별 정차 위치.

Train = 차량(Car) 목록 (앞 → 뒤, 첫 차량 is_first), Car = 길이 + 문(CarDoor) 목록, CarDoor = 차량 앞끝(진행방향)에서 문 중심까지 거리 + 폭.
열차가 정해지면 승강장의 승하차 위치 표시(점자블록), 이후 스크린도어(PSD) 가동문 위치가 같은 문 위치에서 정해진다.
선로: 'L' = 왼쪽 선로 (t = +D/2), 'R' = 오른쪽 선로 (t = −D/2). 각 선로의 승강장은 그 선로 바깥쪽(같은 t 부호) 승강장.
"""
import dataclasses
from typing import Optional

TRACKS = ("L", "R")
TRACK_LABEL = {"L": "왼쪽 선로(+t)", "R": "오른쪽 선로(−t)"}


@dataclasses.dataclass
class CarDoor:
    """차량 문 1개. offset = 차량 앞끝(진행방향 앞)에서 문 중심까지 거리 (m), width = 문 폭 (m)"""
    offset: float = 2.5
    width: float = 1.2


def default_doors(length: float = 20.0, count: int = 4, width: float = 1.2) -> list:
    """차량 길이를 문 수로 고르게 나눈 칸의 가운데 (예시: 20m 4도어 → 2.5, 7.5, 12.5, 17.5)"""
    pitch = length / count
    return [CarDoor(pitch * (k + 0.5), width) for k in range(count)]


@dataclasses.dataclass
class Car:
    """차량 1량. 문은 양쪽 측면 같은 위치 (승강장 쪽 문만 쓴다)"""
    length: float = 20.0
    doors: list = dataclasses.field(default_factory=default_doors)
    is_first: bool = False


@dataclasses.dataclass
class Train:
    """편성. cars[0] = 선두 차량"""
    cars: list = dataclasses.field(default_factory=list)

    @property
    def total_cars(self) -> int:
        return len(self.cars)

    @property
    def length(self) -> float:
        return sum(c.length for c in self.cars)


def make_train(n_cars: int = 8, car_length: float = 20.0, doors=None, first_doors=None) -> Train:
    """같은 차량 n 량 편성 (doors = CarDoor 목록, first_doors 가 있으면 선두 차량만 그 배치)"""
    doors = doors if doors is not None else default_doors(car_length)
    cars = []
    for k in range(n_cars):
        ds = first_doors if (k == 0 and first_doors is not None) else doors
        cars.append(Car(length=car_length, doors=[dataclasses.replace(d) for d in ds], is_first=k == 0))
    return Train(cars)


@dataclasses.dataclass
class TrainStop:
    """선로 하나의 정차. front_s = 선두(열차 앞끝) 정지 위치 s (정거장 로컬, None = 열차 중심을 내공 중심에),
    direction = 진행방향 (+1 = 종점 방향 +s, −1 = 시점 방향 −s)"""
    track: str = "R"
    direction: int = 1
    front_s: Optional[float] = None


@dataclasses.dataclass
class TrainSettings:
    """열차 설정. enabled: 사용 여부 (모델 기본 끔), stops: 정차하는 선로 목록,
    mark_width: 승하차 위치 표시(점자블록) 폭 (s 방향, 문 중심 기준)"""
    enabled: bool = False
    train: Train = dataclasses.field(default_factory=make_train)
    stops: list = dataclasses.field(default_factory=lambda: [TrainStop("R", 1), TrainStop("L", -1)])
    mark_width: float = 1.8
