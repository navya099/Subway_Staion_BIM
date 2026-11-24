"""배치 객체(비품) 종류 등록부: 종류마다 입력 치수 + 형상(볼록 각기둥 조각). 새 종류는 @define 함수 하나를 더하면 된다.

객체 좌표 (x, y, z): 앞면 = +x, 왼쪽 = +y, z = 0 은 바닥 마감면(FLOOR·WALL) 또는 천장 하면(CEILING, 아래 −).
- FLOOR·HANG: 원점 = 평면 중심 / WALL: 원점 = 뒷면(벽 마감 표면) 가운데, 몸은 x > 0 / CEILING: 원점 = 평면 중심
조각 = 평면 볼록 다각형(반시계) × 높이 구간. image 가 있으면 그 조각의 image_face('+x' | '-x') 쪽 면에 그림 한 장.
"""
import math
from dataclasses import dataclass

FLOOR, WALL, CEILING, HANG = "floor", "wall", "ceiling", "hang"      # HANG = 바닥 기준 높이에 매달림 (아래 바닥은 검사 안 함)
NUM, INT, TEXT = "num", "int", "text"

STEEL, DARK, RED, GLASS_, WOOD, BLUE, WHITE = ("스테인리스", "비품 검정", "비품 빨강", "비품 유리", "비품 목재", "비품 파랑", "비품 흰색")


@dataclass
class PropPart:
    material: str
    poly: tuple                   # ((x, y), …) 볼록, 반시계
    z0: float
    z1: float
    image: str = ""               # 그림 이름 (images 사전의 키)
    image_face: str = "+x"

    @property
    def volume(self) -> float:
        a = sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(self.poly, self.poly[1:] + self.poly[:1])) / 2.0
        return a * (self.z1 - self.z0)


@dataclass
class PropField:
    key: str
    label: str
    default: object
    type: str = NUM
    lo: float = 0.0               # 이보다 커야 함 (NUM·INT)


@dataclass
class PropKind:
    code: str
    label: str
    mount: str
    fields: list
    build: object                 # 값 사전 → [PropPart]
    images: object = None         # 값 사전 → {그림 이름: PIL 이미지 함수}
    ifc: tuple = ("IfcBuildingElementProxy", "USERDEFINED")
    material: str = STEEL         # IFC 대표 재질


KINDS: dict = {}


def define(code, label, mount, fields, ifc=("IfcBuildingElementProxy", "USERDEFINED"), material=STEEL, images=None):
    def deco(fn):
        KINDS[code] = PropKind(code, label, mount, [PropField(*f) for f in fields], fn, images, ifc, material)
        return fn
    return deco


def box(material, x0, x1, y0, y1, z0, z1, **kw) -> PropPart:
    return PropPart(material, ((x0, y0), (x1, y0), (x1, y1), (x0, y1)), z0, z1, **kw)


def cyl(material, cx, cy, r, z0, z1, n=12) -> PropPart:
    return PropPart(material, tuple((cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)), z0, z1)


# ===================================================== 바닥에 놓는 비품
@define("BENCH", "의자 (벤치)", FLOOR, [("w", "길이", 1.8, NUM, 0.4), ("d", "깊이", 0.5, NUM, 0.25), ("seat_h", "앉는 높이", 0.42, NUM, 0.2),
                                     ("back_h", "등받이 높이", 0.85, NUM, 0.5)], ("IfcFurniture", "CHAIR"), WOOD)
def _bench(v):
    w, d, h, b = v["w"], v["d"], v["seat_h"], v["back_h"]
    xb = -d / 2 + 0.06
    out = [box(WOOD, xb, d / 2, -w / 2, w / 2, h - 0.04, h), box(WOOD, -d / 2, -d / 2 + 0.04, -w / 2, w / 2, h + 0.1, b)]
    for y in (-(w / 2 - 0.2), w / 2 - 0.2):
        out += [box(STEEL, xb, d / 2 - 0.04, y - 0.025, y + 0.025, 0.0, h - 0.04), box(STEEL, -d / 2, -d / 2 + 0.04, y - 0.025, y + 0.025, 0.0, h + 0.1)]
    for y in (-w / 2, w / 2 - 0.04):                         # 팔걸이
        out += [box(STEEL, d / 2 - 0.08, d / 2 - 0.04, y, y + 0.04, h, h + 0.18), box(STEEL, xb, d / 2 - 0.02, y, y + 0.04, h + 0.18, h + 0.21)]
    return out


@define("BIN", "쓰레기통", FLOOR, [("n", "칸 수", 2, INT, 0), ("w", "칸 폭", 0.4, NUM, 0.15), ("d", "깊이", 0.4, NUM, 0.15), ("h", "높이", 0.9, NUM, 0.4)],
        ("IfcFurniture", "USERDEFINED"))
def _bin(v):
    n, w, d, h = v["n"], v["w"], v["d"], v["h"]
    out = []
    for k in range(n):
        y0 = -n * w / 2 + k * w
        out += [box(STEEL, -d / 2, d / 2, y0, y0 + w, 0.0, h - 0.2), box(DARK if k % 2 == 0 else BLUE, -d / 2 + 0.02, d / 2 - 0.02, y0 + 0.02, y0 + w - 0.02, h - 0.2, h - 0.05),
                box(STEEL, -d / 2, d / 2, y0, y0 + w, h - 0.05, h)]
    return out


@define("EXT", "소화기 (받침대)", FLOOR, [("h", "통 높이", 0.5, NUM, 0.2), ("r", "통 반지름", 0.08, NUM, 0.03)], ("IfcFireSuppressionTerminal", "USERDEFINED"), RED)
def _ext(v):
    h, r = v["h"], v["r"]
    s = r + 0.07
    return [box(RED, -s, s, -s, s, 0.0, 0.06), cyl(RED, 0, 0, r, 0.06, 0.06 + h, 16), cyl(DARK, 0, 0, 0.025, 0.06 + h, 0.14 + h, 8)]


def _tvm_images(v):
    from props.prop_images import ticket_machine
    return {"front": lambda: ticket_machine(v["w"], v["h"], v["text"])}


@define("TVM", "발매기", FLOOR, [("w", "폭", 0.9, NUM, 0.4), ("d", "깊이", 0.75, NUM, 0.3), ("h", "높이", 1.9, NUM, 1.0), ("text", "표시 글자", "승차권 발매기", TEXT)],
        ("IfcElectricAppliance", "VENDINGMACHINE"), STEEL, _tvm_images)
def _tvm(v):
    w, d, h = v["w"], v["d"], v["h"]
    return [box(STEEL, -d / 2, d / 2 - 0.005, -w / 2, w / 2, 0.0, h), box(WHITE, d / 2 - 0.005, d / 2, -w / 2, w / 2, 0.0, h, image="front")]


@define("GATE", "게이트 (개찰구)", FLOOR, [("n", "통로 수", 4, INT, 0), ("lane", "통로 폭", 0.6, NUM, 0.5), ("wide", "넓은 통로 폭 (0 = 없음)", 0.9, NUM, -1e-9),
                                       ("cab", "캐비닛 폭", 0.2, NUM, 0.1), ("length", "길이", 1.9, NUM, 0.5), ("h", "높이", 1.0, NUM, 0.5)])
def _gate(v):
    n, lane, wide, cab, ln, h = v["n"], v["lane"], v["wide"], v["cab"], v["length"], v["h"]
    lanes = [lane] * n + ([wide] if wide > 0 else [])
    total = sum(lanes) + cab * (len(lanes) + 1)
    y, out = -total / 2, []
    for k in range(len(lanes) + 1):
        out += [box(STEEL, -ln / 2, ln / 2, y, y + cab, 0.0, h - 0.03), box(DARK, -ln / 2, ln / 2, y, y + cab, h - 0.03, h)]
        if k < len(lanes):                                   # 카드 단말 (앞쪽 위)
            out.append(box(BLUE, ln / 2 - 0.45, ln / 2 - 0.15, y + 0.02, y + cab - 0.02, h, h + 0.05))
            y += cab + lanes[k]
    return out


# ===================================================== 벽에 붙는 것
def _hydrant_images(v):
    from props.prop_images import hydrant
    return {"front": lambda: hydrant(v["w"], v["h"])}


@define("HYDRANT", "옥내소화전", WALL, [("w", "폭", 0.7, NUM, 0.3), ("h", "높이", 1.2, NUM, 0.4), ("d", "깊이", 0.2, NUM, 0.05), ("z", "바닥에서 하단", 0.3, NUM, -1e-9)],
        ("IfcFireSuppressionTerminal", "HOSEREEL"), STEEL, _hydrant_images)
def _hydrant(v):
    w, h, d, z = v["w"], v["h"], v["d"], v["z"]
    return [box(STEEL, 0.0, d - 0.005, -w / 2, w / 2, z, z + h), box(WHITE, d - 0.005, d, -w / 2, w / 2, z, z + h, image="front"),
            box(RED, 0.0, 0.06, -0.04, 0.04, z + h + 0.03, z + h + 0.11)]          # 위치 표시등


def _panel(w, h, z, t, x0=0.0):
    f = 0.03
    return [box(STEEL, x0, x0 + t, -w / 2, -w / 2 + f, z, z + h), box(STEEL, x0, x0 + t, w / 2 - f, w / 2, z, z + h),
            box(STEEL, x0, x0 + t, -w / 2 + f, w / 2 - f, z, z + f), box(STEEL, x0, x0 + t, -w / 2 + f, w / 2 - f, z + h - f, z + h),
            box(WHITE, x0, x0 + t * 0.6, -w / 2 + f, w / 2 - f, z + f, z + h - f)]


@define("PANEL_W", "벽 점검구", WALL, [("w", "폭", 0.6, NUM, 0.15), ("h", "높이", 0.6, NUM, 0.15), ("t", "두께", 0.02, NUM, 0.002), ("z", "바닥에서 하단", 0.3, NUM, -1e-9)])
def _panel_w(v):
    return _panel(v["w"], v["h"], v["z"], v["t"])


@define("PANEL_C", "천장 점검구", CEILING, [("w", "폭", 0.6, NUM, 0.15), ("d", "길이", 0.6, NUM, 0.15), ("t", "두께", 0.02, NUM, 0.002)])
def _panel_c(v):
    w, d, t, f = v["w"], v["d"], v["t"], 0.03
    return [box(STEEL, -d / 2, d / 2, -w / 2, -w / 2 + f, -t, 0.0), box(STEEL, -d / 2, d / 2, w / 2 - f, w / 2, -t, 0.0),
            box(STEEL, -d / 2, -d / 2 + f, -w / 2 + f, w / 2 - f, -t, 0.0), box(STEEL, d / 2 - f, d / 2, -w / 2 + f, w / 2 - f, -t, 0.0),
            box(WHITE, -d / 2 + f, d / 2 - f, -w / 2 + f, w / 2 - f, -t * 0.6, 0.0)]


# ===================================================== 등록부에 없는 물건 = 외부 3D 모델 (모양은 model_spec, 파일을 못 읽으면 마지막 크기의 상자)
MODEL_KINDS = ("MODEL_F", "MODEL_W", "MODEL_C", "MODEL_H")
EMPTY_SIZE = (0.5, 0.5, 0.5)


def size_box(mount, size, z=0.0) -> PropPart:
    """외곽 상자 (크기 = 깊이 x, 폭 y, 높이 z) — 기준점은 모델과 같은 규칙"""
    d, w, h = size
    x0 = 0.0 if mount == WALL else -d / 2
    z0 = -h if mount == CEILING else z
    return box(WHITE, x0, x0 + d, -w / 2, w / 2, z0, z0 + h)


def _define_models():
    z = ("z", "바닥에서 하단", 0.3, NUM, -1e-9)
    for code, word, mount, fields in (("MODEL_F", "바닥", FLOOR, []), ("MODEL_W", "벽", WALL, [z]), ("MODEL_C", "천장", CEILING, []),
                                      ("MODEL_H", "매달림", HANG, [("z", "바닥에서 하단", 2.5, NUM, 0.5)])):
        define(code, f"외부 모델 ({word})", mount, fields, material=WHITE)(
            lambda v, m=mount: [size_box(m, v.get("size") or EMPTY_SIZE, v.get("z", 0.0))])


_define_models()


# ===================================================== 매달림 안내사인 (높이는 바닥 기준이라 천장까지 거리 'ceil' 을 받음)
ROD = 0.01                        # 행거 반폭


def rod_ys(w: float) -> tuple:
    """행거 기본 자리 (양 끝에서 0.2, 좁은 사인은 비례)"""
    y = w / 2 - 0.2 * min(w, 1.5) / 1.5
    return -y, y


def _hsign_images(v):
    from props.prop_images import hanging_sign
    return {"front": lambda: hanging_sign(v["w"], v["h"], v["text"], v["arrow"], v["bg"]),
            "back": lambda: hanging_sign(v["w"], v["h"], v["text2"] or v["text"], v["arrow2"], v["bg"])}


@define("HSIGN", "매달림 안내사인", HANG, [("w", "폭", 2.4, NUM, 0.3), ("h", "높이", 0.45, NUM, 0.1), ("t", "두께", 0.1, NUM, 0.02), ("z", "바닥에서 하단", 2.5, NUM, 2.0),
                                        ("text", "앞면 문구 (/ 로 줄)", "갈아타는 곳/Transfer", TEXT), ("arrow", "앞면 화살표 (←→↑↓)", "↑", TEXT),
                                        ("text2", "뒷면 문구 (비우면 앞면)", "", TEXT), ("arrow2", "뒷면 화살표", "", TEXT), ("bg", "배경색", "#14203F", TEXT)],
        material=STEEL, images=_hsign_images)
def _hsign(v):
    """v['rods'] = 행거 y 두 자리 (없으면 rod_ys — 엔진이 천장 기구를 피해 옮겨 줌)"""
    w, h, t, z, e = v["w"], v["h"], v["t"], v["z"], 0.002
    out = [box(DARK, -t / 2 + e, t / 2 - e, -w / 2, w / 2, z, z + h),
           box(WHITE, t / 2 - e, t / 2, -w / 2, w / 2, z, z + h, image="front"),
           box(WHITE, -t / 2, -t / 2 + e, -w / 2, w / 2, z, z + h, image="back", image_face="-x")]
    if v.get("ceil", 0.0) > z + h + 1e-6:
        out += [box(STEEL, -ROD, ROD, y - ROD, y + ROD, z + h, v["ceil"]) for y in v.get("rods") or rod_ys(w)]
    return out
